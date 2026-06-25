"""GPU droplet orchestration — the only genuinely new infrastructure layer.

Two control channels (see docs/BENCHMARKING_FEATURE.md §4):
  - DO REST API over httpx  → create / poll / destroy droplets, (de)register SSH keys.
  - SSH over paramiko       → deploy / benchmark (added in later steps).

Long-running ops run on worker.py's ThreadPoolExecutor and stream progress through
the shared progress_store, exactly like evaluations do. SSE in routers reads it.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from database import get_db, oid
from encryption import decrypt_api_key, encrypt_api_key
from worker import executor, progress_store

logger = logging.getLogger(__name__)

DO_API = "https://api.digitalocean.com"
PROVISION_TIMEOUT_S = 600   # 10 min for a droplet to reach `active` + IP
POLL_INTERVAL_S = 5
NEW_DROPLET_GRACE_S = 90    # tolerate transient 404s right after create


# ── progress helpers (mirror worker.py) ──────────────────────────────────────

def _upd(key: str, **kw: Any) -> None:
    progress_store.setdefault(key, {}).update(kw)


def _evt(key: str, event: str, **data: Any) -> None:
    entry = {"event": event, "ts": datetime.utcnow().isoformat(), **data}
    store = progress_store.setdefault(key, {"events": []})
    store.setdefault("events", []).append(entry)
    store["events"] = store["events"][-200:]


# ── DO REST API helpers ───────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def options_token() -> str:
    """Token used ONLY to fetch the DO catalog (regions/sizes/images) for the
    create form. Separate from the per-droplet token the user enters to actually
    create/destroy a droplet."""
    return os.getenv("DO_API_TOKEN", "").strip()


def _generate_keypair() -> tuple[str, str]:
    """Return (private_key_pem, public_key_openssh). One keypair per droplet."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode()
    return priv, pub


class DOError(RuntimeError):
    """A DigitalOcean API error carrying the status code + DO's own message,
    so the real reason (e.g. 'image not available for this size') reaches the UI
    instead of httpx's generic 'Client error 404 for url ...'."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


def _check(r: httpx.Response, ctx: str, ok: tuple[int, ...] = (200, 201, 202, 204)) -> httpx.Response:
    if r.status_code in ok:
        return r
    try:
        body = r.json()
        msg = body.get("message") or body.get("id") or r.text
    except Exception:
        msg = (r.text or "").strip() or r.reason_phrase
    raise DOError(r.status_code, f"{ctx} failed — DigitalOcean {r.status_code}: {msg}")


def _register_ssh_key(client: httpx.Client, token: str, name: str, public_key: str) -> int:
    r = _check(client.post(f"{DO_API}/v2/account/keys", headers=_headers(token),
                           json={"name": name, "public_key": public_key}),
               "Register SSH key")
    return r.json()["ssh_key"]["id"]


def _delete_ssh_key(client: httpx.Client, token: str, key_id: int) -> None:
    r = client.delete(f"{DO_API}/v2/account/keys/{key_id}", headers=_headers(token))
    if r.status_code != 404:
        _check(r, "Delete SSH key")


def _create_droplet(client: httpx.Client, token: str, cfg: dict, ssh_key_id: int) -> int:
    r = _check(client.post(f"{DO_API}/v2/droplets", headers=_headers(token), json={
        "name":     cfg["name"],
        "region":   cfg["region"],
        "size":     cfg["size_slug"],
        "image":    cfg.get("image") or "ubuntu-22-04-x64",
        "ssh_keys": [ssh_key_id],
        "tags":     ["crest", "crest-benchmark"],
    }), "Create droplet")
    return r.json()["droplet"]["id"]


def _get_droplet(client: httpx.Client, token: str, do_droplet_id: int) -> dict:
    r = _check(client.get(f"{DO_API}/v2/droplets/{do_droplet_id}", headers=_headers(token)),
               "Get droplet")
    return r.json()["droplet"]


def _delete_droplet(client: httpx.Client, token: str, do_droplet_id: int) -> None:
    r = client.delete(f"{DO_API}/v2/droplets/{do_droplet_id}", headers=_headers(token))
    if r.status_code != 404:
        _check(r, "Delete droplet")


def _public_ipv4(droplet: dict) -> str | None:
    for net in droplet.get("networks", {}).get("v4", []):
        if net.get("type") == "public":
            return net.get("ip_address")
    return None


def _hourly_price(client: httpx.Client, token: str, size_slug: str) -> float | None:
    """Look up hourly price from the DO size catalog (for cost-to-date display)."""
    try:
        r = client.get(f"{DO_API}/v2/sizes", headers=_headers(token), params={"per_page": 200})
        r.raise_for_status()
        for size in r.json().get("sizes", []):
            if size.get("slug") == size_slug:
                return size.get("price_hourly")
    except Exception as exc:
        logger.warning(f"Could not fetch size price for {size_slug}: {exc}")
    return None


def _size_category(slug: str, description: str) -> str:
    """Map a DO size slug to its plan family (mirrors the DO plan tabs)."""
    if slug.startswith("gpu-"):                         return "GPU"
    if slug.startswith("s-"):                           return "Basic"
    if slug.startswith(("g-", "gd-")):                  return "General Purpose"
    if slug.startswith(("c-", "c2-")):                  return "CPU-Optimized"
    if slug.startswith(("m-", "m3-", "m6-")):           return "Memory-Optimized"
    if slug.startswith(("so-", "so1_5-")):              return "Storage-Optimized"
    return description or "Other"


def fetch_droplet_options(token: str) -> dict:
    """Live-fetch the FULL DO catalog for the create form: every region, every
    size (categorized by plan family), and distribution images. The frontend
    decides what to surface vs. default. Mirrors the DO create-droplet page.
    """
    headers = _headers(token)
    with httpx.Client(timeout=30) as client:
        sr = client.get(f"{DO_API}/v2/sizes", headers=headers, params={"per_page": 200})
        sr.raise_for_status()
        rr = client.get(f"{DO_API}/v2/regions", headers=headers, params={"per_page": 200})
        rr.raise_for_status()
        ir = client.get(f"{DO_API}/v2/images", headers=headers,
                        params={"type": "distribution", "per_page": 200})
        ir.raise_for_status()

    regions = [
        {"slug": r["slug"], "name": r.get("name") or r["slug"], "available": bool(r.get("available", True))}
        for r in rr.json().get("regions", [])
    ]
    regions.sort(key=lambda r: r["name"])

    sizes = []
    for s in sr.json().get("sizes", []):
        slug = s.get("slug", "")
        if not slug:
            continue
        gpu = s.get("gpu_info") or {}
        vram = gpu.get("vram") if isinstance(gpu.get("vram"), dict) else {}
        vram_gb = vram.get("amount")
        if vram_gb and str(vram.get("unit", "")).lower().startswith("m"):
            vram_gb = round(vram_gb / 1024)
        desc = s.get("description") or ""
        sizes.append({
            "slug": slug,
            "category": _size_category(slug, desc),
            "description": desc or slug,
            "vcpus": s.get("vcpus"),
            "memory_gb": round((s.get("memory") or 0) / 1024) or None,   # DO memory is MB
            "disk_gb": s.get("disk"),
            "price_hourly": s.get("price_hourly"),
            "price_monthly": s.get("price_monthly"),
            "available": bool(s.get("available")),
            "regions": s.get("regions", []),
            "gpu_count": gpu.get("count"),
            "gpu_model": gpu.get("model"),
            "gpu_vram_gb": vram_gb,
        })
    sizes.sort(key=lambda x: (x.get("price_hourly") or 0))

    images = []
    for im in ir.json().get("images", []):
        if not im.get("slug") or im.get("public") is False:
            continue
        images.append({
            "slug": im["slug"],
            "name": im.get("name") or im["slug"],
            "distribution": im.get("distribution") or "",
        })
    images.sort(key=lambda x: (x["distribution"], x["name"]))

    return {"sizes": sizes, "regions": regions, "images": images}


# ── Public job submitters ─────────────────────────────────────────────────────

def submit_create_droplet(droplet_id: str) -> None:
    progress_store[droplet_id] = {"status": "provisioning", "events": []}
    executor.submit(_provision_droplet, droplet_id)


def submit_destroy_droplet(droplet_id: str) -> None:
    progress_store.setdefault(droplet_id, {"events": []})["status"] = "destroying"
    executor.submit(_destroy_droplet_job, droplet_id)


# ── Executor jobs ─────────────────────────────────────────────────────────────

def _provision_droplet(droplet_id: str) -> None:
    db = get_db()
    key = droplet_id
    try:
        doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
        if not doc:
            logger.error(f"Droplet {droplet_id} not found")
            return
        token = decrypt_api_key(doc.get("do_token_encrypted"))
        if not token:
            raise RuntimeError("Missing or undecryptable DO API token")

        _upd(key, status="provisioning")
        _evt(key, "droplet_provisioning", name=doc["name"], region=doc["region"], size=doc["size_slug"])

        with httpx.Client(timeout=60) as client:
            # 1. SSH keypair → register public key with DO.
            priv, pub = _generate_keypair()
            ssh_key_id = _register_ssh_key(client, token, f"crest-{droplet_id}", pub)
            db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
                "ssh_public_key": pub,
                "ssh_private_key_encrypted": encrypt_api_key(priv),
                "do_ssh_key_id": ssh_key_id,
            }})
            _evt(key, "ssh_key_registered", do_ssh_key_id=ssh_key_id)

            # 2. Create droplet.
            do_droplet_id = _create_droplet(client, token, doc, ssh_key_id)
            db.gpu_droplets.update_one({"_id": oid(droplet_id)},
                                       {"$set": {"do_droplet_id": do_droplet_id}})
            _evt(key, "droplet_created", do_droplet_id=do_droplet_id)

            # 3. Poll until active + public IP (or time out). DO can briefly 404 a
            #    just-created droplet, so tolerate 404s during a short grace window;
            #    a persistent 404 means DO accepted the create but never built it.
            deadline = time.monotonic() + PROVISION_TIMEOUT_S
            grace_deadline = time.monotonic() + NEW_DROPLET_GRACE_S
            ip = None
            while time.monotonic() < deadline:
                try:
                    d = _get_droplet(client, token, do_droplet_id)
                except DOError as e:
                    if e.status_code == 404 and time.monotonic() < grace_deadline:
                        _upd(key, do_status="pending")
                        time.sleep(POLL_INTERVAL_S)
                        continue
                    if e.status_code == 404:
                        raise RuntimeError(
                            f"DigitalOcean accepted the droplet (id {do_droplet_id}) but it never "
                            f"appeared — usually an invalid image/size/region combination or a quota "
                            f"limit. Check that image '{doc.get('image')}' is valid for size "
                            f"'{doc['size_slug']}' in region '{doc['region']}'."
                        ) from e
                    raise
                status = d.get("status")
                ip = _public_ipv4(d)
                _upd(key, do_status=status, ip=ip)
                if status == "active" and ip:
                    break
                time.sleep(POLL_INTERVAL_S)
            else:
                raise TimeoutError(f"Droplet not active within {PROVISION_TIMEOUT_S}s")

            price = _hourly_price(client, token, doc["size_slug"])

        db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
            "status": "active", "status_detail": None, "ip": ip,
            "hourly_price_usd": price,
        }})
        _upd(key, status="active", ip=ip, hourly_price_usd=price)
        _evt(key, "droplet_ready", ip=ip, hourly_price_usd=price)
        _evt(key, "done")

    except Exception as exc:
        logger.exception(f"Droplet {droplet_id} provisioning failed")
        try:
            db.gpu_droplets.update_one({"_id": oid(droplet_id)},
                                       {"$set": {"status": "failed", "status_detail": str(exc)}})
        except Exception:
            pass
        _upd(key, status="failed", status_detail=str(exc))
        _evt(key, "droplet_failed", error=str(exc))


def _destroy_droplet_job(droplet_id: str) -> None:
    db = get_db()
    key = droplet_id
    try:
        doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
        if not doc:
            logger.error(f"Droplet {droplet_id} not found")
            return
        token = decrypt_api_key(doc.get("do_token_encrypted"))

        _upd(key, status="destroying")
        _evt(key, "droplet_destroying")

        with httpx.Client(timeout=60) as client:
            if doc.get("do_droplet_id"):
                _delete_droplet(client, token, doc["do_droplet_id"])
                _evt(key, "droplet_deleted", do_droplet_id=doc["do_droplet_id"])
            if doc.get("do_ssh_key_id"):
                _delete_ssh_key(client, token, doc["do_ssh_key_id"])
                _evt(key, "ssh_key_deleted", do_ssh_key_id=doc["do_ssh_key_id"])

        db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
            "status": "destroyed", "status_detail": None,
            "ip": None, "destroyed_at": datetime.now(timezone.utc),
        }})
        _upd(key, status="destroyed")
        _evt(key, "droplet_destroyed")
        _evt(key, "done")

    except Exception as exc:
        logger.exception(f"Droplet {droplet_id} destroy failed")
        try:
            db.gpu_droplets.update_one({"_id": oid(droplet_id)},
                                       {"$set": {"status": "failed", "status_detail": str(exc)}})
        except Exception:
            pass
        _upd(key, status="failed", status_detail=str(exc))
        _evt(key, "droplet_failed", error=str(exc))

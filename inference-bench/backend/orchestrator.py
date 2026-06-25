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
import shlex
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

# Deployment (SSH/Docker) timings — pulls and model loads are slow.
SSH_CONNECT_TIMEOUT_S = 60
SSH_READY_TIMEOUT_S = 300       # wait for sshd to come up on a fresh droplet
DEPLOY_PULL_TIMEOUT_S = 1800    # docker pull of a multi-GB engine image
DEPLOY_HEALTH_TIMEOUT_S = 1800  # weights download + model load
DEPLOY_POLL_INTERVAL_S = 5
_DEPLOY_TERMINAL = {"serving", "failed", "droplet_destroyed"}


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
    # DO accepts an image slug (str) or image id (int). Application/AI-ML images
    # often have only a numeric id, which arrives here as a digit string.
    image_val: object = cfg.get("image") or "ubuntu-22-04-x64"
    if isinstance(image_val, str) and image_val.isdigit():
        image_val = int(image_val)
    r = _check(client.post(f"{DO_API}/v2/droplets", headers=_headers(token), json={
        "name":     cfg["name"],
        "region":   cfg["region"],
        "size":     cfg["size_slug"],
        "image":    image_val,
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


def _size_details(client: httpx.Client, token: str, size_slug: str) -> dict | None:
    """Fetch a size's catalog entry (price + GPU info), used to fill cost-to-date
    and the GPU metadata that deployments need for recipe/hardware matching."""
    try:
        r = client.get(f"{DO_API}/v2/sizes", headers=_headers(token), params={"per_page": 200})
        r.raise_for_status()
        for size in r.json().get("sizes", []):
            if size.get("slug") == size_slug:
                return size
    except Exception as exc:
        logger.warning(f"Could not fetch size details for {size_slug}: {exc}")
    return None


def _gpu_fields(size: dict | None, size_slug: str) -> dict:
    """Derive GPU metadata (count / model / vendor / vram) from a size entry, so
    deployments can match the right recipe and TP size without re-querying DO."""
    if not size:
        return {"gpu_count": None, "gpu_model": None,
                "gpu_platform": _gpu_platform(None, size_slug), "gpu_vram_gb": None}
    gpu = size.get("gpu_info") or {}
    vram = gpu.get("vram") if isinstance(gpu.get("vram"), dict) else {}
    vram_gb = vram.get("amount")
    if vram_gb and str(vram.get("unit", "")).lower().startswith("m"):
        vram_gb = round(vram_gb / 1024)
    return {
        "gpu_count": gpu.get("count"),
        "gpu_model": gpu.get("model"),
        "gpu_platform": _gpu_platform(gpu.get("model"), size_slug),
        "gpu_vram_gb": vram_gb,
    }


def _gpu_platform(model: str | None, slug: str) -> str | None:
    """Best-effort vendor for a GPU size (DO groups plans by NVIDIA / AMD)."""
    blob = f"{model or ''} {slug}".lower()
    if any(k in blob for k in ("mi300", "mi325", "mi350", "instinct", "amd")):
        return "AMD"
    if any(k in blob for k in ("h100", "h200", "b200", "b300", "l40", "rtx", "a100", "a40", "nvidia")):
        return "NVIDIA"
    return None


def _excluded_gpu_sku(slug: str, description: str) -> bool:
    """Plans DO lists but won't provision on-demand via the API (contracts,
    multi-node, internal test SKUs) — these 'accept but never build'."""
    blob = f"{slug} {description}".lower()
    return any(w in blob for w in ("test", "contract", "multinode", "multi-node"))


def fetch_droplet_options(token: str) -> dict:
    """Live-fetch the DO catalog for the *GPU* create form: GPU plans only
    (contracts / multi-node / test SKUs excluded), regions, and images — flagging
    the recommended GPU images (AI/ML Ready, Inference Optimized) by name so we
    never hardcode an image id. Mirrors DO's Create GPU Droplet screen.
    """
    headers = _headers(token)
    with httpx.Client(timeout=30) as client:
        sr = client.get(f"{DO_API}/v2/sizes", headers=headers, params={"per_page": 200})
        sr.raise_for_status()
        rr = client.get(f"{DO_API}/v2/regions", headers=headers, params={"per_page": 200})
        rr.raise_for_status()
        # The distribution query returns OS images plus the GPU AI/ML base images,
        # which DO marks with type == "base" (gpu-amd-base, gpu-h100x1-base,
        # gpu-h100x8-base). We surface only those as recommended; anything else
        # (plain OS, 1-click model images) is reachable via the custom-image field.
        ir = client.get(f"{DO_API}/v2/images", headers=headers,
                        params={"type": "distribution", "per_page": 200})
        ir.raise_for_status()
        raw_imgs = ir.json().get("images", [])

    regions = [
        {"slug": r["slug"], "name": r.get("name") or r["slug"], "available": bool(r.get("available", True))}
        for r in rr.json().get("regions", [])
    ]
    regions.sort(key=lambda r: r["name"])

    sizes = []
    for s in sr.json().get("sizes", []):
        slug = s.get("slug", "")
        desc = s.get("description") or ""
        if not slug.startswith("gpu-"):                  # GPU plans only
            continue
        if not s.get("available") or _excluded_gpu_sku(slug, desc):
            continue
        gpu = s.get("gpu_info") or {}
        vram = gpu.get("vram") if isinstance(gpu.get("vram"), dict) else {}
        vram_gb = vram.get("amount")
        if vram_gb and str(vram.get("unit", "")).lower().startswith("m"):
            vram_gb = round(vram_gb / 1024)
        count = gpu.get("count")
        price_hourly = s.get("price_hourly")
        sizes.append({
            "slug": slug,
            "description": desc or slug,
            "gpu_platform": _gpu_platform(gpu.get("model"), slug),
            "vcpus": s.get("vcpus"),
            "memory_gb": round((s.get("memory") or 0) / 1024) or None,   # DO memory is MB
            "disk_gb": s.get("disk"),
            "price_hourly": price_hourly,
            "price_monthly": s.get("price_monthly"),
            "price_per_gpu_hourly": round(price_hourly / count, 3) if price_hourly and count else None,
            "available": True,
            "regions": s.get("regions", []),
            "gpu_count": count,
            "gpu_model": gpu.get("model"),
            "gpu_vram_gb": vram_gb,
        })
    sizes.sort(key=lambda x: (x.get("price_hourly") or 0))

    # Two kinds of image we surface:
    #  - 'ai-ml': GPU base images (slug pattern gpu-*-base). NVIDIA vs AMD vs NVLink
    #    is captured in vendor/nvlink so the frontend can resolve the right one for
    #    the chosen plan — but it presents them as a single "AI/ML Ready" choice.
    #    (NOTE: every public OS image also has type=="base", so type is not usable.)
    #  - 'os': plain distribution images (Ubuntu, Fedora, …).
    images = []
    for im in raw_imgs:
        slug = im.get("slug")
        img_id = im.get("id")
        ref = slug or (str(img_id) if img_id else None)
        if not ref or im.get("public") is False:
            continue
        s = (slug or "").lower()
        name = im.get("name") or slug or str(img_id)
        if s.startswith("gpu-") and s.endswith("-base"):
            blob = f"{name} {s}"
            if "amd" in blob or "mi3" in blob:
                vendor = "AMD"
            elif any(k in blob for k in ("nvidia", "h100", "h200", "b200", "b300", "l40", "rtx")):
                vendor = "NVIDIA"
            else:
                vendor = None
            images.append({
                "value": ref, "label": name, "kind": "ai-ml", "recommended": True,
                "vendor": vendor, "nvlink": ("nvlink" in blob) or ("x8" in s),
                "regions": im.get("regions", []),
            })
        else:
            distro = im.get("distribution") or ""
            images.append({
                "value": ref, "label": f"{distro} {name}".strip(), "kind": "os",
                "recommended": False, "vendor": None, "nvlink": False,
                "regions": im.get("regions", []),
            })
    images.sort(key=lambda x: (0 if x["kind"] == "ai-ml" else 1, x["vendor"] or "", x["label"]))
    recommended_image = next((i["value"] for i in images if i["kind"] == "ai-ml"), None)

    return {"sizes": sizes, "regions": regions, "images": images,
            "recommended_image": recommended_image}


def cleanup_ssh_key(droplet_id: str) -> bool:
    """Best-effort delete of the DO SSH key registered for this droplet, so a
    failed/removed droplet doesn't leave an orphaned key in the account. Returns
    True if a key was deleted. Safe to call when there's no key or no token."""
    db = get_db()
    doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
    if not doc or not doc.get("do_ssh_key_id"):
        return False
    token = decrypt_api_key(doc.get("do_token_encrypted"))
    if not token:
        return False
    try:
        with httpx.Client(timeout=30) as client:
            _delete_ssh_key(client, token, doc["do_ssh_key_id"])
        db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {"do_ssh_key_id": None}})
        return True
    except Exception:
        logger.warning(f"Could not clean up SSH key for droplet {droplet_id}", exc_info=True)
        return False


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

            size = _size_details(client, token, doc["size_slug"])
            price = size.get("price_hourly") if size else None
            gpu = _gpu_fields(size, doc["size_slug"])

        db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
            "status": "active", "status_detail": None, "ip": ip,
            "hourly_price_usd": price, **gpu,
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
        # Best-effort: don't leave the registered SSH key orphaned in DO.
        if cleanup_ssh_key(droplet_id):
            _evt(key, "ssh_key_cleaned_up")


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

        now = datetime.now(timezone.utc)
        db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
            "status": "destroyed", "status_detail": None,
            "ip": None, "destroyed_at": now,
        }})
        # A deployment is bound to its droplet for life — reflect the teardown on
        # the deployment record (kept for history) instead of deleting it.
        db.deployments.update_many(
            {"droplet_id": droplet_id, "status": {"$nin": ["droplet_destroyed"]}},
            {"$set": {"status": "droplet_destroyed", "droplet_destroyed_at": now}},
        )
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


# ═══════════════════════════════════════════════════════════════════════════════
#  DEPLOYMENTS — serve a model on a droplet over SSH (Benchmarking Evaluation §2)
#  Second control channel (paramiko). Engine-specific launch spec comes from
#  engines.py; everything here is engine-neutral.
# ═══════════════════════════════════════════════════════════════════════════════

def _ssh_connect(droplet: dict):
    """Open an SSH session to the droplet using its stored (decrypted) private
    key. paramiko is imported lazily — it's only needed for deployments."""
    import io
    import paramiko  # type: ignore

    if not droplet.get("ip"):
        raise RuntimeError("Droplet has no public IP yet")
    priv = decrypt_api_key(droplet.get("ssh_private_key_encrypted"))
    if not priv:
        raise RuntimeError("Droplet has no usable SSH private key")
    pkey = paramiko.RSAKey.from_private_key(io.StringIO(priv))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(droplet["ip"], username="root", pkey=pkey,
                   timeout=SSH_CONNECT_TIMEOUT_S, banner_timeout=60, auth_timeout=60,
                   look_for_keys=False, allow_agent=False)
    return client


def _ssh_run(client, cmd: str, timeout: int) -> tuple[int, str, str]:
    """Run one command; return (exit_code, stdout, stderr)."""
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def _wait_for_ssh(droplet: dict):
    """A freshly-active droplet may not have sshd ready immediately — retry the
    connect for a short window before giving up."""
    deadline = time.monotonic() + SSH_READY_TIMEOUT_S
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return _ssh_connect(droplet)
        except Exception as exc:  # noqa: BLE001 — retry any connect error
            last = exc
            time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(f"Could not SSH into droplet within {SSH_READY_TIMEOUT_S}s: {last}")


def submit_deploy_model(deployment_id: str) -> None:
    progress_store[deployment_id] = {"status": "pulling", "events": []}
    executor.submit(_deploy_model_job, deployment_id)


def _deploy_model_job(deployment_id: str) -> None:
    from engines import get_engine

    db = get_db()
    key = deployment_id
    client = None
    try:
        dep = db.deployments.find_one({"_id": oid(deployment_id)})
        if not dep:
            logger.error(f"Deployment {deployment_id} not found")
            return
        droplet = db.gpu_droplets.find_one({"_id": oid(dep["droplet_id"])})
        if not droplet:
            raise RuntimeError("Droplet for this deployment no longer exists")
        if droplet.get("status") != "active":
            raise RuntimeError(f"Droplet is not active (status: {droplet.get('status')})")

        engine = get_engine(dep["engine"])
        container = f"crest-{deployment_id}"
        port = dep.get("port") or engine.default_port
        platform = droplet.get("gpu_platform")

        env = dict(dep.get("env") or {})
        hf_token = decrypt_api_key(dep.get("hf_token_encrypted"))
        if hf_token:
            env.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)
            env.setdefault("HF_TOKEN", hf_token)

        argv = engine.build_run_argv(
            container=container, model_ref=dep["model"], image=dep["docker_image"],
            args=dep.get("server_args") or [], env=env, port=port, platform=platform,
        )
        run_cmd = " ".join(shlex.quote(t) for t in argv)

        _upd(key, status="pulling")
        _evt(key, "deployment_pulling", image=dep["docker_image"])

        client = _wait_for_ssh(droplet)

        # Clear any stale container from a prior attempt with the same name.
        _ssh_run(client, f"docker rm -f {shlex.quote(container)} 2>/dev/null || true", 60)

        # 1. Pull the engine image (blocking; can be many minutes).
        rc, _out, err = _ssh_run(client, f"docker pull {shlex.quote(dep['docker_image'])}",
                                 DEPLOY_PULL_TIMEOUT_S)
        if rc != 0:
            raise RuntimeError(f"docker pull failed: {err.strip()[:500]}")
        _evt(key, "image_pulled", image=dep["docker_image"])

        # 2. Start the container detached.
        _upd(key, status="starting")
        _evt(key, "deployment_starting", port=port)
        rc, out, err = _ssh_run(client, run_cmd, 120)
        if rc != 0:
            raise RuntimeError(f"docker run failed: {(err or out).strip()[:500]}")
        cid = out.strip().splitlines()[-1][:12] if out.strip() else None
        db.deployments.update_one({"_id": oid(deployment_id)},
                                  {"$set": {"status": "starting", "container_id": cid}})
        _evt(key, "container_started", container_id=cid)

        # 3. Poll the OpenAI-compatible health endpoint until the model is loaded.
        health_url = f"http://localhost:{port}{engine.health_path}"
        deadline = time.monotonic() + DEPLOY_HEALTH_TIMEOUT_S
        healthy = False
        while time.monotonic() < deadline:
            # Surface recent logs so the UI shows weight-download / load progress.
            lrc, logs, _ = _ssh_run(client, f"docker logs --tail 50 {shlex.quote(container)} 2>&1", 30)
            if logs:
                db.deployments.update_one({"_id": oid(deployment_id)},
                                          {"$set": {"log_tail": logs[-8000:]}})
                _upd(key, log_tail=logs[-4000:])

            # Container died? fail fast with its logs.
            crc, state, _ = _ssh_run(client, f"docker inspect -f '{{{{.State.Running}}}}' {shlex.quote(container)} 2>/dev/null || echo missing", 30)
            if "false" in state or "missing" in state:
                raise RuntimeError(f"Container exited before serving. Recent logs:\n{logs[-1500:]}")

            hrc, code, _ = _ssh_run(
                client,
                f"curl -s -o /dev/null -w '%{{http_code}}' {shlex.quote(health_url)} || true", 30)
            if code.strip() == "200":
                healthy = True
                break
            _upd(key, do_status="loading")
            _evt(key, "waiting_for_health", elapsed_s=int(time.monotonic() - (deadline - DEPLOY_HEALTH_TIMEOUT_S)))
            time.sleep(DEPLOY_POLL_INTERVAL_S)

        if not healthy:
            raise TimeoutError(f"Model did not become healthy within {DEPLOY_HEALTH_TIMEOUT_S}s")

        db.deployments.update_one({"_id": oid(deployment_id)}, {"$set": {
            "status": "serving", "status_detail": None, "health": "ok",
        }})
        _upd(key, status="serving", health="ok")
        _evt(key, "health_ok")
        _evt(key, "deployment_serving", port=port)
        _evt(key, "done")

    except Exception as exc:
        logger.exception(f"Deployment {deployment_id} failed")
        # Best-effort: capture the container's last logs into the failure detail.
        try:
            if client is not None:
                _rc, logs, _ = _ssh_run(client, f"docker logs --tail 80 crest-{deployment_id} 2>&1", 30)
                if logs:
                    db.deployments.update_one({"_id": oid(deployment_id)},
                                              {"$set": {"log_tail": logs[-8000:]}})
        except Exception:
            pass
        try:
            db.deployments.update_one({"_id": oid(deployment_id)},
                                      {"$set": {"status": "failed", "status_detail": str(exc)}})
        except Exception:
            pass
        _upd(key, status="failed", status_detail=str(exc))
        _evt(key, "deployment_failed", error=str(exc))
        # Note: we deliberately do NOT destroy the droplet — the user tears it down
        # manually (1 droplet = 1 deployment).
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def tail_logs(deployment_id: str, lines: int = 200) -> str:
    """On-demand `docker logs` for the logs endpoint."""
    db = get_db()
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        raise RuntimeError("Deployment not found")
    droplet = db.gpu_droplets.find_one({"_id": oid(dep["droplet_id"])})
    if not droplet or droplet.get("status") != "active":
        return dep.get("log_tail") or ""   # droplet gone → last stored logs
    client = None
    try:
        client = _ssh_connect(droplet)
        _rc, logs, _ = _ssh_run(client, f"docker logs --tail {int(lines)} crest-{deployment_id} 2>&1", 30)
        if logs:
            db.deployments.update_one({"_id": oid(deployment_id)}, {"$set": {"log_tail": logs[-8000:]}})
        return logs or (dep.get("log_tail") or "")
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def health_check(deployment_id: str) -> str:
    """On-demand health probe for the health endpoint. Returns 'ok' | 'down' | 'unknown'."""
    from engines import get_engine

    db = get_db()
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        raise RuntimeError("Deployment not found")
    droplet = db.gpu_droplets.find_one({"_id": oid(dep["droplet_id"])})
    if not droplet or droplet.get("status") != "active":
        return "unknown"
    engine = get_engine(dep["engine"])
    port = dep.get("port") or engine.default_port
    url = f"http://localhost:{port}{engine.health_path}"
    client = None
    try:
        client = _ssh_connect(droplet)
        _rc, code, _ = _ssh_run(client, f"curl -s -o /dev/null -w '%{{http_code}}' {shlex.quote(url)} || true", 30)
        health = "ok" if code.strip() == "200" else "down"
        db.deployments.update_one({"_id": oid(deployment_id)}, {"$set": {"health": health}})
        return health
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

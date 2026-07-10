"""GPU droplet orchestration — the only genuinely new infrastructure layer.

Two control channels (see docs/BENCHMARKING_FEATURE.md §4):
  - DO REST API over httpx  → create / poll / destroy droplets, (de)register SSH keys.
  - SSH over paramiko       → deploy / benchmark (added in later steps).

Long-running ops run on worker.py's ThreadPoolExecutor and stream progress through
the shared progress_store, exactly like evaluations do. SSE in routers reads it.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
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

# Reconciliation: detect droplets destroyed out-of-band (e.g. the DO console).
STALE_AGENT_S = 90          # agent silent this long → worth a DO existence check
NEW_DROPLET_BOOT_S = 180    # don't suspect a brand-new droplet whose agent isn't up yet
# States where the DO droplet may still exist, so reconcile should verify against
# DO. `active` is the normal case; `failed`/`destroy_failed` are stuck states that
# would otherwise never be re-checked (a failed provision or a failed destroy can
# leave a live droplet behind). `provisioning`/`destroying` have a job in flight;
# `destroyed` is terminal — none of those are reconciled here.
RECONCILABLE_STATES = ("active", "failed", "destroy_failed")
# Agent silent this long while a deployment is serving / a benchmark is running →
# treat the work as dead (the droplet/agent went away without a clean teardown).
AGENT_DEAD_S = 300
# A deploy job the agent never picks up (droplet failed to boot / was destroyed)
# would otherwise leave the deployment stuck "pulling" forever.
DEPLOY_AGENT_PICKUP_TIMEOUT_S = 300

# Deployment timings — passed to the agent in the job spec; pulls + loads are slow.
DEPLOY_PULL_TIMEOUT_S = 1800    # docker pull of a multi-GB engine image
# Default ceiling for a model to become healthy. Big FP4/MoE models on first load
# do weight download + quantization + kernel autotune + torch.compile, which can
# run well past 30 min — so this is a generous default and is overridable
# per-deployment (DeploymentCreate.startup_timeout_min).
DEPLOY_HEALTH_TIMEOUT_S = 3600
DEPLOY_POLL_INTERVAL_S = 5

# Benchmark (aiperf) timings/config — aiperf is a client-side load generator that
# we pip-install at run time inside a stock Python image (no official image, no
# GPU needed), so it stays engine-agnostic. See docs §3.
AIPERF_BASE_IMAGE = "python:3.12"
AIPERF_RUN_TIMEOUT_S = 3600     # whole profile run (pip install + load test)


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


def _friendly_provision_error(exc: Exception, size_slug: str = "", region: str = "") -> str:
    """Turn DigitalOcean's terse provisioning errors into something a user can act
    on. GPU capacity fluctuates, so a 422 'size not available' is an availability
    limit — not a Crest bug — and should read that way."""
    low = str(exc).lower()
    if isinstance(exc, DOError) and exc.status_code == 422 and "not available in this region" in low:
        where = f"{size_slug} in {region}".strip() if (size_slug or region) else "this GPU in this region"
        return (f"DigitalOcean currently has no available capacity for {where}. GPU capacity "
                f"fluctuates — retry in a few minutes, or pick a different GPU or region. ")
    return str(exc)


def _register_ssh_key(client: httpx.Client, token: str, name: str, public_key: str) -> int:
    r = _check(client.post(f"{DO_API}/v2/account/keys", headers=_headers(token),
                           json={"name": name, "public_key": public_key}),
               "Register SSH key")
    return r.json()["ssh_key"]["id"]


def _delete_ssh_key(client: httpx.Client, token: str, key_id: int) -> None:
    r = client.delete(f"{DO_API}/v2/account/keys/{key_id}", headers=_headers(token))
    if r.status_code != 404:
        _check(r, "Delete SSH key")


def _create_droplet(client: httpx.Client, token: str, cfg: dict, ssh_key_id: int,
                    user_data: str | None = None) -> int:
    # DO accepts an image slug (str) or image id (int). Application/AI-ML images
    # often have only a numeric id, which arrives here as a digit string.
    image_val: object = cfg.get("image") or "ubuntu-22-04-x64"
    if isinstance(image_val, str) and image_val.isdigit():
        image_val = int(image_val)
    payload: dict = {
        "name":     cfg["name"],
        "region":   cfg["region"],
        "size":     cfg["size_slug"],
        "image":    image_val,
        "ssh_keys": [ssh_key_id],
        "tags":     ["crest", "crest-benchmark"],
    }
    if user_data:
        payload["user_data"] = user_data   # cloud-init: installs the Crest agent
    r = _check(client.post(f"{DO_API}/v2/droplets", headers=_headers(token), json=payload),
               "Create droplet")
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


# ── Agent provisioning (cloud-init) ────────────────────────────────────────────

def _public_base_url() -> str:
    """Where the on-droplet agent calls home. Must be the app's public URL since
    the droplet reaches the backend over HTTPS (App Platform blocks the reverse)."""
    return (os.getenv("CREST_PUBLIC_URL") or os.getenv("APP_URL") or "").rstrip("/")


def _agent_user_data(droplet_id: str, agent_token: str) -> str | None:
    """cloud-init that installs the Crest agent as a systemd service. The service
    re-fetches the agent source from the backend on every start, so it self-heals
    and self-updates. Returns None if we don't know the backend URL."""
    base = _public_base_url()
    if not base:
        logger.warning("CREST_PUBLIC_URL/APP_URL not set — the droplet agent can't "
                       "call home; deployments won't work until it is configured.")
        return None
    return f"""#cloud-config
write_files:
  - path: /opt/crest/agent.env
    permissions: '0600'
    content: |
      CREST_URL={base}
      CREST_AGENT_TOKEN={agent_token}
      CREST_DROPLET_ID={droplet_id}
  - path: /etc/systemd/system/crest-agent.service
    content: |
      [Unit]
      Description=Crest deployment agent
      After=network-online.target docker.service
      Wants=network-online.target
      [Service]
      EnvironmentFile=/opt/crest/agent.env
      ExecStartPre=/bin/sh -c 'curl -fsSL "$CREST_URL/api/agent/script" -o /opt/crest/agent.py'
      ExecStart=/usr/bin/python3 /opt/crest/agent.py
      Restart=always
      RestartSec=10
      [Install]
      WantedBy=multi-user.target
runcmd:
  - mkdir -p /opt/crest
  - command -v docker >/dev/null 2>&1 || (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io)
  - systemctl enable --now docker 2>/dev/null || true
  - systemctl daemon-reload
  - systemctl enable --now crest-agent
"""


def _gpu_platform(model: str | None, slug: str) -> str | None:
    """Best-effort vendor for a GPU size (DO groups plans by NVIDIA / AMD)."""
    blob = f"{model or ''} {slug}".lower()
    if any(k in blob for k in ("mi3", "instinct", "amd")):
        return "AMD"
    if any(k in blob for k in ("h100", "h200", "b200", "b300", "l40", "rtx", "a100", "a40", "nvidia")):
        return "NVIDIA"
    return None


# Canonical GPU inventory from the "GPU Droplet Sizes" sheet — the source of truth
# for region availability, which the DO API does NOT return reliably for this
# account. Contracted SKUs only (incl. multi-node "fabric"); H100-contracted is
# omitted because its Available Regions cell is blank in the sheet. Update this
# table when the sheet changes.
# Columns: slug, model, platform, gpu_count, vram_total_gb, vcpus, ram_gb, disk_gb, regions, fabric
_GPU_CATALOG: list[tuple] = [
    # AMD MI300X — ATL1
    ("gpu-mi300x1-192gb-contracted",          "AMD MI300X",   "AMD",    1,  192,  20,  240,  720,  ["atl1"], False),
    ("gpu-mi300x8-1536gb-contracted",         "AMD MI300X",   "AMD",    8, 1536, 160, 1920, 2046,  ["atl1"], False),
    ("gpu-mi300x8-1536gb-fabric-contracted",  "AMD MI300X",   "AMD",    8, 1536, 160, 1920, 2046,  ["atl1"], True),
    # AMD MI325X — ATL1, NYC2, TOR1
    ("gpu-mi325x1-256gb-contracted",          "AMD MI325X",   "AMD",    1,  256,  20,  160,  720,  ["atl1", "nyc2", "tor1"], False),
    ("gpu-mi325x8-2048gb-contracted",         "AMD MI325X",   "AMD",    8, 2048, 160, 1280, 2046,  ["atl1", "nyc2", "tor1"], False),
    ("gpu-mi325x8-2048gb-fabric-contracted",  "AMD MI325X",   "AMD",    8, 2048, 160, 1280, 2046,  ["atl1", "nyc2", "tor1"], True),
    # AMD MI350X — ATL1
    ("gpu-mi350x1-288gb-contracted",          "AMD MI350X",   "AMD",    1,  288,  24,  256,  720,  ["atl1"], False),
    ("gpu-mi350x8-2304gb-contracted",         "AMD MI350X",   "AMD",    8, 2304, 192, 2048, 2046,  ["atl1"], False),
    ("gpu-mi350x8-2304gb-fabric-contracted",  "AMD MI350X",   "AMD",    8, 2304, 192, 2048, 2046,  ["atl1"], True),
    # NVIDIA H200 — x1: NYC2+ATL1, x8: NYC2
    ("gpu-h200x1-141gb-contracted",           "NVIDIA H200",  "NVIDIA", 1,  141,  24,  240,  720,  ["nyc2", "atl1"], False),
    ("gpu-h200x8-1128gb-contracted",          "NVIDIA H200",  "NVIDIA", 8, 1128, 192, 1920, 2046,  ["nyc2"], False),
    ("gpu-h200x8-1128gb-fabric-contracted",   "NVIDIA H200",  "NVIDIA", 8, 1128, 192, 1920, 2046,  ["nyc2"], True),
    # NVIDIA B300 — RIC1
    ("gpu-b300x1-288gb-contracted",           "NVIDIA B300",  "NVIDIA", 1,  288,  28,  448,  720,  ["ric1"], False),
    ("gpu-b300x8-2304gb-contracted",          "NVIDIA B300",  "NVIDIA", 8, 2304, 224, 3584, 2046,  ["ric1"], False),
    ("gpu-b300x8-2304gb-fabric-contracted",   "NVIDIA B300",  "NVIDIA", 8, 2304, 224, 3584, 2046,  ["ric1"], True),
    # NVIDIA B300 LC (liquid-cooled) — MKC1
    ("gpu-b300x1-288gb-lc-contracted",        "NVIDIA B300 LC", "NVIDIA", 1,  288,  28,  448,  720,  ["mkc1"], False),
    ("gpu-b300x8-2304gb-lc-contracted",       "NVIDIA B300 LC", "NVIDIA", 8, 2304, 224, 3584, 2046,  ["mkc1"], False),
    ("gpu-b300x8-2304gb-lc-fabric-contracted","NVIDIA B300 LC", "NVIDIA", 8, 2304, 224, 3584, 2046,  ["mkc1"], True),
]


def _contracted_gpu_sizes() -> list[dict]:
    """Expand _GPU_CATALOG into the size shape the create form consumes. Prices are
    None (the sheet doesn't carry them); the UI shows '—'."""
    out = []
    for slug, model, platform, count, vram, vcpus, ram_gb, disk_gb, regions, fabric in _GPU_CATALOG:
        out.append({
            "slug": slug,
            "description": f"{count}× {model}" + (" · multi-node (fabric)" if fabric else ""),
            "gpu_platform": platform,
            "vcpus": vcpus,
            "memory_gb": ram_gb,
            "disk_gb": disk_gb,
            "price_hourly": None,
            "price_monthly": None,
            "price_per_gpu_hourly": None,
            "available": True,
            "regions": list(regions),
            "gpu_count": count,
            "gpu_model": model,
            "gpu_vram_gb": vram,
        })
    return out


def fetch_droplet_options(token: str) -> dict:
    """Catalog for the GPU create form: GPU plans from the canonical sheet
    (_GPU_CATALOG — the DO API doesn't return reliable GPU region availability for
    this account), plus regions and images fetched live. Only the regions our plans
    run in are surfaced, named from /v2/regions.
    """
    headers = _headers(token)
    with httpx.Client(timeout=30) as client:
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

    # GPU plans come from the sheet, not /v2/sizes (see _GPU_CATALOG).
    sizes = _contracted_gpu_sizes()

    # Surface only the regions our plans actually run in; names from /v2/regions.
    region_names = {r.get("slug"): r.get("name") for r in rr.json().get("regions", [])}
    gpu_region_slugs = sorted({reg for s in sizes for reg in s["regions"]})
    regions = [{"slug": rs, "name": region_names.get(rs) or rs.upper(), "available": True}
               for rs in gpu_region_slugs]
    regions.sort(key=lambda r: r["name"])

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


# DigitalOcean's AI/ML-Ready images (stable slugs — see DO Droplet images docs).
AIML_IMAGE_AMD = "gpu-amd-base"               # AMD AI/ML Ready (ROCm)
AIML_IMAGE_NVIDIA = "gpu-h100x1-base"         # NVIDIA AI/ML Ready (single GPU)
AIML_IMAGE_NVIDIA_NVLINK = "gpu-h100x8-base"  # NVIDIA AI/ML Ready with NVLink (multi-GPU)


def _gpu_count_from_slug(slug: str) -> int | None:
    """e.g. gpu-h100x8-640gb -> 8, gpu-mi300x1-192gb -> 1."""
    m = re.search(r"x(\d+)", slug or "")
    return int(m.group(1)) if m else None


def aiml_image_for_plan(size_slug: str, gpu_platform: str | None = None,
                        gpu_count: int | None = None) -> str:
    """Deterministic AI/ML-Ready image for a GPU plan. The driver image vendor
    MUST match the GPU or the hardware is dead:
        AMD GPU            -> AMD ROCm image
        NVIDIA single GPU  -> NVIDIA image
        NVIDIA multi GPU   -> NVIDIA NVLink image
    Pure function of the plan (no catalog round-trip), so it can't silently no-op
    the way a catalog/vendor-string lookup can.
    """
    slug = (size_slug or "").lower()
    plat = (gpu_platform or "").upper()
    # "mi3" covers all AMD Instinct MI3xx (mi300x/mi325x/mi355x/…) without a
    # per-chip list; anything not AMD is treated as NVIDIA (DO's only two vendors).
    is_amd = plat == "AMD" or any(k in slug for k in ("mi3", "instinct", "amd"))
    if is_amd:
        return AIML_IMAGE_AMD
    count = gpu_count or _gpu_count_from_slug(slug) or 1
    return AIML_IMAGE_NVIDIA_NVLINK if count > 1 else AIML_IMAGE_NVIDIA


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

            # 2. Per-droplet agent token + cloud-init that installs the Crest agent.
            agent_token = secrets.token_urlsafe(32)
            db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
                "agent_token_sha256": hashlib.sha256(agent_token.encode()).hexdigest(),
                "agent_last_seen": None,
            }})
            user_data = _agent_user_data(droplet_id, agent_token)

            # 3. Create droplet (cloud-init installs the agent on first boot).
            do_droplet_id = _create_droplet(client, token, doc, ssh_key_id, user_data=user_data)
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

            # Prefer the GPU details the user selected from the catalog (stored at
            # create); only fall back to the per-droplet token's size data for any
            # gaps (e.g. custom sizes), since that token can return sparse info.
            size = _size_details(client, token, doc["size_slug"])
            derived = _gpu_fields(size, doc["size_slug"])
            gpu = {k: (doc.get(k) if doc.get(k) is not None else derived.get(k))
                   for k in ("gpu_count", "gpu_model", "gpu_platform", "gpu_vram_gb")}
            price = doc.get("hourly_price_usd")
            if price is None:
                price = size.get("price_hourly") if size else None

        db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
            "status": "active", "status_detail": None, "ip": ip,
            "hourly_price_usd": price, **gpu,
        }})
        _upd(key, status="active", ip=ip, hourly_price_usd=price)
        _evt(key, "droplet_ready", ip=ip, hourly_price_usd=price)
        _evt(key, "done")

    except Exception as exc:
        logger.exception(f"Droplet {droplet_id} provisioning failed")
        d = db.gpu_droplets.find_one({"_id": oid(droplet_id)}) or {}
        detail = _friendly_provision_error(exc, d.get("size_slug", ""), d.get("region", ""))
        try:
            db.gpu_droplets.update_one({"_id": oid(droplet_id)},
                                       {"$set": {"status": "failed", "status_detail": detail}})
        except Exception:
            pass
        _upd(key, status="failed", status_detail=detail)
        _evt(key, "droplet_failed", error=detail)
        # Best-effort: don't leave the registered SSH key orphaned in DO.
        if cleanup_ssh_key(droplet_id):
            _evt(key, "ssh_key_cleaned_up")


def _fail_pending_aiperf_runs(db, droplet_id: str, now) -> None:
    """A benchmark whose droplet was destroyed will never report back, so it would
    hang as queued/running forever. Flip those runs to failed with a clear reason so
    they surface as failures (and can be cleared with 'Archive failed')."""
    db.aiperf_runs.update_many(
        {"droplet_id": droplet_id, "status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "failed", "status_detail": "Droplet destroyed", "completed_at": now}},
    )


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
        _fail_pending_aiperf_runs(db, droplet_id, now)
        _upd(key, status="destroyed")
        _evt(key, "droplet_destroyed")
        _evt(key, "done")

    except Exception as exc:
        logger.exception(f"Droplet {droplet_id} destroy failed")
        # A failed destroy is NOT a generic failure: the real DO droplet is very
        # likely still running (and billing). Mark it `destroy_failed` — a distinct,
        # retryable state that reconciliation keeps watching (so a later console
        # delete is still detected) — rather than a terminal `failed` that hides a
        # live droplet from reconcile forever.
        detail = (f"Couldn't destroy the droplet ({exc}). It may still be running and "
                  f"billing on DigitalOcean — retry Destroy, or remove it in the DO console "
                  f"(Crest will then detect it's gone).")
        try:
            db.gpu_droplets.update_one({"_id": oid(droplet_id)},
                                       {"$set": {"status": "destroy_failed", "status_detail": detail}})
        except Exception:
            pass
        _upd(key, status="destroy_failed", status_detail=detail)
        _evt(key, "droplet_destroy_failed", error=str(exc))


# ── Reconciliation (detect out-of-band destroys) ──────────────────────────────

def _agent_stale(doc: dict) -> bool:
    """Whether the droplet's agent has gone quiet long enough to be worth a DO
    existence check. Uses naive utcnow to match Mongo's naive datetimes. A live
    agent (recent heartbeat) means the droplet is definitely up, so we skip it —
    bounding DO calls to genuinely suspicious droplets."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC, matches Mongo
    last = doc.get("agent_last_seen")
    if last is None:
        created = doc.get("created_at")
        return created is not None and (now - created).total_seconds() > NEW_DROPLET_BOOT_S
    return (now - last).total_seconds() > STALE_AGENT_S


def reconcile_droplet(droplet_id: str) -> dict | None:
    """If a droplet has been destroyed out-of-band (DO console, API), reflect that
    in Crest: mark it destroyed, cascade its deployments, clean up the SSH key. A DO
    404 is the authoritative signal. Returns the (possibly updated) droplet doc.
    Best-effort — any non-404 error leaves the record untouched.

    Watches every state where the DO droplet might still exist (RECONCILABLE_STATES),
    not just `active`, so a droplet stuck in `failed`/`destroy_failed` (e.g. a destroy
    that hit an auth error) is still checked and can recover once it's really gone."""
    db = get_db()
    doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
    if not doc or doc.get("status") not in RECONCILABLE_STATES or not doc.get("do_droplet_id"):
        return doc
    token = decrypt_api_key(doc.get("do_token_encrypted"))
    if not token:
        return doc
    try:
        with httpx.Client(timeout=20) as client:
            try:
                _get_droplet(client, token, doc["do_droplet_id"])
                return doc  # still alive
            except DOError as e:
                if e.status_code != 404:
                    return doc
                now = datetime.now(timezone.utc)
                db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {
                    "status": "destroyed",
                    "status_detail": "Destroyed in the DigitalOcean console",
                    "ip": None, "destroyed_at": now,
                }})
                db.deployments.update_many(
                    {"droplet_id": droplet_id, "status": {"$nin": ["droplet_destroyed"]}},
                    {"$set": {"status": "droplet_destroyed", "droplet_destroyed_at": now}})
                _fail_pending_aiperf_runs(db, droplet_id, now)
                if doc.get("do_ssh_key_id"):
                    try:
                        _delete_ssh_key(client, token, doc["do_ssh_key_id"])
                    except Exception:
                        logger.warning(f"Could not clean SSH key for externally-destroyed {droplet_id}")
                progress_store.setdefault(droplet_id, {"events": []})["status"] = "destroyed"
    except Exception:
        logger.warning(f"Reconcile failed for droplet {droplet_id}", exc_info=True)
    return db.gpu_droplets.find_one({"_id": oid(droplet_id)})


# Deployment/benchmark states that represent work still "in flight" — the ones
# that get orphaned when a droplet goes away without a clean teardown.
_DEP_ACTIVE = ("pulling", "starting", "serving")
_RUN_PENDING = ("queued", "running")


def _agent_dead(doc: dict) -> bool:
    """Whether the droplet's agent has been silent long enough (AGENT_DEAD_S) that
    in-flight work on it should be considered dead. Stricter than _agent_stale (which
    only decides whether a DO existence check is worthwhile). Naive UTC to match
    Mongo's naive datetimes."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last = doc.get("agent_last_seen")
    if last is None:
        created = doc.get("created_at")
        return created is not None and (now - created).total_seconds() > AGENT_DEAD_S
    return (now - last).total_seconds() > AGENT_DEAD_S


def sweep_orphans(db) -> dict:
    """Backstop cascade: heal deployments/benchmarks whose droplet went away but that
    still claim to be in flight. reconcile_droplet already cascades on the destroy
    transition; this catches anything it missed (a droplet record deleted outright,
    a cascade that partially failed, or an agent that died mid-run while the droplet
    still nominally exists). Idempotent — safe to run on a timer."""
    now = datetime.now(timezone.utc)
    healed = {"deployments": 0, "runs": 0}

    # Cache droplet status by id so we don't re-query per record.
    def _droplet(did: str | None) -> dict | None:
        if not did:
            return None
        try:
            return db.gpu_droplets.find_one({"_id": oid(did)}, {"status": 1, "agent_last_seen": 1, "created_at": 1})
        except Exception:
            return None

    for dep in db.deployments.find({"status": {"$in": list(_DEP_ACTIVE)}}):
        dr = _droplet(dep.get("droplet_id"))
        if dr is None or dr.get("status") == "destroyed":
            db.deployments.update_one({"_id": dep["_id"]}, {"$set": {
                "status": "droplet_destroyed", "droplet_destroyed_at": now}})
            healed["deployments"] += 1
        elif dep.get("status") == "serving" and _agent_dead(dr) and dep.get("health") != "down":
            # Droplet still nominally exists but its agent is long silent — the
            # server is very likely gone. Flag it down (soft signal; don't tear
            # the record down, the agent may recover).
            db.deployments.update_one({"_id": dep["_id"]}, {"$set": {"health": "down"}})

    for run in db.aiperf_runs.find({"status": {"$in": list(_RUN_PENDING)}}):
        dr = _droplet(run.get("droplet_id"))
        if dr is None or dr.get("status") == "destroyed":
            db.aiperf_runs.update_one({"_id": run["_id"]}, {"$set": {
                "status": "failed", "status_detail": "Droplet destroyed",
                "completed_at": now}})
            healed["runs"] += 1
        elif run.get("status") == "running" and _agent_dead(dr):
            db.aiperf_runs.update_one({"_id": run["_id"]}, {"$set": {
                "status": "failed",
                "status_detail": "The droplet's agent stopped responding mid-run.",
                "completed_at": now}})
            healed["runs"] += 1

    # Any agent_jobs left queued/running for a droplet that's gone would keep the
    # per-droplet queue "busy" — close them out too.
    for job in db.agent_jobs.find({"status": {"$in": ["queued", "running"]}}):
        dr = _droplet(job.get("droplet_id"))
        if dr is None or dr.get("status") == "destroyed":
            db.agent_jobs.update_one({"_id": job["_id"]},
                                     {"$set": {"status": "failed", "completed_at": now}})
    return healed


def reconcile_all() -> dict:
    """Periodic self-heal (called from the worker's background loop): verify every
    possibly-alive droplet against DO, then sweep orphaned deployments/benchmarks.
    Bounds DO calls the same way the list endpoint does — an `active` droplet with a
    fresh agent heartbeat is provably up, so it's skipped."""
    db = get_db()
    checked = 0
    for d in db.gpu_droplets.find(
        {"status": {"$in": list(RECONCILABLE_STATES)}, "do_droplet_id": {"$ne": None}},
        {"_id": 1, "status": 1, "agent_last_seen": 1, "created_at": 1},
    ):
        if d.get("status") == "active" and not _agent_stale(d):
            continue
        try:
            reconcile_droplet(str(d["_id"]))
            checked += 1
        except Exception:
            logger.warning(f"reconcile_all: droplet {d['_id']} failed", exc_info=True)
    healed = sweep_orphans(db)
    return {"droplets_checked": checked, **healed}


# ═══════════════════════════════════════════════════════════════════════════════
#  DEPLOYMENTS — serve a model on a droplet via the on-droplet agent (§2)
#  The backend can't reach droplets (App Platform blocks outbound), so we enqueue
#  a job; the droplet's agent (crest_agent.py) polls over HTTPS, runs Docker, and
#  reports back through routers/agent.py. Engine-specific launch spec is built
#  here from engines.py; the agent is a dumb executor.
# ═══════════════════════════════════════════════════════════════════════════════

def _fail_deployment(db, deployment_id: str, msg: str) -> None:
    db.deployments.update_one({"_id": oid(deployment_id)},
                              {"$set": {"status": "failed", "status_detail": msg}})
    progress_store[deployment_id] = {"status": "failed", "status_detail": msg, "events": []}


def submit_deploy_model(deployment_id: str) -> None:
    """Build the launch spec and enqueue a deploy job for the droplet's agent.
    No backend→droplet connection — the agent picks it up on its next poll."""
    from engines import get_engine

    db = get_db()
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        logger.error(f"Deployment {deployment_id} not found")
        return
    droplet = db.gpu_droplets.find_one({"_id": oid(dep["droplet_id"])})
    if not droplet:
        _fail_deployment(db, deployment_id, "Droplet for this deployment no longer exists")
        return

    try:
        engine = get_engine(dep["engine"])
        container = f"crest-{deployment_id}"
        port = dep.get("port") or engine.default_port
        platform = droplet.get("gpu_platform")

        health_timeout = dep.get("health_timeout_s") or DEPLOY_HEALTH_TIMEOUT_S

        env = dict(dep.get("env") or {})
        hf_token = decrypt_api_key(dep.get("hf_token_encrypted"))
        if hf_token:
            env.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)
            env.setdefault("HF_TOKEN", hf_token)
        # vLLM's own engine-readiness timeout defaults to just 600s; a big FP4/MoE
        # load blows past that and vLLM would abort before our health deadline.
        # Align it with our timeout so the two never disagree. (env var, not a CLI
        # flag; setdefault so a recipe/user value still wins.)
        if engine.name == "vllm":
            env.setdefault("VLLM_ENGINE_READY_TIMEOUT_S", str(int(health_timeout)))

        argv = engine.build_run_argv(
            container=container, model_ref=dep["model"], image=dep["docker_image"],
            args=dep.get("server_args") or [], env=env, port=port, platform=platform,
        )
        spec = {
            "deployment_id": deployment_id,
            "container": container,
            "image": dep["docker_image"],
            "run_cmd": " ".join(shlex.quote(t) for t in argv),
            "health_url": f"http://localhost:{port}{engine.health_path}",
            "pull_timeout": DEPLOY_PULL_TIMEOUT_S,
            "health_timeout": health_timeout,
            "poll_interval": DEPLOY_POLL_INTERVAL_S,
        }
    except Exception as exc:
        logger.exception(f"Could not build deploy job for {deployment_id}")
        _fail_deployment(db, deployment_id, f"Could not build deploy job: {exc}")
        return

    now = datetime.now(timezone.utc)
    db.agent_jobs.insert_one({
        "droplet_id": dep["droplet_id"],
        "deployment_id": deployment_id,
        "type": "deploy",
        "spec": spec,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    })
    db.deployments.update_one({"_id": oid(deployment_id)}, {"$set": {
        "status": "pulling", "status_detail": None,
        "events": [{"event": "queued", "ts": now.isoformat()}],
    }})
    progress_store[deployment_id] = {"status": "pulling", "events": []}
    if not droplet.get("agent_last_seen"):
        logger.info(f"Deployment {deployment_id}: droplet agent has not checked in yet — "
                    f"the job will run once the agent comes online.")
    # Watchdog: if the agent never picks the job up (droplet failed to boot or was
    # destroyed out-of-band), fail the deployment instead of leaving it "pulling".
    executor.submit(_deploy_watchdog, deployment_id)


def _deploy_watchdog(deployment_id: str) -> None:
    try:
        time.sleep(DEPLOY_AGENT_PICKUP_TIMEOUT_S)
        db = get_db()
        job = db.agent_jobs.find_one({"deployment_id": deployment_id, "type": "deploy"},
                                     sort=[("created_at", -1)])
        if not job or job.get("status") != "queued":
            return  # picked up (or gone) — the agent is alive and handling it
        dep = db.deployments.find_one({"_id": oid(deployment_id)})
        if not dep or dep.get("status") in ("serving", "failed", "droplet_destroyed"):
            return
        _fail_deployment(db, deployment_id,
                         f"The droplet's agent never came online within "
                         f"{DEPLOY_AGENT_PICKUP_TIMEOUT_S // 60} minutes — the droplet may have "
                         f"failed to boot or was destroyed. Destroy it and try again.")
        db.agent_jobs.update_one({"_id": job["_id"]},
                                 {"$set": {"status": "failed", "completed_at": datetime.now(timezone.utc)}})
    except Exception:
        logger.exception(f"Deploy watchdog error for {deployment_id}")


def tail_logs(deployment_id: str, lines: int = 200) -> str:
    """Latest logs the agent reported (it refreshes them via heartbeat while the
    deployment is serving). The backend never connects to the droplet."""
    db = get_db()
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        raise RuntimeError("Deployment not found")
    return dep.get("log_tail") or ""


def health_check(deployment_id: str) -> str:
    """Latest health the agent reported. Returns 'ok' | 'down' | 'unknown'."""
    db = get_db()
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        raise RuntimeError("Deployment not found")
    return dep.get("health") or "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
#  BENCHMARKS — run aiperf against a serving deployment via the on-droplet agent.
#  aiperf only speaks OpenAI HTTP, so this layer is engine-agnostic: the same
#  profile runs identically against vLLM today and any future engine. We enqueue a
#  "benchmark" agent job; the agent runs aiperf in a container against
#  localhost:<port> and reports computed metrics back through routers/agent.py.
# ═══════════════════════════════════════════════════════════════════════════════

def _fail_aiperf_run(db, run_id: str, msg: str) -> None:
    db.aiperf_runs.update_one({"_id": oid(run_id)},
                              {"$set": {"status": "failed", "status_detail": msg,
                                        "completed_at": datetime.now(timezone.utc)}})
    progress_store[run_id] = {"status": "failed", "status_detail": msg, "events": []}


def submit_run_aiperf(run_id: str) -> None:
    """Build the aiperf launch spec and enqueue a benchmark job for the droplet's
    agent. No backend→droplet connection — the agent picks it up on its next poll,
    after any deploy/benchmark jobs already queued (serial per droplet, which is
    correct: concurrent benchmarks would pollute each other's measurements)."""
    from engines import _args_to_tokens

    db = get_db()
    run = db.aiperf_runs.find_one({"_id": oid(run_id)})
    if not run:
        logger.error(f"Aiperf run {run_id} not found")
        return
    dep = db.deployments.find_one({"_id": oid(run["deployment_id"])})
    if not dep:
        _fail_aiperf_run(db, run_id, "Deployment for this benchmark no longer exists")
        return

    try:
        snap = run.get("deployment_snapshot") or {}
        served_model = snap.get("model") or dep["model"]
        port = snap.get("port") or dep.get("port") or 8000

        profile = run.get("profile") or {}
        user_tokens = _args_to_tokens(profile.get("args") or [])
        flags = {(a.get("flag") or "") for a in (profile.get("args") or [])}

        # model + url are authoritative (must match the served deployment) so the
        # backend always injects them, overriding any user attempt. tokenizer and
        # endpoint-type get sensible defaults only if the user didn't set them.
        aiperf_args = ["--model", served_model, "--url", f"http://localhost:{port}"]
        if "--tokenizer" not in flags:
            aiperf_args += ["--tokenizer", served_model]
        if "--endpoint-type" not in flags:
            aiperf_args += ["--endpoint-type", "chat"]
        aiperf_args += user_tokens

        # HF token for the tokenizer download: the run's alternate token if given,
        # else the deployment's token (reused). aiperf pulls the HF tokenizer to
        # count tokens, which is gated for gated models just like the weights.
        env: dict[str, str] = {}
        token = decrypt_api_key(run.get("hf_token_encrypted")) or decrypt_api_key(dep.get("hf_token_encrypted"))
        if token:
            env["HF_TOKEN"] = token
            env["HUGGING_FACE_HUB_TOKEN"] = token

        spec = {
            "aiperf_run_id": run_id,
            "image": AIPERF_BASE_IMAGE,
            "aiperf_args": aiperf_args,
            "env": env,
            "extra_percentiles": profile.get("extra_percentiles") or [],
            "metrics_port": port,   # where the agent scrapes vLLM /metrics for live trends
            "run_timeout": AIPERF_RUN_TIMEOUT_S,
        }
    except Exception as exc:
        logger.exception(f"Could not build benchmark job for {run_id}")
        _fail_aiperf_run(db, run_id, f"Could not build benchmark job: {exc}")
        return

    now = datetime.now(timezone.utc)
    db.agent_jobs.insert_one({
        "droplet_id": run["droplet_id"],
        "aiperf_run_id": run_id,
        "type": "benchmark",
        "spec": spec,
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    })
    db.aiperf_runs.update_one({"_id": oid(run_id)}, {"$set": {
        "status": "queued", "status_detail": None,
        "events": [{"event": "queued", "ts": now.isoformat()}],
    }})
    progress_store[run_id] = {"status": "queued", "events": []}

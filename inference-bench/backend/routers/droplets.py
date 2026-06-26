"""GPU droplet provisioning routes (Benchmarking Evaluation — Step 1).

CRUD + destroy action + SSE provisioning progress, reusing worker.py's executor
and progress_store via orchestrator.py.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from sse_starlette.sse import EventSourceResponse

from database import get_db, _id as doc_id, oid
from encryption import encrypt_api_key
from schemas import DropletCreate, DropletOut
from worker import progress_store
import orchestrator

router = APIRouter(prefix="/api/droplets", tags=["droplets"])

_TERMINAL = {"active", "failed", "destroyed"}


def _droplet_out(doc: dict) -> DropletOut:
    d = doc_id(doc)
    d.pop("do_token_encrypted", None)
    d.pop("ssh_private_key_encrypted", None)
    return DropletOut(**d)


@router.get("/options")
def droplet_options():
    """Live DO catalog (all regions + sizes + images) for the create form.
    Uses ONLY the server's DO_API_TOKEN — never the per-droplet user token."""
    token = orchestrator.options_token()
    if not token:
        raise HTTPException(400, "Server has no DO_API_TOKEN configured for fetching droplet options")
    try:
        return orchestrator.fetch_droplet_options(token)
    except httpx.HTTPStatusError as e:
        detail = "DO_API_TOKEN is invalid" if e.response.status_code == 401 else e.response.text[:200]
        raise HTTPException(e.response.status_code, f"DigitalOcean API error: {detail}")
    except Exception as e:
        raise HTTPException(502, f"Could not reach DigitalOcean: {e}")


@router.get("", response_model=list[DropletOut])
def list_droplets(db: Database = Depends(get_db)):
    docs = list(db.gpu_droplets.find({}).sort("created_at", -1))
    return [_droplet_out(d) for d in docs]


@router.post("", response_model=DropletOut, status_code=201)
def create_droplet(body: DropletCreate, db: Database = Depends(get_db)):
    if not body.do_token:
        raise HTTPException(400, "DigitalOcean API token is required to create a droplet")
    # "AI/ML Ready" means "the driver image for this GPU" — resolve it
    # deterministically from the plan so an AMD GPU can't land on an NVIDIA image.
    # OS / custom images are the user's explicit choice and used as-is.
    if body.image_source == "aiml":
        body.image = orchestrator.aiml_image_for_plan(
            body.size_slug, body.gpu_platform, body.gpu_count)
    now = datetime.now(timezone.utc)
    doc = {
        "name": body.name,
        "region": body.region,
        "size_slug": body.size_slug,
        "image": body.image,
        "do_token_encrypted": encrypt_api_key(body.do_token),   # per-droplet user token
        "do_droplet_id": None,
        "ip": None,
        "ssh_public_key": None,
        "ssh_private_key_encrypted": None,
        "do_ssh_key_id": None,
        "status": "provisioning",
        "status_detail": None,
        # Authoritative GPU details from the catalog selection (deployments rely on
        # these); provisioning fills any gaps from the size catalog as a fallback.
        "hourly_price_usd": body.hourly_price_usd,
        "gpu_count": body.gpu_count,
        "gpu_model": body.gpu_model,
        "gpu_platform": body.gpu_platform,
        "gpu_vram_gb": body.gpu_vram_gb,
        "created_at": now,
        "destroyed_at": None,
    }
    droplet_id = str(db.gpu_droplets.insert_one(doc).inserted_id)
    orchestrator.submit_create_droplet(droplet_id)
    return _droplet_out(db.gpu_droplets.find_one({"_id": oid(droplet_id)}))


@router.get("/{droplet_id}", response_model=DropletOut)
def get_droplet(droplet_id: str, db: Database = Depends(get_db)):
    doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
    if not doc:
        raise HTTPException(404, "Droplet not found")
    return _droplet_out(doc)


@router.post("/{droplet_id}/destroy", response_model=DropletOut)
def destroy_droplet(droplet_id: str, db: Database = Depends(get_db)):
    doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
    if not doc:
        raise HTTPException(404, "Droplet not found")
    if doc.get("status") in ("destroying", "destroyed"):
        raise HTTPException(409, f"Droplet already {doc['status']}")
    db.gpu_droplets.update_one({"_id": oid(droplet_id)}, {"$set": {"status": "destroying"}})
    orchestrator.submit_destroy_droplet(droplet_id)
    return _droplet_out(db.gpu_droplets.find_one({"_id": oid(droplet_id)}))


@router.delete("/{droplet_id}", status_code=204)
def delete_droplet_record(droplet_id: str, db: Database = Depends(get_db)):
    doc = db.gpu_droplets.find_one({"_id": oid(droplet_id)})
    if not doc:
        raise HTTPException(404, "Droplet not found")
    if doc.get("status") not in ("destroyed", "failed"):
        raise HTTPException(409, "Destroy the droplet before deleting its record")
    orchestrator.cleanup_ssh_key(droplet_id)   # don't leave an orphaned DO SSH key
    db.gpu_droplets.delete_one({"_id": oid(droplet_id)})


@router.get("/{droplet_id}/stream")
async def stream_droplet(droplet_id: str, api_key: Optional[str] = None):
    async def event_generator():
        while True:
            data = progress_store.get(droplet_id, {"status": "provisioning"})
            yield {"data": json.dumps(data)}
            if data.get("status") in _TERMINAL:
                break
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())

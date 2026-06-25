"""Model deployment routes (Benchmarking Evaluation — Step 2).

A deployment serves one model on one droplet over SSH/Docker. It is bound to its
droplet for life: there is no stop/redeploy — to change the model you destroy the
droplet and make a new one (1 droplet = 1 deployment = many benchmarks). The
record is kept for history; destroying the droplet flips it to `droplet_destroyed`
(handled in orchestrator._destroy_droplet_job).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from sse_starlette.sse import EventSourceResponse

from database import get_db, _id as doc_id, oid
from encryption import encrypt_api_key
from schemas import DeploymentCreate, DeploymentOut
import engines
import orchestrator

router = APIRouter(prefix="/api/deployments", tags=["deployments"])

_TERMINAL = {"serving", "failed", "droplet_destroyed"}
# A droplet is considered "taken" while a deployment is in any of these states.
_ACTIVE = {"pulling", "starting", "serving"}


def _deployment_out(doc: dict, db: Database) -> DeploymentOut:
    d = doc_id(doc)
    d.pop("hf_token_encrypted", None)
    droplet = db.gpu_droplets.find_one({"_id": oid(d["droplet_id"])}) if d.get("droplet_id") else None
    d["droplet_name"] = droplet.get("name") if droplet else (d.get("droplet_snapshot") or {}).get("name")
    return DeploymentOut(**d)


@router.get("", response_model=list[DeploymentOut])
def list_deployments(droplet_id: Optional[str] = None, db: Database = Depends(get_db)):
    flt = {"droplet_id": droplet_id} if droplet_id else {}
    docs = list(db.deployments.find(flt).sort("created_at", -1))
    return [_deployment_out(d, db) for d in docs]


@router.post("", response_model=DeploymentOut, status_code=201)
def create_deployment(body: DeploymentCreate, db: Database = Depends(get_db)):
    try:
        engine = engines.get_engine(body.engine)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not engine.available:
        raise HTTPException(400, f"{engine.display_name} deployments are not available yet")

    droplet = db.gpu_droplets.find_one({"_id": oid(body.droplet_id)})
    if not droplet:
        raise HTTPException(404, "Droplet not found")
    if droplet.get("status") != "active":
        raise HTTPException(409, f"Droplet must be active to deploy (status: {droplet.get('status')})")

    # One active deployment per droplet (1 droplet = 1 deployment).
    existing = db.deployments.find_one({"droplet_id": body.droplet_id, "status": {"$in": list(_ACTIVE)}})
    if existing:
        raise HTTPException(409, "This droplet already has a deployment. Destroy the droplet to deploy a different model.")

    now = datetime.now(timezone.utc)
    doc = {
        "droplet_id": body.droplet_id,
        "droplet_snapshot": {
            "name": droplet.get("name"),
            "size_slug": droplet.get("size_slug"),
            "region": droplet.get("region"),
            "gpu_model": droplet.get("gpu_model"),
            "gpu_count": droplet.get("gpu_count"),
            "gpu_platform": droplet.get("gpu_platform"),
        },
        "engine": engine.name,
        "model": body.model,
        "docker_image": body.docker_image,
        "server_args": [a.model_dump() for a in body.server_args],
        "env": body.env,
        "port": body.port or engine.default_port,
        "recipe_source_url": body.recipe_source_url,
        "hardware_key": body.hardware_key,
        "hf_token_encrypted": encrypt_api_key(body.hf_token) if body.hf_token else None,
        "container_id": None,
        "status": "pulling",
        "status_detail": None,
        "health": None,
        "log_tail": None,
        "events": [],
        "created_at": now,
        "droplet_destroyed_at": None,
    }
    deployment_id = str(db.deployments.insert_one(doc).inserted_id)
    orchestrator.submit_deploy_model(deployment_id)
    return _deployment_out(db.deployments.find_one({"_id": oid(deployment_id)}), db)


@router.get("/{deployment_id}", response_model=DeploymentOut)
def get_deployment(deployment_id: str, db: Database = Depends(get_db)):
    doc = db.deployments.find_one({"_id": oid(deployment_id)})
    if not doc:
        raise HTTPException(404, "Deployment not found")
    return _deployment_out(doc, db)


@router.get("/{deployment_id}/logs")
def deployment_logs(deployment_id: str, lines: int = 200, db: Database = Depends(get_db)):
    if not db.deployments.find_one({"_id": oid(deployment_id)}):
        raise HTTPException(404, "Deployment not found")
    try:
        return {"log_tail": orchestrator.tail_logs(deployment_id, lines)}
    except Exception as e:
        raise HTTPException(502, f"Could not fetch logs: {e}")


@router.get("/{deployment_id}/health")
def deployment_health(deployment_id: str, db: Database = Depends(get_db)):
    if not db.deployments.find_one({"_id": oid(deployment_id)}):
        raise HTTPException(404, "Deployment not found")
    try:
        return {"health": orchestrator.health_check(deployment_id)}
    except Exception as e:
        raise HTTPException(502, f"Health check failed: {e}")


@router.get("/{deployment_id}/stream")
async def stream_deployment(deployment_id: str, api_key: Optional[str] = None):
    # Reads the deployment doc (updated by the agent via routers/agent.py), so it
    # works regardless of which app instance the agent reported to.
    async def event_generator():
        db = get_db()
        while True:
            doc = db.deployments.find_one({"_id": oid(deployment_id)})
            if not doc:
                yield {"data": json.dumps({"status": "failed", "status_detail": "Deployment not found"})}
                break
            yield {"data": json.dumps({
                "status": doc.get("status"),
                "status_detail": doc.get("status_detail"),
                "health": doc.get("health"),
                "log_tail": doc.get("log_tail"),
                "events": doc.get("events", []),
            })}
            if doc.get("status") in _TERMINAL:
                break
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())

"""On-droplet agent API (Benchmarking Evaluation — control channel).

The droplet's agent (crest_agent.py) calls these over HTTPS — App Platform blocks
the reverse (backend→droplet) direction. Auth is a per-droplet bearer token
(sha256 stored on the droplet doc), NOT the app's X-API-Key, so these routes are
exempt from the X-API-Key middleware in main.py.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pymongo import ReturnDocument
from pymongo.database import Database

from database import get_db, oid
from worker import progress_store

router = APIRouter(prefix="/api/agent", tags=["agent"])

_DEPLOY_TERMINAL = {"serving", "failed", "droplet_destroyed"}
_AGENT_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "crest_agent.py")


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def agent_droplet(authorization: Optional[str] = Header(None), db: Database = Depends(get_db)) -> dict:
    """Resolve the droplet that owns the presented agent bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing agent token")
    token = authorization.split(" ", 1)[1].strip()
    droplet = db.gpu_droplets.find_one({"agent_token_sha256": _sha256(token)})
    if not droplet:
        raise HTTPException(401, "Invalid agent token")
    return droplet


@router.get("/script")
def agent_script():
    """The canonical agent source. Public (not secret); cloud-init fetches it on
    every (re)start so the agent self-updates."""
    try:
        with open(_AGENT_SCRIPT, encoding="utf-8") as f:
            return PlainTextResponse(f.read(), media_type="text/x-python")
    except FileNotFoundError:
        raise HTTPException(500, "Agent script not found on server")


@router.post("/heartbeat")
def heartbeat(body: dict, droplet: dict = Depends(agent_droplet), db: Database = Depends(get_db)):
    now = datetime.now(timezone.utc)
    db.gpu_droplets.update_one({"_id": droplet["_id"]}, {"$set": {"agent_last_seen": now}})
    # Optionally refresh the serving deployment's health/logs (no backend→droplet needed).
    dep_id = body.get("deployment_id")
    if dep_id:
        upd = {}
        if body.get("health") is not None:
            upd["health"] = body["health"]
        if body.get("log_tail") is not None:
            upd["log_tail"] = body["log_tail"][-8000:]
        if upd:
            db.deployments.update_one(
                {"_id": oid(dep_id), "droplet_id": str(droplet["_id"]), "status": "serving"},
                {"$set": upd})
    return {"ok": True}


@router.get("/jobs/next")
def next_job(droplet: dict = Depends(agent_droplet), db: Database = Depends(get_db)):
    job = db.agent_jobs.find_one_and_update(
        {"droplet_id": str(droplet["_id"]), "status": "queued"},
        {"$set": {"status": "running", "started_at": datetime.now(timezone.utc)}},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    if not job:
        return Response(status_code=204)
    return {"id": str(job["_id"]), "type": job["type"], "spec": job.get("spec", {})}


@router.post("/jobs/{job_id}/event")
def job_event(job_id: str, body: dict, droplet: dict = Depends(agent_droplet), db: Database = Depends(get_db)):
    job = db.agent_jobs.find_one({"_id": oid(job_id), "droplet_id": str(droplet["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    status = body.get("status")
    event = body.get("event")
    now = datetime.now(timezone.utc)

    # Update the linked deployment doc — the source of truth the UI/SSE reads.
    dep_id = job.get("deployment_id")
    if dep_id:
        upd: dict = {}
        if status:
            upd["status"] = status
        if body.get("error") is not None:
            upd["status_detail"] = body["error"]
        if body.get("health") is not None:
            upd["health"] = body["health"]
        if body.get("log_tail") is not None:
            upd["log_tail"] = body["log_tail"][-8000:]
        if body.get("container_id"):
            upd["container_id"] = body["container_id"]
        ops: dict = {"$set": upd} if upd else {}
        if event:
            entry = {"event": event, "ts": now.isoformat()}
            if body.get("error"):
                entry["error"] = body["error"]
            ops["$push"] = {"events": {"$each": [entry], "$slice": -200}}
        if ops:
            db.deployments.update_one({"_id": oid(dep_id)}, ops)
        # Mirror into progress_store for any in-process readers.
        store = progress_store.setdefault(dep_id, {"events": []})
        if status:
            store["status"] = status
        if body.get("log_tail") is not None:
            store["log_tail"] = body["log_tail"][-4000:]

    # Advance the job's own lifecycle.
    job_upd = {"updated_at": now}
    if status in _DEPLOY_TERMINAL:
        job_upd["status"] = "completed" if status == "serving" else "failed"
        job_upd["completed_at"] = now
    db.agent_jobs.update_one({"_id": oid(job_id)}, {"$set": job_upd})
    return {"ok": True}

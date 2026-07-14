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
_BENCH_TERMINAL = {"completed", "failed"}
_AGENT_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "crest_agent.py")
# Ceiling for log_tail stored inline in the deployment/run doc. Mongo caps a document
# at 16 MB; 0.5 MB holds the full logs for any real failure while staying well clear.
MAX_LOG_TAIL = 500_000


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
    set_fields: dict = {"agent_last_seen": now}
    ops: dict = {"$set": set_fields}
    # GPU snapshot (nvidia-smi/rocm-smi) — latest for gauges + a capped rolling
    # history for sparklines on the Droplets tab.
    gpu = body.get("gpu")
    if isinstance(gpu, list) and gpu:
        sample = {"ts": now.isoformat(), "gpus": gpu}
        set_fields["gpu_stats"] = sample
        ops["$push"] = {"gpu_history": {"$each": [sample], "$slice": -60}}
    db.gpu_droplets.update_one({"_id": droplet["_id"]}, ops)
    # Optionally refresh the serving deployment's health/logs (no backend→droplet needed).
    dep_id = body.get("deployment_id")
    if dep_id:
        upd = {}
        if body.get("health") is not None:
            upd["health"] = body["health"]
        if body.get("log_tail") is not None:
            upd["log_tail"] = body["log_tail"][-MAX_LOG_TAIL:]
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


def _event_entry(event: str, body: dict, now: datetime) -> dict:
    entry = {"event": event, "ts": now.isoformat()}
    if body.get("error"):
        entry["error"] = body["error"]
    return entry


def _apply_deployment_event(db: Database, job: dict, body: dict, status, event, now) -> None:
    """Deploy job → update the deployment doc (the source of truth the UI/SSE reads)."""
    dep_id = job.get("deployment_id")
    if not dep_id:
        return
    upd: dict = {}
    if status:
        upd["status"] = status
    if body.get("error") is not None:
        upd["status_detail"] = body["error"]
    if body.get("health") is not None:
        upd["health"] = body["health"]
    if body.get("log_tail") is not None:
        upd["log_tail"] = body["log_tail"][-MAX_LOG_TAIL:]
    if body.get("container_id"):
        upd["container_id"] = body["container_id"]
    ops: dict = {"$set": upd} if upd else {}
    if event:
        ops["$push"] = {"events": {"$each": [_event_entry(event, body, now)], "$slice": -200}}
    if ops:
        db.deployments.update_one({"_id": oid(dep_id)}, ops)
    store = progress_store.setdefault(dep_id, {"events": []})
    if status:
        store["status"] = status
    if body.get("log_tail") is not None:
        store["log_tail"] = body["log_tail"][-4000:]


def _apply_benchmark_event(db: Database, job: dict, body: dict, status, event, now) -> None:
    """Benchmark job → update the aiperf_runs doc (NOT a deployment)."""
    run_id = job.get("aiperf_run_id")
    if not run_id:
        return
    upd: dict = {}
    if status:
        upd["status"] = status
        if status == "running":
            upd["started_at"] = now
        if status in _BENCH_TERMINAL:
            upd["completed_at"] = now
    if body.get("error") is not None:
        upd["status_detail"] = body["error"]
    if body.get("log_tail") is not None:
        upd["log_tail"] = body["log_tail"][-MAX_LOG_TAIL:]
    if isinstance(body.get("metrics"), dict):
        upd["metrics"] = body["metrics"]
    if isinstance(body.get("trends"), dict):
        upd["trends"] = body["trends"]
    ops: dict = {"$set": upd} if upd else {}
    if event:
        ops["$push"] = {"events": {"$each": [_event_entry(event, body, now)], "$slice": -200}}
    if ops:
        db.aiperf_runs.update_one({"_id": oid(run_id)}, ops)
    store = progress_store.setdefault(run_id, {"events": []})
    if status:
        store["status"] = status
    if body.get("log_tail") is not None:
        store["log_tail"] = body["log_tail"][-4000:]


@router.post("/jobs/{job_id}/event")
def job_event(job_id: str, body: dict, droplet: dict = Depends(agent_droplet), db: Database = Depends(get_db)):
    job = db.agent_jobs.find_one({"_id": oid(job_id), "droplet_id": str(droplet["_id"])})
    if not job:
        raise HTTPException(404, "Job not found")

    status = body.get("status")
    event = body.get("event")
    now = datetime.now(timezone.utc)
    jtype = job.get("type")

    if jtype == "benchmark":
        _apply_benchmark_event(db, job, body, status, event, now)
        terminal = _BENCH_TERMINAL
    else:
        _apply_deployment_event(db, job, body, status, event, now)
        terminal = _DEPLOY_TERMINAL

    # Advance the job's own lifecycle.
    job_upd = {"updated_at": now}
    if status in terminal:
        job_upd["status"] = "completed" if status in ("serving", "completed") else "failed"
        job_upd["completed_at"] = now
    db.agent_jobs.update_one({"_id": oid(job_id)}, {"$set": job_upd})
    return {"ok": True}

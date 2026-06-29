"""Benchmark (aiperf) routes (Benchmarking Evaluation — Step 3).

A benchmark run drives NVIDIA aiperf against a serving deployment's
OpenAI-compatible endpoint (localhost:<port>/v1) via the on-droplet agent. aiperf
only speaks OpenAI HTTP, so this layer is engine-agnostic.

Runs are self-describing — they carry droplet/deployment snapshots and the full
profile — so History (Step 4) survives droplet/deployment teardown and never has
to join back. Many runs per deployment; they execute serially on the droplet
(concurrent benchmarks would pollute each other's measurements).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from sse_starlette.sse import EventSourceResponse

from database import get_db, _id as doc_id, oid
from encryption import encrypt_api_key, decrypt_api_key
from schemas import (
    AiperfRunCreate, AiperfRunOut,
    AiperfConfigCreate, AiperfConfigOut, AiperfBatchCreate,
)
import engines
import orchestrator

router = APIRouter(prefix="/api/aiperf", tags=["aiperf"])

_TERMINAL = {"completed", "failed"}
_PENDING = {"queued", "running"}


def _aiperf_out(doc: dict, db: Database) -> AiperfRunOut:
    d = doc_id(doc)
    d.pop("hf_token_encrypted", None)
    dep = db.deployments.find_one({"_id": oid(d["deployment_id"])}) if d.get("deployment_id") else None
    snap = d.get("deployment_snapshot") or {}
    d["deployment_name"] = (dep.get("model") if dep else None) or snap.get("model")
    d["engine"] = snap.get("engine") or (dep.get("engine") if dep else "vllm")
    d["model"] = snap.get("model") or (dep.get("model") if dep else "")
    # How many runs are ahead of this one on the same droplet (serial execution).
    if d.get("status") in _PENDING and d.get("droplet_id") and d.get("created_at"):
        d["queue_position"] = db.aiperf_runs.count_documents({
            "droplet_id": d["droplet_id"], "status": {"$in": list(_PENDING)},
            "created_at": {"$lt": d["created_at"]},
        })
    return AiperfRunOut(**d)


@router.get("", response_model=list[AiperfRunOut])
def list_runs(deployment_id: Optional[str] = None, db: Database = Depends(get_db)):
    flt = {"deployment_id": deployment_id} if deployment_id else {}
    docs = list(db.aiperf_runs.find(flt).sort("created_at", -1))
    return [_aiperf_out(d, db) for d in docs]


@router.get("/history", response_model=list[AiperfRunOut])
def history(limit: int = 200, db: Database = Depends(get_db)):
    """Global, persistent list of every benchmark run (including those whose
    droplet/deployment were destroyed). Powers the History dashboards (Step 4)."""
    docs = list(db.aiperf_runs.find({}).sort("created_at", -1).limit(min(limit, 1000)))
    return [_aiperf_out(d, db) for d in docs]


@router.get("/preflight")
def preflight(deployment_id: str, db: Database = Depends(get_db)):
    """Tell the UI up front whether the tokenizer is gated and whether a token is
    already on file (from the deployment), so it can reuse it or prompt for one."""
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        raise HTTPException(404, "Deployment not found")
    return {
        "model": dep.get("model"),
        "port": dep.get("port") or 8000,
        "gated": engines.hf_model_is_gated(dep["model"]),
        "has_token": bool(dep.get("hf_token_encrypted")),
    }


def _ready_deployment(db: Database, deployment_id: str) -> tuple[dict, dict]:
    """Validate that the deployment is serving and its droplet is active, reconciling
    the droplet first so an out-of-band teardown is caught here (not by a benchmark
    hanging on an agent that will never poll). Returns (deployment, droplet)."""
    dep = db.deployments.find_one({"_id": oid(deployment_id)})
    if not dep:
        raise HTTPException(404, "Deployment not found")
    if dep.get("status") != "serving":
        raise HTTPException(409, f"Deployment must be serving to benchmark (status: {dep.get('status')})")
    orchestrator.reconcile_droplet(dep["droplet_id"])
    droplet = db.gpu_droplets.find_one({"_id": oid(dep["droplet_id"])})
    if not droplet or droplet.get("status") != "active":
        raise HTTPException(409, "The deployment's droplet is not active")
    return dep, droplet


def _require_tokenizer_token(dep: dict, hf_token: str) -> None:
    """aiperf downloads the HF tokenizer to count tokens — gated for gated models,
    like the weights. Reuse the deployment's token, or require an alternate one."""
    have_token = bool(hf_token) or bool(dep.get("hf_token_encrypted"))
    if not have_token and engines.hf_model_is_gated(dep["model"]):
        raise HTTPException(400, "This model's tokenizer is gated on HuggingFace and needs an access token. "
                                 "Add an HF token with access to this model, or choose an open model.")


def _enqueue_run(db: Database, dep: dict, droplet: dict, *, args: list[dict],
                 extra_percentiles: list[int], hf_token: str, now: datetime) -> str:
    """Insert a queued aiperf run from a resolved deployment/droplet + profile, and
    submit it to the agent. Returns the new run id. Shared by single and batch create
    so they build identical, self-describing run documents."""
    droplet_snapshot = dep.get("droplet_snapshot") or {
        "name": droplet.get("name"), "size_slug": droplet.get("size_slug"),
        "region": droplet.get("region"), "gpu_model": droplet.get("gpu_model"),
        "gpu_count": droplet.get("gpu_count"), "gpu_platform": droplet.get("gpu_platform"),
        "gpu_vram_gb": droplet.get("gpu_vram_gb"),
    }
    deployment_snapshot = {
        "engine": dep.get("engine"), "model": dep.get("model"),
        "port": dep.get("port") or 8000, "docker_image": dep.get("docker_image"),
        "server_args": dep.get("server_args") or [],
        "recipe_source_url": dep.get("recipe_source_url"),
        "hardware_key": dep.get("hardware_key"),
    }
    doc = {
        "deployment_id": str(dep["_id"]),
        "droplet_id": dep["droplet_id"],
        "droplet_snapshot": droplet_snapshot,
        "deployment_snapshot": deployment_snapshot,
        "profile": {"args": args, "extra_percentiles": extra_percentiles},
        # Alternate tokenizer token only (deployment's token is reused otherwise).
        "hf_token_encrypted": encrypt_api_key(hf_token) if hf_token else None,
        "status": "queued",
        "status_detail": None,
        "metrics": {},
        "log_tail": None,
        "events": [],
        "created_at": now,
        "started_at": None,
        "completed_at": None,
    }
    run_id = str(db.aiperf_runs.insert_one(doc).inserted_id)
    orchestrator.submit_run_aiperf(run_id)
    return run_id


@router.post("", response_model=AiperfRunOut, status_code=201)
def create_run(body: AiperfRunCreate, db: Database = Depends(get_db)):
    dep, droplet = _ready_deployment(db, body.deployment_id)
    _require_tokenizer_token(dep, body.hf_token)
    run_id = _enqueue_run(
        db, dep, droplet,
        args=[a.model_dump() for a in body.args],
        extra_percentiles=body.extra_percentiles,
        hf_token=body.hf_token, now=datetime.now(timezone.utc),
    )
    return _aiperf_out(db.aiperf_runs.find_one({"_id": oid(run_id)}), db)


@router.post("/batch", response_model=list[AiperfRunOut], status_code=201)
def create_batch(body: AiperfBatchCreate, db: Database = Depends(get_db)):
    """Queue many saved configs against one deployment in a single click. Validates
    the deployment/droplet and tokenizer once, then enqueues one run per config —
    they drain serially via the existing per-droplet queue."""
    if not body.config_ids:
        raise HTTPException(400, "Select at least one saved configuration to queue.")
    dep, droplet = _ready_deployment(db, body.deployment_id)
    _require_tokenizer_token(dep, body.hf_token)

    # Preserve the user's selection order, skipping ids that no longer exist.
    configs_by_id = {str(c["_id"]): c for c in
                     db.benchmark_configs.find({"_id": {"$in": [oid(i) for i in body.config_ids]}})}
    ordered = [configs_by_id[i] for i in body.config_ids if i in configs_by_id]
    if not ordered:
        raise HTTPException(404, "None of the selected configurations were found.")

    # Stagger created_at by microsecond so queue positions ("N ahead") read in the
    # user's selection order rather than tying on one identical timestamp.
    now = datetime.now(timezone.utc)
    run_ids = [
        _enqueue_run(
            db, dep, droplet,
            args=cfg.get("args") or [],
            extra_percentiles=cfg.get("extra_percentiles") or [],
            hf_token=body.hf_token, now=now + timedelta(microseconds=i),
        )
        for i, cfg in enumerate(ordered)
    ]
    runs = db.aiperf_runs.find({"_id": {"$in": [oid(r) for r in run_ids]}})
    by_id = {str(r["_id"]): r for r in runs}
    return [_aiperf_out(by_id[r], db) for r in run_ids]


# ── Saved benchmark configurations (named aiperf profiles) ─────────────────────
def _config_out(doc: dict) -> AiperfConfigOut:
    return AiperfConfigOut(**doc_id(doc))


@router.get("/configs", response_model=list[AiperfConfigOut])
def list_configs(db: Database = Depends(get_db)):
    docs = list(db.benchmark_configs.find({}).sort("created_at", -1))
    return [_config_out(d) for d in docs]


@router.post("/configs", response_model=AiperfConfigOut, status_code=201)
def create_config(body: AiperfConfigCreate, db: Database = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Configuration name is required.")
    now = datetime.now(timezone.utc)
    doc = {
        "name": name,
        "args": [a.model_dump() for a in body.args],
        "extra_percentiles": body.extra_percentiles,
        "created_at": now,
        "updated_at": now,
    }
    # Upsert by name so re-saving a config with the same name overwrites it.
    db.benchmark_configs.update_one(
        {"name": name},
        {"$set": {"args": doc["args"], "extra_percentiles": doc["extra_percentiles"],
                  "updated_at": now},
         "$setOnInsert": {"name": name, "created_at": now}},
        upsert=True,
    )
    return _config_out(db.benchmark_configs.find_one({"name": name}))


@router.delete("/configs/{config_id}", status_code=204)
def delete_config(config_id: str, db: Database = Depends(get_db)):
    res = db.benchmark_configs.delete_one({"_id": oid(config_id)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Configuration not found")
    return None


@router.get("/{run_id}", response_model=AiperfRunOut)
def get_run(run_id: str, db: Database = Depends(get_db)):
    doc = db.aiperf_runs.find_one({"_id": oid(run_id)})
    if not doc:
        raise HTTPException(404, "Benchmark run not found")
    return _aiperf_out(doc, db)


@router.get("/{run_id}/stream")
async def stream_run(run_id: str, api_key: Optional[str] = None):
    """SSE — reads the run doc (updated by the agent via routers/agent.py), so it
    works regardless of which app instance the agent reported to."""
    async def event_generator():
        db = get_db()
        while True:
            doc = db.aiperf_runs.find_one({"_id": oid(run_id)})
            if not doc:
                yield {"data": json.dumps({"status": "failed", "status_detail": "Benchmark run not found"})}
                break
            yield {"data": json.dumps({
                "status": doc.get("status"),
                "status_detail": doc.get("status_detail"),
                "log_tail": doc.get("log_tail"),
                "metrics": doc.get("metrics") or {},
                "events": doc.get("events", []),
            })}
            if doc.get("status") in _TERMINAL:
                break
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())

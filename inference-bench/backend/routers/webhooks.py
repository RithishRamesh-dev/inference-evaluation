"""CI/CD webhook integration routes."""
from __future__ import annotations
import os
import secrets
import asyncio
from datetime import datetime, timezone
import httpx
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Header
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import WebhookKeyOut, WebhookKeyCreated, WebhookTriggerRequest

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

WEBHOOK_HEADER = "X-Gauge-Webhook-Key"


def _verify_webhook_key(key: str, db: Database) -> bool:
    docs = list(db.webhook_keys.find({}))
    for doc in docs:
        try:
            if bcrypt.checkpw(key.encode(), doc["key_hash"].encode()):
                return True
        except Exception:
            pass
    return False


@router.get("/keys", response_model=list[WebhookKeyOut])
def list_keys(db: Database = Depends(get_db)):
    docs = list(db.webhook_keys.find({}).sort("created_at", -1))
    return [WebhookKeyOut(id=str(d["_id"]), name=d.get("name", ""), key_prefix=d.get("key_prefix", ""), created_at=d.get("created_at")) for d in docs]


@router.post("/keys", response_model=WebhookKeyCreated, status_code=201)
def create_key(body: dict, db: Database = Depends(get_db)):
    name = body.get("name", "Webhook Key")
    raw_key = f"gauge_{secrets.token_hex(24)}"
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc)
    doc = {"name": name, "key_hash": key_hash, "key_prefix": raw_key[:12], "created_at": now}
    result = db.webhook_keys.insert_one(doc)
    return WebhookKeyCreated(id=str(result.inserted_id), name=name, key=raw_key, created_at=now)


@router.delete("/keys/{key_id}", status_code=204)
def delete_key(key_id: str, db: Database = Depends(get_db)):
    db.webhook_keys.delete_one({"_id": oid(key_id)})


@router.post("/trigger")
async def trigger_evaluation(
    body: WebhookTriggerRequest,
    x_gauge_webhook_key: str = Header(..., alias="X-Gauge-Webhook-Key"),
    db: Database = Depends(get_db),
):
    if not _verify_webhook_key(x_gauge_webhook_key, db):
        raise HTTPException(401, "Invalid webhook key")

    # Import here to avoid circular
    from worker import submit_evaluation
    from database import oid as _oid

    model = db.models.find_one({"_id": _oid(body.model_id)})
    if not model:
        raise HTTPException(404, "Model not found")

    # Create evaluation run
    from datetime import datetime, timezone as tz
    run_doc = {
        "model_id": body.model_id,
        "display_name": f"Webhook run {datetime.now(tz.utc).strftime('%Y-%m-%d %H:%M')}",
        "status": "queued",
        "total_benchmarks": len(body.benchmark_ids),
        "passed_benchmarks": 0,
        "overall_score": None,
        "started_at": None,
        "completed_at": None,
        "wall_time_seconds": None,
        "created_at": datetime.now(tz.utc),
        "callback_url": body.callback_url,
        **body.eval_config,
    }
    run_id = str(db.evaluation_runs.insert_one(run_doc).inserted_id)
    for bid in body.benchmark_ids:
        db.run_benchmarks.insert_one({
            "run_id": run_id, "benchmark_suite_id": bid,
            "status": "pending", "primary_score": None, "subset_scores": "{}",
            "started_at": None, "completed_at": None,
        })

    submit_evaluation(run_id)
    db.evaluation_runs.update_one({"_id": _oid(run_id)}, {"$set": {"status": "running"}})
    return {"run_id": run_id, "status": "running"}

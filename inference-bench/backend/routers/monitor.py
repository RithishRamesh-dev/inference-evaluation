"""Real-time endpoint monitoring routes."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import MonitorConfigCreate, MonitorConfigOut, MonitorResultOut

router = APIRouter(prefix="/api/monitors", tags=["monitors"])


def _monitor_out(doc: dict, db: Database) -> MonitorConfigOut:
    d = doc_id(doc)
    model = db.models.find_one({"_id": oid(d["model_id"])}) if d.get("model_id") else None
    d["model_name"] = model.get("name") if model else None
    # Get latest result for status
    latest = db.monitor_results.find_one({"monitor_config_id": d["id"]}, sort=[("run_at", -1)])
    d["latest_status"] = latest.get("status") if latest else None
    return MonitorConfigOut(**d)


@router.get("", response_model=list[MonitorConfigOut])
def list_monitors(db: Database = Depends(get_db)):
    docs = list(db.monitor_configs.find({}).sort("created_at", -1))
    return [_monitor_out(d, db) for d in docs]


@router.post("", response_model=MonitorConfigOut, status_code=201)
def create_monitor(body: MonitorConfigCreate, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(body.model_id)}):
        raise HTTPException(404, "Model not found")
    now = datetime.now(timezone.utc)
    doc = {**body.model_dump(), "created_at": now}
    result = db.monitor_configs.insert_one(doc)
    return _monitor_out(db.monitor_configs.find_one({"_id": result.inserted_id}), db)


@router.get("/{monitor_id}", response_model=MonitorConfigOut)
def get_monitor(monitor_id: str, db: Database = Depends(get_db)):
    doc = db.monitor_configs.find_one({"_id": oid(monitor_id)})
    if not doc:
        raise HTTPException(404, "Monitor not found")
    return _monitor_out(doc, db)


@router.put("/{monitor_id}/toggle")
def toggle_monitor(monitor_id: str, db: Database = Depends(get_db)):
    doc = db.monitor_configs.find_one({"_id": oid(monitor_id)})
    if not doc:
        raise HTTPException(404, "Monitor not found")
    new_state = not doc.get("enabled", True)
    db.monitor_configs.update_one({"_id": oid(monitor_id)}, {"$set": {"enabled": new_state}})
    return {"enabled": new_state}


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: str, db: Database = Depends(get_db)):
    db.monitor_configs.delete_one({"_id": oid(monitor_id)})
    db.monitor_results.delete_many({"monitor_config_id": monitor_id})


@router.get("/{monitor_id}/results", response_model=list[MonitorResultOut])
def get_monitor_results(monitor_id: str, hours: int = 24, db: Database = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    docs = list(db.monitor_results.find(
        {"monitor_config_id": monitor_id, "run_at": {"$gte": since}}
    ).sort("run_at", -1).limit(288))  # max 5-min intervals over 24h
    return [MonitorResultOut(**doc_id(d)) for d in docs]


@router.get("/{monitor_id}/uptime")
def get_uptime(monitor_id: str, db: Database = Depends(get_db)):
    def _uptime(hours: int):
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        total = db.monitor_results.count_documents({"monitor_config_id": monitor_id, "run_at": {"$gte": since}})
        healthy = db.monitor_results.count_documents({"monitor_config_id": monitor_id, "run_at": {"$gte": since}, "status": "healthy"})
        return round(healthy / max(total, 1) * 100, 1)
    return {"uptime_24h": _uptime(24), "uptime_7d": _uptime(168), "uptime_30d": _uptime(720)}


@router.get("/{monitor_id}/incidents")
def get_incidents(monitor_id: str, db: Database = Depends(get_db)):
    results = list(db.monitor_results.find({"monitor_config_id": monitor_id}).sort("run_at", 1).limit(1000))
    incidents = []
    in_incident = False
    start_time = None
    for r in results:
        status = r.get("status", "healthy")
        run_at = r.get("run_at")
        if status in ("degraded", "down") and not in_incident:
            in_incident = True
            start_time = run_at
        elif status == "healthy" and in_incident:
            in_incident = False
            if start_time:
                duration = (run_at - start_time).total_seconds() if run_at and start_time else 0
                incidents.append({"start": start_time, "end": run_at, "duration_seconds": int(duration)})
    return incidents

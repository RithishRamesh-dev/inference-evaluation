"""Scheduled evaluation routes."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import ScheduledEvalCreate, ScheduledEvalOut

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _cron_description(cron: str) -> str:
    """Human-readable description of cron expression."""
    try:
        from croniter import croniter
        c = croniter(cron)
        # Get next 2 runs to infer frequency
        n1 = c.get_next(datetime)
        n2 = c.get_next(datetime)
        diff_hours = (n2 - n1).total_seconds() / 3600
        if diff_hours <= 1.1:
            return "Every hour"
        elif diff_hours <= 24.1:
            return f"Daily at {n1.strftime('%H:%M')}"
        elif diff_hours <= 168.1:
            return f"Weekly on {n1.strftime('%A')} at {n1.strftime('%H:%M')}"
        else:
            return f"Every {int(diff_hours/24)} days"
    except Exception:
        return cron


def _sched_out(doc: dict, db: Database) -> ScheduledEvalOut:
    d = doc_id(doc)
    model = db.models.find_one({"_id": oid(d["model_id"])}) if d.get("model_id") else None
    d["model_name"] = model.get("name") if model else None
    return ScheduledEvalOut(**d)


def _compute_next_run(cron: str) -> Optional[datetime]:
    try:
        from croniter import croniter
        c = croniter(cron, datetime.now(timezone.utc))
        return c.get_next(datetime)
    except Exception:
        return None


@router.get("", response_model=list[ScheduledEvalOut])
def list_schedules(db: Database = Depends(get_db)):
    docs = list(db.scheduled_evaluations.find({}).sort("created_at", -1))
    return [_sched_out(d, db) for d in docs]


@router.post("", response_model=ScheduledEvalOut, status_code=201)
def create_schedule(body: ScheduledEvalCreate, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(body.model_id)}):
        raise HTTPException(404, "Model not found")
    # Validate cron
    try:
        from croniter import croniter
        croniter(body.schedule_cron)
    except Exception:
        raise HTTPException(400, f"Invalid cron expression: {body.schedule_cron}")

    now = datetime.now(timezone.utc)
    next_run = _compute_next_run(body.schedule_cron)
    doc = {**body.model_dump(), "last_run_at": None, "next_run_at": next_run, "created_at": now}
    result = db.scheduled_evaluations.insert_one(doc)
    return _sched_out(db.scheduled_evaluations.find_one({"_id": result.inserted_id}), db)


@router.get("/{schedule_id}", response_model=ScheduledEvalOut)
def get_schedule(schedule_id: str, db: Database = Depends(get_db)):
    doc = db.scheduled_evaluations.find_one({"_id": oid(schedule_id)})
    if not doc:
        raise HTTPException(404, "Schedule not found")
    return _sched_out(doc, db)


@router.put("/{schedule_id}/toggle")
def toggle_schedule(schedule_id: str, db: Database = Depends(get_db)):
    doc = db.scheduled_evaluations.find_one({"_id": oid(schedule_id)})
    if not doc:
        raise HTTPException(404, "Schedule not found")
    new_state = not doc.get("enabled", True)
    db.scheduled_evaluations.update_one({"_id": oid(schedule_id)}, {"$set": {"enabled": new_state}})
    return {"enabled": new_state}


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, db: Database = Depends(get_db)):
    db.scheduled_evaluations.delete_one({"_id": oid(schedule_id)})


@router.get("/{schedule_id}/cron-description")
def cron_description(schedule_id: str, db: Database = Depends(get_db)):
    doc = db.scheduled_evaluations.find_one({"_id": oid(schedule_id)})
    if not doc:
        raise HTTPException(404, "Schedule not found")
    return {"description": _cron_description(doc["schedule_cron"]), "next_run": doc.get("next_run_at")}


@router.post("/cron-preview")
def preview_cron(body: dict):
    cron = body.get("cron", "")
    return {"description": _cron_description(cron), "next_run": _compute_next_run(cron)}

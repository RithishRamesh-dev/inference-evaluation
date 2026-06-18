"""Probe history — saves probe run results (no API keys stored)."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import ProbeHistoryOut

router = APIRouter(prefix="/api/probe-history", tags=["probe-history"])


def _summarize_checks(checks: list) -> dict:
    summary = {"passed": 0, "failed": 0, "warned": 0, "skipped": 0}
    for c in checks:
        s = c.get("status", "fail")
        if s == "pass":
            summary["passed"] += 1
        elif s == "warn":
            summary["warned"] += 1
        elif s == "skip":
            summary["skipped"] += 1
        else:
            summary["failed"] += 1
    return summary


@router.get("", response_model=list[ProbeHistoryOut])
def list_history(db: Database = Depends(get_db)):
    docs = list(db.probe_history.find({}).sort("created_at", -1).limit(20))
    return [ProbeHistoryOut(**doc_id(d)) for d in docs]


@router.get("/{probe_id}")
def get_probe(probe_id: str, db: Database = Depends(get_db)):
    doc = db.probe_history.find_one({"_id": oid(probe_id)})
    if not doc:
        raise HTTPException(404, "Probe run not found")
    d = doc_id(doc)
    return d


@router.delete("/{probe_id}", status_code=204)
def delete_probe(probe_id: str, db: Database = Depends(get_db)):
    db.probe_history.delete_one({"_id": oid(probe_id)})

"""Load profiling and heatmap routes."""
from __future__ import annotations
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import LoadProfileOut, LoadWindow
from encryption import decrypt_api_key

router = APIRouter(prefix="/api/models", tags=["load-profile"])


def compute_load_profile(model_id: str, db: Database) -> dict:
    """Aggregate load_samples into 7x24 heatmap."""
    since = datetime.now(timezone.utc) - timedelta(days=30)
    samples = list(db.load_samples.find({
        "model_id": model_id,
        "sampled_at": {"$gte": since},
        "status": "ok",
    }))

    data_points = len(samples)

    if data_points < 10:
        return {
            "model_id": model_id,
            "heatmap": [[0.0]*24 for _ in range(7)],
            "quietest_windows": [],
            "busiest_windows": [],
            "current_load": None,
            "data_points": data_points,
            "confidence": "insufficient",
        }

    # Build 7x24 matrix
    matrix: list[list[list[float]]] = [[[] for _ in range(24)] for _ in range(7)]
    for s in samples:
        d = s.get("day_of_week", 0) % 7
        h = s.get("hour_of_day", 0) % 24
        matrix[d][h].append(s.get("latency_ms", 0))

    avg_matrix: list[list[float]] = [[0.0]*24 for _ in range(7)]
    all_avgs: list[float] = []
    for d in range(7):
        for h in range(24):
            vals = matrix[d][h]
            if vals:
                avg = sum(vals) / len(vals)
                avg_matrix[d][h] = avg
                all_avgs.append(avg)

    if not all_avgs:
        return {
            "model_id": model_id,
            "heatmap": [[0.0]*24 for _ in range(7)],
            "quietest_windows": [],
            "busiest_windows": [],
            "current_load": None,
            "data_points": data_points,
            "confidence": "insufficient",
        }

    min_val = min(all_avgs)
    max_val = max(all_avgs)
    rng = max_val - min_val or 1.0

    # Normalize
    norm_matrix: list[list[float]] = [[0.0]*24 for _ in range(7)]
    windows: list[dict] = []
    for d in range(7):
        for h in range(24):
            raw = avg_matrix[d][h]
            norm = (raw - min_val) / rng if raw > 0 else 0.0
            norm_matrix[d][h] = round(norm, 3)
            if raw > 0:
                windows.append({"day": d, "hour": h, "avg_latency_ms": round(raw, 1), "load_score": round(norm, 3)})

    windows.sort(key=lambda x: x["load_score"])
    quietest = windows[:5]
    busiest = windows[-5:][::-1]

    confidence = "high" if data_points >= 500 else ("medium" if data_points >= 100 else "low")

    return {
        "model_id": model_id,
        "heatmap": norm_matrix,
        "quietest_windows": quietest,
        "busiest_windows": busiest,
        "current_load": None,
        "data_points": data_points,
        "confidence": confidence,
    }


@router.get("/{model_id}/load-profile")
def get_load_profile(model_id: str, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}):
        raise HTTPException(404, "Model not found")
    return compute_load_profile(model_id, db)


@router.get("/{model_id}/load-heatmap")
def get_load_heatmap(model_id: str, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}):
        raise HTTPException(404, "Model not found")
    profile = compute_load_profile(model_id, db)
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return {
        "heatmap": profile["heatmap"],
        "days": days,
        "hours": list(range(24)),
        "data_points": profile["data_points"],
        "confidence": profile["confidence"],
        "quietest_windows": profile["quietest_windows"],
    }


@router.get("/{model_id}/load-samples/count")
def load_sample_count(model_id: str, db: Database = Depends(get_db)):
    count = db.load_samples.count_documents({"model_id": model_id})
    return {"count": count}

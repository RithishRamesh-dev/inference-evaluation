"""A/B test run management routes."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import ABTestCreate, ABTestOut
from worker import submit_evaluation

router = APIRouter(prefix="/api/ab-tests", tags=["ab-tests"])


def _ab_out(doc: dict, db: Database) -> dict:
    d = doc_id(doc)
    # Enrich with run statuses
    run_ids = d.get("run_ids", [])
    runs = []
    for rid in run_ids:
        try:
            run = db.evaluation_runs.find_one({"_id": oid(rid)})
            if run:
                rd = doc_id(run)
                model = db.models.find_one({"_id": oid(rd["model_id"])}) if rd.get("model_id") else None
                rd["model_name"] = model.get("name") if model else None
                # Get benchmark results
                rbs = list(db.run_benchmarks.find({"run_id": rid}))
                rd["run_benchmarks"] = []
                for rb in rbs:
                    suite = db.benchmark_suites.find_one({"_id": oid(rb["benchmark_suite_id"])}) if rb.get("benchmark_suite_id") else None
                    rbd = doc_id(rb)
                    rbd["suite_name"] = suite.get("name") if suite else None
                    rbd["suite_display_name"] = suite.get("display_name") if suite else None
                    rd["run_benchmarks"].append(rbd)
                runs.append(rd)
        except Exception:
            pass
    d["runs"] = runs

    # Check if all runs are complete
    if run_ids:
        statuses = [r.get("status") for r in runs]
        if all(s == "completed" for s in statuses):
            d["status"] = "completed"
        elif any(s == "failed" for s in statuses):
            d["status"] = "failed"
        elif any(s in ("running", "queued") for s in statuses):
            d["status"] = "running"

    return d


@router.get("", response_model=list[dict])
def list_ab_tests(db: Database = Depends(get_db)):
    docs = list(db.ab_test_runs.find({}).sort("created_at", -1).limit(50))
    return [_ab_out(d, db) for d in docs]


@router.post("", status_code=201)
def create_ab_test(body: ABTestCreate, db: Database = Depends(get_db)):
    if len(body.model_ids) < 2:
        raise HTTPException(400, "At least 2 models required")
    if len(body.model_ids) > 4:
        raise HTTPException(400, "Maximum 4 models")

    now = datetime.now(timezone.utc)
    run_ids = []

    for mid in body.model_ids:
        model = db.models.find_one({"_id": oid(mid)})
        if not model:
            raise HTTPException(404, f"Model {mid} not found")

        model_name = model.get("name", mid)
        run_doc = {
            "model_id": mid,
            "display_name": f"{body.name} — {model_name}",
            "status": "queued",
            "total_benchmarks": len(body.benchmark_ids),
            "passed_benchmarks": 0,
            "overall_score": None,
            "started_at": None,
            "completed_at": None,
            "wall_time_seconds": None,
            "created_at": now,
            "sample_count": body.sample_count,
            **body.eval_config,
        }
        run_id = str(db.evaluation_runs.insert_one(run_doc).inserted_id)

        for bid in body.benchmark_ids:
            if not db.benchmark_suites.find_one({"_id": oid(bid)}):
                continue
            db.run_benchmarks.insert_one({
                "run_id": run_id,
                "benchmark_suite_id": bid,
                "status": "pending",
                "primary_score": None,
                "subset_scores": "{}",
                "started_at": None,
                "completed_at": None,
            })

        submit_evaluation(run_id)
        db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "running"}})
        run_ids.append(run_id)

    ab_doc = {
        "name": body.name,
        "benchmark_ids": body.benchmark_ids,
        "model_ids": body.model_ids,
        "eval_config": body.eval_config,
        "status": "running",
        "run_ids": run_ids,
        "created_at": now,
        "completed_at": None,
    }
    ab_id = str(db.ab_test_runs.insert_one(ab_doc).inserted_id)
    return {"ab_test_id": ab_id, "run_ids": run_ids}


@router.get("/{ab_id}")
def get_ab_test(ab_id: str, db: Database = Depends(get_db)):
    doc = db.ab_test_runs.find_one({"_id": oid(ab_id)})
    if not doc:
        raise HTTPException(404, "A/B test not found")
    return _ab_out(doc, db)


@router.get("/{ab_id}/winner")
def get_ab_winner(ab_id: str, db: Database = Depends(get_db)):
    doc = db.ab_test_runs.find_one({"_id": oid(ab_id)})
    if not doc:
        raise HTTPException(404, "A/B test not found")

    ab = _ab_out(doc, db)
    benchmark_ids = ab.get("benchmark_ids", [])
    results = {}

    for bid in benchmark_ids:
        suite = db.benchmark_suites.find_one({"_id": oid(bid)}) if bid else None
        bench_name = suite.get("display_name", bid) if suite else bid
        scores: dict = {}

        for run in ab.get("runs", []):
            model_id = run.get("model_id")
            for rb in run.get("run_benchmarks", []):
                if rb.get("benchmark_suite_id") == bid and rb.get("primary_score") is not None:
                    scores[model_id] = rb["primary_score"]

        winner = max(scores, key=lambda m: scores[m]) if scores else None
        results[bid] = {
            "benchmark_name": bench_name,
            "winner_model_id": winner,
            "scores": scores,
        }

    return results

"""Eval run template management routes."""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import EvalTemplateCreate, EvalTemplateOut
from worker import submit_evaluation

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[EvalTemplateOut])
def list_templates(db: Database = Depends(get_db)):
    docs = list(db.eval_templates.find({}).sort("created_at", -1))
    return [EvalTemplateOut(**doc_id(d)) for d in docs]


@router.post("", response_model=EvalTemplateOut, status_code=201)
def create_template(body: EvalTemplateCreate, db: Database = Depends(get_db)):
    now = datetime.now(timezone.utc)
    doc = {**body.model_dump(), "created_at": now}
    result = db.eval_templates.insert_one(doc)
    return EvalTemplateOut(**doc_id(db.eval_templates.find_one({"_id": result.inserted_id})))


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str, db: Database = Depends(get_db)):
    db.eval_templates.delete_one({"_id": oid(template_id)})


@router.post("/{template_id}/launch")
def launch_from_template(template_id: str, model_id: str = None, db: Database = Depends(get_db)):
    tmpl = db.eval_templates.find_one({"_id": oid(template_id)})
    if not tmpl:
        raise HTTPException(404, "Template not found")

    mid = model_id or tmpl.get("model_id")
    if not mid:
        raise HTTPException(400, "model_id required")
    if not db.models.find_one({"_id": oid(mid)}):
        raise HTTPException(404, "Model not found")

    now = datetime.now(timezone.utc)
    run_doc = {
        "model_id": mid,
        "display_name": f"{tmpl['name']} run",
        "status": "queued",
        "total_benchmarks": len(tmpl.get("benchmark_ids", [])),
        "passed_benchmarks": 0,
        "overall_score": None,
        "started_at": None,
        "completed_at": None,
        "wall_time_seconds": None,
        "created_at": now,
        **tmpl.get("eval_config", {}),
    }
    run_id = str(db.evaluation_runs.insert_one(run_doc).inserted_id)
    for bid in tmpl.get("benchmark_ids", []):
        if db.benchmark_suites.find_one({"_id": oid(bid)}):
            db.run_benchmarks.insert_one({
                "run_id": run_id, "benchmark_suite_id": bid,
                "status": "pending", "primary_score": None,
                "subset_scores": "{}", "started_at": None, "completed_at": None,
            })

    submit_evaluation(run_id)
    db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "running"}})
    return {"run_id": run_id}

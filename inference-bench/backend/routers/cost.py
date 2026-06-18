"""Cost tracking and pricing routes."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import ModelPricingCreate, ModelPricingOut, BudgetConfigCreate, BudgetConfigOut

router = APIRouter(prefix="/api/cost", tags=["cost"])

# Known pricing for common DO Serverless models (per 1K tokens, USD)
KNOWN_PRICING = [
    {"model_pattern": "llama3.3-70b", "input": 0.00059, "output": 0.00079},
    {"model_pattern": "llama3.1-70b", "input": 0.00059, "output": 0.00079},
    {"model_pattern": "llama3.1-405b", "input": 0.00500, "output": 0.00500},
    {"model_pattern": "mistral", "input": 0.00020, "output": 0.00060},
    {"model_pattern": "gpt-4o", "input": 0.00500, "output": 0.01500},
    {"model_pattern": "gpt-4o-mini", "input": 0.00015, "output": 0.00060},
    {"model_pattern": "claude-3-5", "input": 0.00300, "output": 0.01500},
]


@router.get("/pricing", response_model=list[ModelPricingOut])
def list_pricing(db: Database = Depends(get_db)):
    docs = list(db.model_pricing.find({}))
    return [ModelPricingOut(**doc_id(d)) for d in docs]


@router.post("/pricing", response_model=ModelPricingOut, status_code=201)
def create_pricing(body: ModelPricingCreate, db: Database = Depends(get_db)):
    now = datetime.now(timezone.utc)
    doc = {**body.model_dump(), "created_at": now}
    result = db.model_pricing.insert_one(doc)
    return ModelPricingOut(**doc_id(db.model_pricing.find_one({"_id": result.inserted_id})))


@router.delete("/pricing/{pricing_id}", status_code=204)
def delete_pricing(pricing_id: str, db: Database = Depends(get_db)):
    db.model_pricing.delete_one({"_id": oid(pricing_id)})


@router.get("/budget", response_model=list[BudgetConfigOut])
def list_budgets(db: Database = Depends(get_db)):
    docs = list(db.budget_configs.find({}))
    return [BudgetConfigOut(**doc_id(d)) for d in docs]


@router.post("/budget", response_model=BudgetConfigOut, status_code=201)
def create_budget(body: BudgetConfigCreate, db: Database = Depends(get_db)):
    now = datetime.now(timezone.utc)
    doc = {**body.model_dump(), "created_at": now}
    result = db.budget_configs.insert_one(doc)
    return BudgetConfigOut(**doc_id(db.budget_configs.find_one({"_id": result.inserted_id})))


@router.delete("/budget/{budget_id}", status_code=204)
def delete_budget(budget_id: str, db: Database = Depends(get_db)):
    db.budget_configs.delete_one({"_id": oid(budget_id)})


@router.get("/summary")
def cost_summary(days: int = 30, db: Database = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Get all completed runs in period
    runs = list(db.evaluation_runs.find({"status": "completed", "created_at": {"$gte": since}}))

    # For each run, compute cost from run_benchmarks
    model_costs: dict = {}
    daily_costs: dict = {}

    for run in runs:
        rid = str(run["_id"])
        mid = run.get("model_id", "")
        rbs = list(db.run_benchmarks.find({"run_id": rid}))

        # Get model info
        model = db.models.find_one({"_id": oid(mid)}) if mid else None
        pricing = None
        if model:
            pricing = db.model_pricing.find_one({"model_id": mid})

        run_cost = 0.0
        for rb in rbs:
            if pricing:
                input_tok = rb.get("avg_input_tokens", 0) or 0
                output_tok = rb.get("avg_output_tokens", 0) or 0
                samples = rb.get("samples_scored", 0) or 0
                cost = (input_tok * samples * pricing["price_per_1k_input_tokens"] / 1000 +
                        output_tok * samples * pricing["price_per_1k_output_tokens"] / 1000)
                run_cost += round(cost, 6)

        model_name = model.get("name", "Unknown") if model else "Unknown"
        if mid not in model_costs:
            model_costs[mid] = {"model_id": mid, "model_name": model_name, "total_cost_usd": 0.0, "run_count": 0}
        model_costs[mid]["total_cost_usd"] += run_cost
        model_costs[mid]["run_count"] += 1

        # Daily
        day = run["created_at"].strftime("%Y-%m-%d") if run.get("created_at") else "unknown"
        daily_costs[day] = daily_costs.get(day, 0.0) + run_cost

    total = sum(v["total_cost_usd"] for v in model_costs.values())

    return {
        "total_cost_usd": round(total, 6),
        "period_days": days,
        "by_model": list(model_costs.values()),
        "by_day": [{"date": k, "cost_usd": round(v, 6)} for k, v in sorted(daily_costs.items())],
    }

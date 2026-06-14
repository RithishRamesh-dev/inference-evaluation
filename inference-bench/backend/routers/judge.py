"""LLM-as-Judge evaluation routes."""
from __future__ import annotations
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid

router = APIRouter(prefix="/api", tags=["judge"])

JUDGE_PROMPT = """You are evaluating an AI model's response quality.

Question: {question}
Expected Answer: {expected_answer}
Model Response: {model_output}

Score this response on the following dimensions. For each dimension provide a score from 1-10 and a one-sentence justification.

Dimensions to score: {dimensions}

Respond ONLY in valid JSON format:
{{"dimensions": {{"dimension_name": {{"score": 8, "reason": "..."}}, ...}}}}"""


async def _run_judge_on_sample(
    sample: dict, judge_config: dict,
    endpoint_url: str, api_key: str, judge_model_id: str
) -> dict:
    dims = [d["name"] for d in judge_config.get("dimensions", [])]
    prompt = JUDGE_PROMPT.format(
        question=sample.get("question", ""),
        expected_answer=sample.get("expected_answer", ""),
        model_output=sample.get("model_output", ""),
        dimensions=", ".join(dims),
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": judge_model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{endpoint_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
        if r.status_code != 200:
            return {}
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        dim_scores = parsed.get("dimensions", {})

        # Compute weighted overall score
        total_weight = sum(d["weight"] for d in judge_config["dimensions"])
        overall = 0.0
        for d in judge_config["dimensions"]:
            ds = dim_scores.get(d["name"], {})
            score = ds.get("score", 5) if isinstance(ds, dict) else 5
            overall += (score / 10.0) * (d["weight"] / total_weight)

        return {
            "dimension_scores": {k: v if isinstance(v, dict) else {"score": v, "reason": ""} for k, v in dim_scores.items()},
            "overall_score": round(overall, 3),
            "judge_reasoning": content,
        }
    except Exception:
        return {}


@router.get("/judge/configs")
def list_judge_configs(db: Database = Depends(get_db)):
    docs = list(db.llm_judge_configs.find({}))
    return [{"id": str(d["_id"]), "name": d["name"], "description": d.get("description", ""),
             "dimensions": d.get("dimensions", []), "min_score": d.get("min_score", 1),
             "max_score": d.get("max_score", 10)} for d in docs]


@router.post("/evaluations/{run_id}/judge")
async def run_judge(run_id: str, body: dict, db: Database = Depends(get_db)):
    judge_config_id = body.get("judge_config_id")
    judge_endpoint_url = body.get("judge_endpoint_url", "")
    judge_api_key = body.get("judge_api_key", "")
    judge_model_id = body.get("judge_model_id", "")

    if not all([judge_config_id, judge_endpoint_url, judge_api_key, judge_model_id]):
        raise HTTPException(400, "Missing required fields")

    judge_config = db.llm_judge_configs.find_one({"_id": oid(judge_config_id)})
    if not judge_config:
        raise HTTPException(404, "Judge config not found")

    run = db.evaluation_runs.find_one({"_id": oid(run_id)})
    if not run:
        raise HTTPException(404, "Evaluation not found")

    # Get run_benchmarks for this run
    rbs = list(db.run_benchmarks.find({"run_id": run_id}))
    rb_ids = [str(rb["_id"]) for rb in rbs]

    # Get samples
    sample_ids = body.get("sample_ids")
    if sample_ids:
        samples = list(db.sample_outputs.find({"_id": {"$in": [oid(s) for s in sample_ids]}}))
    else:
        samples = list(db.sample_outputs.find({"run_benchmark_id": {"$in": rb_ids}}))

    if not samples:
        return {"judged_count": 0, "avg_score": 0.0, "dimension_averages": {}}

    # Run judge in batches of 5
    now = datetime.now(timezone.utc)
    results = []
    batch_size = 5
    for i in range(0, len(samples), batch_size):
        batch = samples[i:i + batch_size]
        batch_results = await asyncio.gather(*[
            _run_judge_on_sample(doc_id(s), judge_config, judge_endpoint_url, judge_api_key, judge_model_id)
            for s in batch
        ])
        for sample, result in zip(batch, batch_results):
            if not result:
                continue
            doc = {
                "run_benchmark_id": sample.get("run_benchmark_id", ""),
                "sample_output_id": str(sample["_id"]),
                "judge_config_id": judge_config_id,
                "dimension_scores": result.get("dimension_scores", {}),
                "overall_score": result.get("overall_score", 0.0),
                "judge_reasoning": result.get("judge_reasoning", ""),
                "created_at": now,
            }
            db.llm_judge_results.insert_one(doc)
            results.append(result)

    if not results:
        return {"judged_count": 0, "avg_score": 0.0, "dimension_averages": {}}

    avg_score = sum(r["overall_score"] for r in results) / len(results)

    # Dimension averages
    dim_avgs: dict = {}
    for r in results:
        for dim, val in r.get("dimension_scores", {}).items():
            score = val.get("score", 0) if isinstance(val, dict) else 0
            dim_avgs.setdefault(dim, []).append(score)
    dim_averages = {k: round(sum(v) / len(v), 2) for k, v in dim_avgs.items()}

    return {"judged_count": len(results), "avg_score": round(avg_score, 3), "dimension_averages": dim_averages}


@router.get("/evaluations/{run_id}/judge/results")
def get_judge_results(run_id: str, db: Database = Depends(get_db)):
    rbs = list(db.run_benchmarks.find({"run_id": run_id}))
    rb_ids = [str(rb["_id"]) for rb in rbs]
    docs = list(db.llm_judge_results.find({"run_benchmark_id": {"$in": rb_ids}}).sort("created_at", -1))
    result = []
    for d in docs:
        dd = doc_id(d)
        sample = db.sample_outputs.find_one({"_id": oid(dd["sample_output_id"])}) if dd.get("sample_output_id") else None
        dd["question"] = sample.get("question", "") if sample else ""
        dd["model_output_preview"] = (sample.get("model_output", "") or "")[:200] if sample else ""
        result.append(dd)
    return result

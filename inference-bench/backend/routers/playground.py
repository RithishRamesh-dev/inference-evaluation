"""Playground routes — ephemeral completions, no DB storage for runs."""
from __future__ import annotations
import time
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from database import get_db, _id as doc_id, oid
from schemas import (
    PlaygroundRunRequest, PlaygroundRunResult, PlaygroundBatchResult,
    PlaygroundTemplateCreate, PlaygroundTemplateOut,
)

router = APIRouter(prefix="/api/playground", tags=["playground"])

TEMPLATES_BUILTIN = [
    {"name": "Basic Chat", "description": "Simple user message", "system_prompt": "", "messages": [{"role": "user", "content": "Hello! How are you?"}], "params": {}},
    {"name": "System + User", "description": "With system prompt", "system_prompt": "You are a helpful assistant.", "messages": [{"role": "user", "content": "What can you help me with?"}], "params": {}},
    {"name": "Chain of Thought", "description": "CoT instruction", "system_prompt": "Think step by step before answering. Show your reasoning.", "messages": [{"role": "user", "content": "If a train travels 120km in 2 hours, what is its average speed?"}], "params": {}},
    {"name": "Function Calling Test", "description": "Weather function tool", "system_prompt": "", "messages": [{"role": "user", "content": "What is the weather in San Francisco?"}], "params": {}},
    {"name": "JSON Extraction", "description": "Extract structured data", "system_prompt": "Extract information as JSON.", "messages": [{"role": "user", "content": "Extract the following: Name: John Smith, Age: 30, City: New York"}], "params": {"response_format": "json_object"}},
    {"name": "Summarization", "description": "Text summarization", "system_prompt": "You are an expert at summarizing text concisely.", "messages": [{"role": "user", "content": "Summarize the following in 2-3 sentences: Artificial intelligence is transforming every industry from healthcare to finance. Machine learning models can now diagnose diseases, predict stock prices, and generate human-like text. The pace of AI development is accelerating rapidly."}], "params": {}},
    {"name": "Multi-turn Conversation", "description": "3-turn conversation", "system_prompt": "", "messages": [{"role": "user", "content": "What is machine learning?"}, {"role": "assistant", "content": "Machine learning is a subset of AI where systems learn from data."}, {"role": "user", "content": "Can you give me a practical example?"}], "params": {}},
    {"name": "Code Generation", "description": "Python function request", "system_prompt": "You are an expert Python developer.", "messages": [{"role": "user", "content": "Write a Python function that checks if a number is prime."}], "params": {}},
    {"name": "Reasoning Problem", "description": "AIME-style math problem", "system_prompt": "Solve this step by step, showing all work.", "messages": [{"role": "user", "content": "Find the number of integers n with 1 \u2264 n \u2264 2023 such that n\u00b2 + n + 1 is divisible by 7."}], "params": {"temperature": 0.0}},
    {"name": "Instruction Following", "description": "IFEval-style prompt", "system_prompt": "", "messages": [{"role": "user", "content": "Write exactly 3 bullet points about the benefits of exercise. Each bullet must start with an emoji. Do not include any other text."}], "params": {}},
]


async def _call_endpoint(req: PlaygroundRunRequest) -> PlaygroundRunResult:
    msgs = []
    if req.system_prompt:
        msgs.append({"role": "system", "content": req.system_prompt})
    msgs.extend([m.model_dump() for m in req.messages])

    payload: dict = {
        "model": req.model_id,
        "messages": msgs,
        "temperature": req.params.temperature,
        "max_tokens": req.params.max_tokens,
        "top_p": req.params.top_p,
    }
    if req.params.stop:
        payload["stop"] = req.params.stop
    if req.params.seed is not None:
        payload["seed"] = req.params.seed
    if req.params.response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif req.params.response_format == "json_schema" and req.params.json_schema:
        try:
            payload["response_format"] = {"type": "json_schema", "json_schema": json.loads(req.params.json_schema)}
        except Exception:
            pass

    headers = {"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{req.endpoint_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        if r.status_code != 200:
            return PlaygroundRunResult(content="", error=f"HTTP {r.status_code}: {r.text[:200]}", latency_ms=latency_ms)
        data = r.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or None
        usage = data.get("usage", {})
        return PlaygroundRunResult(
            content=content,
            reasoning_content=reasoning,
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            reasoning_tokens=usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
            latency_ms=latency_ms,
        )
    except Exception as e:
        return PlaygroundRunResult(content="", error=str(e), latency_ms=round((time.monotonic() - t0) * 1000, 1))


@router.post("/run", response_model=PlaygroundRunResult)
async def playground_run(body: PlaygroundRunRequest):
    return await _call_endpoint(body)


@router.post("/run-batch", response_model=PlaygroundBatchResult)
async def playground_run_batch(body: PlaygroundRunRequest):
    results = await asyncio.gather(*[_call_endpoint(body) for _ in range(5)])
    results = list(results)

    latencies = [r.latency_ms for r in results if not r.error]
    contents = [r.content for r in results if not r.error]

    # Consistency: % of responses that match the most common response
    consistency = 0.0
    if contents:
        most_common = max(set(contents), key=contents.count)
        consistency = contents.count(most_common) / len(contents)

    completion_tokens = [r.completion_tokens for r in results if not r.error]
    token_variance = 0.0
    if len(completion_tokens) > 1:
        avg = sum(completion_tokens) / len(completion_tokens)
        token_variance = sum((t - avg) ** 2 for t in completion_tokens) / len(completion_tokens)

    return PlaygroundBatchResult(
        results=results,
        consistency_score=round(consistency, 3),
        avg_latency_ms=round(sum(latencies) / max(len(latencies), 1), 1),
        min_latency_ms=min(latencies) if latencies else 0,
        max_latency_ms=max(latencies) if latencies else 0,
        token_variance=round(token_variance, 1),
    )


@router.get("/templates", response_model=list[dict])
def list_templates(db: Database = Depends(get_db)):
    custom = list(db.playground_templates.find({}).sort("created_at", -1))
    custom_out = [{"id": str(d["_id"]), "name": d["name"], "description": d.get("description", ""),
                   "messages": d.get("messages", []), "params": d.get("params", {}),
                   "system_prompt": d.get("system_prompt", ""), "is_custom": True}
                  for d in custom]
    builtin_out = [{"id": f"builtin_{i}", **t, "is_custom": False} for i, t in enumerate(TEMPLATES_BUILTIN)]
    return builtin_out + custom_out


@router.post("/templates", response_model=PlaygroundTemplateOut, status_code=201)
def create_template(body: PlaygroundTemplateCreate, db: Database = Depends(get_db)):
    now = datetime.now(timezone.utc)
    doc = {**body.model_dump(), "created_at": now}
    result = db.playground_templates.insert_one(doc)
    d = db.playground_templates.find_one({"_id": result.inserted_id})
    return PlaygroundTemplateOut(**{**d, "id": str(d["_id"])})


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str, db: Database = Depends(get_db)):
    db.playground_templates.delete_one({"_id": oid(template_id)})

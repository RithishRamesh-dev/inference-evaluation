"""Inference Benchmarking Platform — FastAPI + MongoDB backend.

Sections:
  AUTH MIDDLEWARE
  MODELS ENDPOINTS
  BENCHMARKS ENDPOINTS
  EVALUATIONS ENDPOINTS
  NOTES ENDPOINTS
  SSE PROGRESS
  STATIC FILES
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.database import Database
from sse_starlette.sse import EventSourceResponse

from database import get_db, get_client, init_db, _id as doc_id, oid
from encryption import decrypt_api_key, encrypt_api_key
from schemas import (
    BenchmarkOut, CategoryOut,
    ConnectionTestOut,
    EvaluationCreate, EvaluationOut,
    ModelCreate, ModelOut, ModelUpdate,
    NoteCreate, NoteOut, NoteUpdate,
    RunBenchmarkOut, SampleOutputOut,
)
from seeds import seed_benchmarks
from worker import cancel_run, progress_store, submit_evaluation

API_KEY = os.getenv("API_KEY", "dev-key")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        seed_benchmarks(get_db())
        print("[startup] Database ready.")
    except Exception as e:
        print(f"[startup] WARNING: DB init failed ({e}). Will retry on first request.")
    yield


app = FastAPI(title="Inference Bench", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ── AUTH MIDDLEWARE ───────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/health", "/docs", "/redoc", "/openapi.json") or path.startswith("/static"):
        return await call_next(request)
    if path.endswith("/stream"):
        if request.query_params.get("api_key") == API_KEY:
            return await call_next(request)
    if request.headers.get("X-API-Key") != API_KEY:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


# ── Document helpers ──────────────────────────────────────────────────────────

def _404(label: str):
    raise HTTPException(404, f"{label} not found")


def _model_out(doc: dict) -> ModelOut:
    d = doc_id(doc)
    d.pop("api_key_encrypted", None)
    return ModelOut(**d)


def _bench_out(doc: dict) -> BenchmarkOut:
    return BenchmarkOut(**doc_id(doc))


def _rb_out(rb: dict, suite: dict | None = None) -> RunBenchmarkOut:
    d = doc_id(rb)
    if suite:
        d["suite_name"]         = suite.get("name")
        d["suite_display_name"] = suite.get("display_name")
        d["suite_category"]     = suite.get("category")
    return RunBenchmarkOut(**d)


def _run_out(run: dict, db: Database) -> EvaluationOut:
    d = doc_id(run)
    model = db.models.find_one({"_id": oid(d["model_id"])})
    if model:
        d["model_name"]     = model.get("name")
        d["model_provider"] = model.get("provider")

    rbs = list(db.run_benchmarks.find({"run_id": d["id"]}))
    rb_outs = []
    for rb in rbs:
        suite = db.benchmark_suites.find_one({"_id": oid(rb["benchmark_suite_id"])})
        rb_outs.append(_rb_out(rb, suite))
    d["run_benchmarks"] = rb_outs
    return EvaluationOut(**d)


# ── HEALTH ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        get_client().admin.command("ping", serverSelectionTimeoutMS=2000)
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status, "version": "1.0"}


# ── MODELS ENDPOINTS ──────────────────────────────────────────────────────────

@app.get("/api/models", response_model=list[ModelOut])
def list_models(
    search: Optional[str] = None,
    provider: Optional[str] = None,
    supports_vision: Optional[bool] = None,
    supports_reasoning: Optional[bool] = None,
    supports_tool_calling: Optional[bool] = None,
    db: Database = Depends(get_db),
):
    flt: dict = {}
    if search:
        flt["$or"] = [{"name": {"$regex": search, "$options": "i"}},
                      {"model_id": {"$regex": search, "$options": "i"}}]
    if provider:          flt["provider"]           = {"$regex": provider, "$options": "i"}
    if supports_vision    is not None: flt["supports_vision"]     = supports_vision
    if supports_reasoning is not None: flt["supports_reasoning"]  = supports_reasoning
    if supports_tool_calling is not None: flt["supports_tool_calling"] = supports_tool_calling
    docs = list(db.models.find(flt).sort("created_at", -1).limit(100))
    return [_model_out(d) for d in docs]


@app.get("/api/models/{model_id}", response_model=ModelOut)
def get_model(model_id: str, db: Database = Depends(get_db)):
    doc = db.models.find_one({"_id": oid(model_id)})
    if not doc: _404("Model")
    return _model_out(doc)


@app.post("/api/models", response_model=ModelOut, status_code=201)
def create_model(body: ModelCreate, db: Database = Depends(get_db)):
    doc = body.model_dump(exclude={"api_key"})
    doc["api_key_encrypted"] = encrypt_api_key(body.api_key) if body.api_key else None
    doc["created_at"] = doc["updated_at"] = datetime.now(timezone.utc)
    result = db.models.insert_one(doc)
    return _model_out(db.models.find_one({"_id": result.inserted_id}))


@app.put("/api/models/{model_id}", response_model=ModelOut)
def update_model(model_id: str, body: ModelUpdate, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}): _404("Model")
    upd = body.model_dump(exclude_none=True, exclude={"api_key"})
    if body.api_key is not None:
        upd["api_key_encrypted"] = encrypt_api_key(body.api_key)
    upd["updated_at"] = datetime.now(timezone.utc)
    db.models.update_one({"_id": oid(model_id)}, {"$set": upd})
    return _model_out(db.models.find_one({"_id": oid(model_id)}))


@app.delete("/api/models/{model_id}", status_code=204)
def delete_model(model_id: str, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}): _404("Model")
    db.models.delete_one({"_id": oid(model_id)})


@app.post("/api/models/{model_id}/test", response_model=ConnectionTestOut)
async def test_model(model_id: str, db: Database = Depends(get_db)):
    doc = db.models.find_one({"_id": oid(model_id)})
    if not doc: _404("Model")
    api_key = decrypt_api_key(doc.get("api_key_encrypted"))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        headers.update(json.loads(doc.get("custom_headers") or "{}"))
    except Exception:
        pass
    payload = {"model": doc["model_id"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{doc['endpoint_url']}/chat/completions", headers=headers, json=payload)
        return ConnectionTestOut(ok=r.status_code < 500, latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as e:
        return ConnectionTestOut(ok=False, error=str(e))


# ── BENCHMARKS ENDPOINTS ──────────────────────────────────────────────────────

@app.get("/api/benchmarks", response_model=list[BenchmarkOut])
def list_benchmarks(
    category: Optional[str] = None,
    is_recommended: Optional[bool] = None,
    search: Optional[str] = None,
    db: Database = Depends(get_db),
):
    flt: dict = {}
    if category:        flt["category"]       = category
    if is_recommended is not None: flt["is_recommended"] = is_recommended
    if search:
        flt["$or"] = [{"name":         {"$regex": search, "$options": "i"}},
                      {"display_name": {"$regex": search, "$options": "i"}},
                      {"description":  {"$regex": search, "$options": "i"}}]
    docs = list(db.benchmark_suites.find(flt).sort([("is_recommended", -1), ("name", 1)]))
    return [_bench_out(d) for d in docs]


@app.get("/api/benchmarks/categories", response_model=list[CategoryOut])
def benchmark_categories(db: Database = Depends(get_db)):
    pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}},
                {"$sort":  {"_id": 1}}]
    return [CategoryOut(category=r["_id"], count=r["count"])
            for r in db.benchmark_suites.aggregate(pipeline)]


@app.get("/api/benchmarks/recommended", response_model=list[BenchmarkOut])
def recommended_benchmarks(db: Database = Depends(get_db)):
    docs = list(db.benchmark_suites.find({"is_recommended": True}).sort("name", 1))
    return [_bench_out(d) for d in docs]


# ── EVALUATIONS ENDPOINTS ─────────────────────────────────────────────────────

@app.post("/api/evaluations", response_model=EvaluationOut, status_code=201)
def create_evaluation(body: EvaluationCreate, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(body.model_id)}):
        _404("Model")

    run_doc = body.model_dump(exclude={"benchmark_ids"})
    run_doc.update({"status": "queued", "total_benchmarks": len(body.benchmark_ids),
                    "passed_benchmarks": 0, "overall_score": None,
                    "started_at": None, "completed_at": None, "wall_time_seconds": None,
                    "created_at": datetime.now(timezone.utc)})
    run_id = str(db.evaluation_runs.insert_one(run_doc).inserted_id)

    for bid in body.benchmark_ids:
        if not db.benchmark_suites.find_one({"_id": oid(bid)}):
            db.evaluation_runs.delete_one({"_id": oid(run_id)})
            raise HTTPException(404, f"Benchmark {bid} not found")
        db.run_benchmarks.insert_one({
            "run_id": run_id, "benchmark_suite_id": bid,
            "status": "pending", "primary_score": None,
            "subset_scores": "{}", "started_at": None, "completed_at": None,
        })

    return _run_out(db.evaluation_runs.find_one({"_id": oid(run_id)}), db)


@app.post("/api/evaluations/{run_id}/start", response_model=EvaluationOut)
def start_evaluation(run_id: str, db: Database = Depends(get_db)):
    run = db.evaluation_runs.find_one({"_id": oid(run_id)})
    if not run: _404("Evaluation")
    if run["status"] not in ("queued", "failed"):
        raise HTTPException(409, f"Cannot start run in status '{run['status']}'")
    submit_evaluation(run_id)
    db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "running"}})
    return _run_out(db.evaluation_runs.find_one({"_id": oid(run_id)}), db)


@app.post("/api/evaluations/{run_id}/cancel", response_model=dict)
def cancel_evaluation(run_id: str, db: Database = Depends(get_db)):
    if not db.evaluation_runs.find_one({"_id": oid(run_id)}): _404("Evaluation")
    cancel_run(run_id)
    return {"cancelled": True}


@app.get("/api/evaluations", response_model=list[EvaluationOut])
def list_evaluations(
    status: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = 0,
    db: Database = Depends(get_db),
):
    flt: dict = {}
    if status: flt["status"] = status
    runs = list(db.evaluation_runs.find(flt).sort("created_at", -1).skip(offset).limit(limit))
    return [_run_out(r, db) for r in runs]


@app.get("/api/evaluations/compare", response_model=list[EvaluationOut])
def compare_evaluations(
    ids: str = Query(..., description="Comma-separated run IDs"),
    db: Database = Depends(get_db),
):
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if len(id_list) > 4: raise HTTPException(400, "Maximum 4 runs")
    oids = [oid(i) for i in id_list]
    runs = list(db.evaluation_runs.find({"_id": {"$in": oids}}))
    return [_run_out(r, db) for r in runs]


@app.get("/api/evaluations/{run_id}", response_model=EvaluationOut)
def get_evaluation(run_id: str, db: Database = Depends(get_db)):
    run = db.evaluation_runs.find_one({"_id": oid(run_id)})
    if not run: _404("Evaluation")
    return _run_out(run, db)


@app.get("/api/evaluations/{run_id}/results", response_model=EvaluationOut)
def get_results(run_id: str, db: Database = Depends(get_db)):
    run = db.evaluation_runs.find_one({"_id": oid(run_id)})
    if not run: _404("Evaluation")
    return _run_out(run, db)


@app.get("/api/evaluations/{run_id}/benchmarks/{rb_id}/samples",
         response_model=list[SampleOutputOut])
def get_samples(
    run_id: str, rb_id: str,
    limit: int = Query(50, le=200), offset: int = 0,
    db: Database = Depends(get_db),
):
    docs = (db.sample_outputs.find({"run_benchmark_id": rb_id})
            .sort("sample_index", 1).skip(offset).limit(limit))
    return [SampleOutputOut(**doc_id(d)) for d in docs]


# ── NOTES ENDPOINTS ───────────────────────────────────────────────────────────

@app.get("/api/evaluations/{run_id}/notes", response_model=list[NoteOut])
def list_notes(run_id: str, db: Database = Depends(get_db)):
    docs = list(db.run_notes.find({"run_id": run_id})
                .sort([("is_pinned", -1), ("created_at", -1)]))
    return [NoteOut(**doc_id(d)) for d in docs]


@app.post("/api/evaluations/{run_id}/notes", response_model=NoteOut, status_code=201)
def create_note(run_id: str, body: NoteCreate, db: Database = Depends(get_db)):
    if not db.evaluation_runs.find_one({"_id": oid(run_id)}): _404("Evaluation")
    now = datetime.now(timezone.utc)
    doc = {"run_id": run_id, "content": body.content,
           "note_type": body.note_type, "is_pinned": body.is_pinned,
           "created_at": now, "updated_at": now}
    result = db.run_notes.insert_one(doc)
    return NoteOut(**doc_id(db.run_notes.find_one({"_id": result.inserted_id})))


@app.put("/api/evaluations/{run_id}/notes/{note_id}", response_model=NoteOut)
def update_note(run_id: str, note_id: str, body: NoteUpdate, db: Database = Depends(get_db)):
    note = db.run_notes.find_one({"_id": oid(note_id), "run_id": run_id})
    if not note: _404("Note")
    upd = body.model_dump(exclude_none=True)
    upd["updated_at"] = datetime.now(timezone.utc)
    db.run_notes.update_one({"_id": oid(note_id)}, {"$set": upd})
    return NoteOut(**doc_id(db.run_notes.find_one({"_id": oid(note_id)})))


@app.delete("/api/evaluations/{run_id}/notes/{note_id}", status_code=204)
def delete_note(run_id: str, note_id: str, db: Database = Depends(get_db)):
    note = db.run_notes.find_one({"_id": oid(note_id), "run_id": run_id})
    if not note: _404("Note")
    db.run_notes.delete_one({"_id": oid(note_id)})


# ── SSE PROGRESS ──────────────────────────────────────────────────────────────

@app.get("/api/evaluations/{run_id}/stream")
async def stream_progress(run_id: str, api_key: Optional[str] = None):
    async def event_generator():
        terminal = {"completed", "failed", "cancelled"}
        while True:
            data = progress_store.get(run_id, {"status": "queued", "percent": 0})
            yield {"data": json.dumps(data)}
            if data.get("status") in terminal:
                break
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())


# ── STATIC FILES ──────────────────────────────────────────────────────────────

_static = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="static")

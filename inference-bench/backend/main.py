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
    BenchmarkOut, BenchmarkTargetOut, CategoryOut,
    ConnectionTestOut,
    EvaluationCreate, EvaluationOut,
    ModelCreate, ModelOut, ModelUpdate,
    NoteCreate, NoteOut, NoteUpdate,
    ProbeRequest,
    RegressionAlertOut,
    RunBenchmarkOut, SampleOutputOut,
    StressTestCreate, StressTestOut,
    SystemInfoOut,
    ValidationRunOut,
)
from seeds import seed_benchmarks
from worker import cancel_run, progress_store, submit_evaluation

API_KEY = os.getenv("API_KEY", "dev-key")


# ── Lifespan ──────────────────────────────────────────────────────────────────

_db_initialized = False

def _lazy_init_db():
    global _db_initialized
    if not _db_initialized:
        try:
            init_db()
            seed_benchmarks(get_db())
            _db_initialized = True
            print("[db] Lazy init complete.")
        except Exception as e:
            print(f"[db] WARNING: Lazy init failed ({e}). Will retry.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] Server ready. DB will initialize on first request.")
    yield


app = FastAPI(title="Inference Bench", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ── AUTH MIDDLEWARE ───────────────────────────────────────────────────────────

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Only API routes require authentication
    if not path.startswith("/api/"):
        return await call_next(request)
    # SSE streams accept key via query param
    if path.endswith("/stream"):
        if request.query_params.get("api_key") == API_KEY:
            _lazy_init_db()
            return await call_next(request)
    if request.headers.get("X-API-Key") != API_KEY:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    _lazy_init_db()
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
    return {"status": "ok", "version": "1.0"}


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


# ── EXPORT ENDPOINTS ──────────────────────────────────────────────────────────

@app.get("/api/evaluations/{run_id}/export")
def export_evaluation(
    run_id: str,
    format: str = Query("json", regex="^(json|csv|md|html)$"),
    db: Database = Depends(get_db),
):
    from fastapi.responses import PlainTextResponse, Response
    run = db.evaluation_runs.find_one({"_id": oid(run_id)})
    if not run: _404("Evaluation")
    ev = _run_out(run, db)

    if format == "json":
        return JSONResponse(ev.model_dump())

    if format == "csv":
        rows = ["benchmark,status,score,samples_total,samples_scored,avg_latency_s"]
        for rb in ev.run_benchmarks:
            rows.append(f"{rb.suite_name},{rb.status},{rb.primary_score or ''},"
                        f"{rb.samples_total or ''},{rb.samples_scored or ''},"
                        f"{rb.avg_latency_s or ''}")
        return PlainTextResponse("\n".join(rows), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="run_{run_id}.csv"'})

    if format == "md":
        lines = [
            f"# Evaluation Report: {ev.display_name or run_id}",
            f"",
            f"| Field | Value |",
            f"|---|---|",
            f"| Model | {ev.model_name} ({ev.model_provider}) |",
            f"| Status | {ev.status} |",
            f"| Overall Score | {f'{ev.overall_score*100:.1f}%' if ev.overall_score is not None else '—'} |",
            f"| Benchmarks | {ev.passed_benchmarks}/{ev.total_benchmarks} passed |",
            f"| Wall Time | {ev.wall_time_seconds}s |",
            f"",
            f"## Benchmark Results",
            f"",
            f"| Benchmark | Category | Score | Samples | Avg Latency |",
            f"|---|---|---|---|---|",
        ]
        for rb in ev.run_benchmarks:
            score_str = f"{rb.primary_score*100:.1f}%" if rb.primary_score is not None else "—"
            lines.append(f"| {rb.suite_display_name or rb.suite_name} | {rb.suite_category or ''} | "
                         f"{score_str} | {rb.samples_scored or '—'}/{rb.samples_total or '—'} | "
                         f"{f'{rb.avg_latency_s:.2f}s' if rb.avg_latency_s else '—'} |")
        return PlainTextResponse("\n".join(lines), media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="run_{run_id}.md"'})

    if format == "html":
        benchmarks_json = json.dumps([
            {"name": rb.suite_display_name or rb.suite_name,
             "score": round((rb.primary_score or 0) * 100, 1),
             "category": rb.suite_category or ""}
            for rb in ev.run_benchmarks if rb.primary_score is not None
        ])
        rows_html = "\n".join(
            f"<tr><td>{rb.suite_display_name or rb.suite_name}</td>"
            f"<td>{rb.suite_category or ''}</td>"
            f"<td class='score'>{f'{rb.primary_score*100:.1f}%' if rb.primary_score is not None else '—'}</td>"
            f"<td>{rb.samples_scored or '—'}/{rb.samples_total or '—'}</td>"
            f"<td>{f'{rb.avg_latency_s:.2f}s' if rb.avg_latency_s else '—'}</td></tr>"
            for rb in ev.run_benchmarks
        )
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Eval Report — {ev.display_name or run_id}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:2rem}}
h1{{color:#38bdf8}} table{{width:100%;border-collapse:collapse;margin:1rem 0}}
th,td{{padding:.5rem 1rem;text-align:left;border-bottom:1px solid #1e293b}}
th{{color:#94a3b8;font-size:.75rem;text-transform:uppercase}}
.score{{font-weight:700;color:#4ade80}} .summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin:1.5rem 0}}
.stat{{background:#1e293b;padding:1rem;border-radius:.5rem;text-align:center}}
.stat .val{{font-size:1.5rem;font-weight:700;color:#38bdf8}} .stat .lbl{{font-size:.75rem;color:#64748b}}
canvas{{max-height:300px}}
</style></head><body>
<h1>Evaluation Report</h1>
<p style="color:#64748b">{ev.display_name or run_id} · {ev.model_name} · {ev.created_at}</p>
<div class="summary">
  <div class="stat"><div class="val">{f'{ev.overall_score*100:.1f}%' if ev.overall_score is not None else '—'}</div><div class="lbl">Overall Score</div></div>
  <div class="stat"><div class="val">{ev.passed_benchmarks}/{ev.total_benchmarks}</div><div class="lbl">Benchmarks Passed</div></div>
  <div class="stat"><div class="val">{ev.status}</div><div class="lbl">Status</div></div>
  <div class="stat"><div class="val">{ev.wall_time_seconds or '—'}s</div><div class="lbl">Wall Time</div></div>
</div>
<canvas id="chart"></canvas>
<h2>Benchmark Results</h2>
<table><thead><tr><th>Benchmark</th><th>Category</th><th>Score</th><th>Samples</th><th>Avg Latency</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<script>
const data = {benchmarks_json};
new Chart(document.getElementById('chart'), {{
  type: 'bar',
  data: {{
    labels: data.map(d => d.name),
    datasets: [{{label: 'Score %', data: data.map(d => d.score),
      backgroundColor: '#38bdf8', borderRadius: 4}}]
  }},
  options: {{responsive:true, scales: {{y: {{max:100, ticks:{{color:'#94a3b8'}}}}, x: {{ticks:{{color:'#94a3b8'}}}}}}}}
}});
</script></body></html>"""
        return Response(html, media_type="text/html",
                        headers={"Content-Disposition": f'attachment; filename="run_{run_id}.html"'})


# ── EVALUATION RESUME ──────────────────────────────────────────────────────────

@app.post("/api/evaluations/{run_id}/resume", response_model=EvaluationOut)
def resume_evaluation(run_id: str, db: Database = Depends(get_db)):
    run = db.evaluation_runs.find_one({"_id": oid(run_id)})
    if not run: _404("Evaluation")
    if run["status"] not in ("failed", "cancelled"):
        raise HTTPException(409, f"Can only resume failed or cancelled runs")
    # Reset pending/failed run_benchmarks back to pending
    db.run_benchmarks.update_many(
        {"run_id": run_id, "status": {"$in": ["pending", "failed"]}},
        {"$set": {"status": "pending", "error_message": None}}
    )
    db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "queued"}})
    submit_evaluation(run_id)
    db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "running"}})
    return _run_out(db.evaluation_runs.find_one({"_id": oid(run_id)}), db)


# ── VALIDATION ENDPOINTS ──────────────────────────────────────────────────────

def _vrun_out(doc: dict, db: Database, include_checks: bool = True) -> ValidationRunOut:
    d = doc_id(doc)
    model = db.models.find_one({"_id": oid(d["model_id"])}) if d.get("model_id") else None
    d["model_name"] = model.get("name") if model else None
    if not include_checks:
        d["checks"] = []
    return ValidationRunOut(**d)


@app.post("/api/models/{model_id}/validate", response_model=ValidationRunOut)
async def run_validation(model_id: str, db: Database = Depends(get_db)):
    from validation import run_validation_suite
    doc = db.models.find_one({"_id": oid(model_id)})
    if not doc: _404("Model")
    api_key = decrypt_api_key(doc.get("api_key_encrypted"))
    model = doc_id(doc)

    now = datetime.now(timezone.utc)
    vrun = {
        "model_id": model_id,
        "status": "running",
        "total_checks": 0, "passed": 0, "warned": 0, "failed": 0, "skipped": 0,
        "checks": [],
        "created_at": now,
        "completed_at": None,
        "duration_ms": None,
    }
    vrun_id = str(db.validation_runs.insert_one(vrun).inserted_id)

    t0 = time.monotonic()
    try:
        checks = await run_validation_suite(model, api_key)
    except Exception as e:
        checks = [{"check_id": "suite_error", "name": "Suite Error", "category": "connectivity",
                   "status": "fail", "latency_ms": 0, "detail": {"error": str(e)}, "message": str(e)}]

    ms = (time.monotonic() - t0) * 1000
    summary = {"passed": 0, "warned": 0, "failed": 0, "skipped": 0}
    for c in checks:
        s = c.get("status", "fail")
        if s == "pass":    summary["passed"]  += 1
        elif s == "warn":  summary["warned"]  += 1
        elif s == "skip":  summary["skipped"] += 1
        else:              summary["failed"]  += 1

    db.validation_runs.update_one(
        {"_id": oid(vrun_id)},
        {"$set": {
            "status": "completed",
            "total_checks": len(checks),
            **summary,
            "checks": checks,
            "completed_at": datetime.now(timezone.utc),
            "duration_ms": round(ms, 1),
        }}
    )
    return _vrun_out(db.validation_runs.find_one({"_id": oid(vrun_id)}), db)


@app.get("/api/models/{model_id}/validate/history", response_model=list[ValidationRunOut])
def validation_history(model_id: str, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}): _404("Model")
    docs = list(db.validation_runs.find({"model_id": model_id})
                .sort("created_at", -1).limit(10))
    return [_vrun_out(d, db, include_checks=False) for d in docs]


@app.get("/api/models/{model_id}/validate/latest", response_model=ValidationRunOut)
def validation_latest(model_id: str, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}): _404("Model")
    doc = db.validation_runs.find_one({"model_id": model_id}, sort=[("created_at", -1)])
    if not doc: raise HTTPException(404, "No validation runs yet")
    return _vrun_out(doc, db)


@app.get("/api/models/{model_id}/validate/curl")
def validation_curl_script(model_id: str, db: Database = Depends(get_db)):
    from fastapi.responses import PlainTextResponse
    from validation import generate_curl_script
    doc = db.models.find_one({"_id": oid(model_id)})
    if not doc: _404("Model")
    script = generate_curl_script(doc["endpoint_url"], doc["model_id"])
    return PlainTextResponse(script, media_type="text/x-shellscript",
                             headers={"Content-Disposition": "attachment; filename=validate.sh"})


# ── PROBE ENDPOINT (no stored model required) ─────────────────────────────────

@app.post("/api/probe", response_model=list[dict])
async def probe_endpoint(body: ProbeRequest):
    from validation import run_validation_suite
    model = {
        "endpoint_url": body.endpoint_url,
        "model_id": body.model_id,
        "supports_vision": False,
        "supports_reasoning": False,
        "reasoning_format": None,
        "reasoning_enable_param": None,
        "reasoning_disable_param": None,
        "custom_headers": "{}",
    }
    checks = await run_validation_suite(model, body.api_key)
    if body.checks:
        checks = [c for c in checks if c["check_id"] in body.checks]
    return checks


# ── STRESS TEST ENDPOINTS ─────────────────────────────────────────────────────

async def _run_stress_level(base_url: str, model_id: str, headers: dict,
                             concurrency: int, n_requests: int, output_tokens: int) -> dict:
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content":
                      "Write a detailed paragraph about machine learning. Be thorough and comprehensive."}],
        "max_tokens": output_tokens,
    }
    latencies: list[float] = []
    ttfts: list[float] = []
    total_output_tokens = 0
    failed = 0
    timeout_count = 0

    async def single_req():
        nonlocal total_output_tokens, failed, timeout_count
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=60, headers=headers) as c:
                async with c.stream("POST", f"{base_url}/chat/completions",
                                    json={**payload, "stream": True}) as r:
                    if r.status_code != 200:
                        failed += 1
                        return
                    first_token = False
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "): continue
                        data = line[6:]
                        if data.strip() == "[DONE]": break
                        try:
                            j = json.loads(data)
                            delta = j["choices"][0].get("delta", {})
                            if delta.get("content") and not first_token:
                                ttfts.append((time.monotonic() - t0) * 1000)
                                first_token = True
                            if j.get("usage"):
                                total_output_tokens += j["usage"].get("completion_tokens", 0) or 0
                        except Exception:
                            pass
            elapsed = (time.monotonic() - t0) * 1000
            latencies.append(elapsed)
        except httpx.TimeoutException:
            timeout_count += 1
            failed += 1
        except Exception:
            failed += 1

    # Run in batches of concurrency
    tasks = [single_req() for _ in range(n_requests)]
    for i in range(0, len(tasks), concurrency):
        batch = tasks[i:i + concurrency]
        await asyncio.gather(*batch)

    latencies.sort()
    n = len(latencies)

    def pct(p: float) -> float:
        if not latencies: return 0.0
        idx = min(int(len(latencies) * p / 100), len(latencies) - 1)
        return round(latencies[idx], 1)

    wall_s = sum(latencies) / 1000 / max(concurrency, 1) if latencies else 1
    rps = n / max(wall_s, 0.001)
    tps = total_output_tokens / max(sum(l / 1000 for l in latencies), 0.001)

    return {
        "concurrency": concurrency,
        "requests_total": n_requests,
        "requests_succeeded": n,
        "requests_failed": failed,
        "avg_latency_ms": round(sum(latencies) / max(n, 1), 1),
        "p50_latency_ms": pct(50),
        "p90_latency_ms": pct(90),
        "p95_latency_ms": pct(95),
        "p99_latency_ms": pct(99),
        "ttft_ms_avg": round(sum(ttfts) / max(len(ttfts), 1), 1) if ttfts else None,
        "throughput_requests_per_second": round(rps, 2),
        "throughput_tokens_per_second": round(tps, 1),
        "total_output_tokens": total_output_tokens,
        "error_rate": round(failed / max(n_requests, 1), 4),
        "timeout_rate": round(timeout_count / max(n_requests, 1), 4),
    }


@app.post("/api/models/{model_id}/stress-test")
async def create_stress_test(model_id: str, body: StressTestCreate, db: Database = Depends(get_db)):
    doc = db.models.find_one({"_id": oid(model_id)})
    if not doc: _404("Model")
    api_key = decrypt_api_key(doc.get("api_key_encrypted"))
    try:
        ch = json.loads(doc.get("custom_headers") or "{}")
    except Exception:
        ch = {}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **ch}
    base_url = doc["endpoint_url"].rstrip("/")

    now = datetime.now(timezone.utc)
    test_doc = {"model_id": model_id, "status": "running", "config": body.model_dump(),
                "results": [], "created_at": now, "completed_at": None}
    test_id = str(db.stress_test_runs.insert_one(test_doc).inserted_id)

    results = []
    for conc in body.concurrency_levels:
        try:
            lvl = await _run_stress_level(base_url, doc["model_id"], headers,
                                          conc, body.requests_per_level, body.output_tokens)
            results.append(lvl)
        except Exception as e:
            results.append({"concurrency": conc, "error": str(e)})

    db.stress_test_runs.update_one(
        {"_id": oid(test_id)},
        {"$set": {"status": "completed", "results": results, "completed_at": datetime.now(timezone.utc)}}
    )
    return {"test_id": test_id}


@app.get("/api/models/{model_id}/stress-test/{test_id}", response_model=StressTestOut)
def get_stress_test(model_id: str, test_id: str, db: Database = Depends(get_db)):
    doc = db.stress_test_runs.find_one({"_id": oid(test_id), "model_id": model_id})
    if not doc: _404("StressTest")
    d = doc_id(doc)
    model = db.models.find_one({"_id": oid(model_id)})
    d["model_name"] = model.get("name") if model else None
    return StressTestOut(**d)


@app.get("/api/models/{model_id}/stress-tests")
def list_stress_tests(model_id: str, db: Database = Depends(get_db)):
    if not db.models.find_one({"_id": oid(model_id)}): _404("Model")
    docs = list(db.stress_test_runs.find({"model_id": model_id}).sort("created_at", -1).limit(20))
    return [doc_id(d) for d in docs]


# ── BENCHMARK TARGETS ─────────────────────────────────────────────────────────

@app.get("/api/benchmarks/{benchmark_id}/targets", response_model=list[BenchmarkTargetOut])
def benchmark_targets(benchmark_id: str, db: Database = Depends(get_db)):
    if not db.benchmark_suites.find_one({"_id": oid(benchmark_id)}): _404("Benchmark")
    docs = list(db.benchmark_targets.find({"benchmark_suite_id": benchmark_id}))
    return [BenchmarkTargetOut(**doc_id(d)) for d in docs]


# ── REGRESSION ALERTS ─────────────────────────────────────────────────────────

@app.get("/api/regression-alerts", response_model=list[RegressionAlertOut])
def list_regression_alerts(
    acknowledged: Optional[bool] = None,
    db: Database = Depends(get_db)
):
    flt: dict = {}
    if acknowledged is not None:
        flt["acknowledged"] = acknowledged
    docs = list(db.regression_alerts.find(flt).sort("created_at", -1).limit(50))
    result = []
    for d in docs:
        rd = doc_id(d)
        suite = db.benchmark_suites.find_one({"_id": oid(rd["benchmark_suite_id"])}) if rd.get("benchmark_suite_id") else None
        rd["benchmark_name"] = suite.get("display_name") if suite else None
        result.append(RegressionAlertOut(**rd))
    return result


@app.post("/api/regression-alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, db: Database = Depends(get_db)):
    doc = db.regression_alerts.find_one({"_id": oid(alert_id)})
    if not doc: _404("RegressionAlert")
    db.regression_alerts.update_one({"_id": oid(alert_id)}, {"$set": {"acknowledged": True}})
    return {"acknowledged": True}


# ── SYSTEM INFO ────────────────────────────────────────────────────────────────

@app.get("/api/system/info", response_model=SystemInfoOut)
def system_info(db: Database = Depends(get_db)):
    import sys
    evalscope_available = False
    try:
        import evalscope  # noqa: F401
        evalscope_available = True
    except ImportError:
        pass
    return SystemInfoOut(
        python_version=sys.version.split()[0],
        benchmarks_seeded=db.benchmark_suites.count_documents({}),
        total_runs=db.evaluation_runs.count_documents({}),
        total_models=db.models.count_documents({}),
        evalscope_available=evalscope_available,
    )


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

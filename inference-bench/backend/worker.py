"""EvalScope runner — ThreadPoolExecutor + MongoDB (pymongo, thread-safe).

progress_store and cancel_flags are shared in-process with main.py.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from typing import Any

from bson import ObjectId
from database import get_db, oid
from encryption import decrypt_api_key

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=4)

progress_store: dict[str, dict] = {}
cancel_flags:   dict[str, Event] = {}


# ── Public API ─────────────────────────────────────────────────────────────────

def submit_evaluation(run_id: str) -> None:
    cancel_flags[run_id] = Event()
    progress_store[run_id] = {
        "status": "queued", "percent": 0,
        "current_benchmark": None,
        "samples_done": 0, "samples_total": 0,
        "eta_seconds": None, "elapsed_seconds": 0,
        "events": [],
    }
    executor.submit(_run_evaluation, run_id)


def cancel_run(run_id: str) -> None:
    flag = cancel_flags.get(run_id)
    if flag:
        flag.set()


# ── Internals ─────────────────────────────────────────────────────────────────

def _upd(run_id: str, **kw: Any) -> None:
    progress_store.setdefault(run_id, {}).update(kw)


def _evt(run_id: str, event: str, **data: Any) -> None:
    entry = {"event": event, "ts": datetime.utcnow().isoformat(), **data}
    store = progress_store.setdefault(run_id, {"events": []})
    store.setdefault("events", []).append(entry)
    store["events"] = store["events"][-200:]


def _cancelled(run_id: str) -> bool:
    return cancel_flags.get(run_id, Event()).is_set()


def _run_evaluation(run_id: str) -> None:
    db   = get_db()
    t0   = time.monotonic()
    key  = run_id

    try:
        run = db.evaluation_runs.find_one({"_id": oid(run_id)})
        if not run:
            logger.error(f"Run {run_id} not found")
            return

        db.evaluation_runs.update_one(
            {"_id": oid(run_id)},
            {"$set": {"status": "running", "started_at": datetime.now(timezone.utc)}},
        )
        _upd(key, status="running", percent=0)

        model = db.models.find_one({"_id": oid(str(run["model_id"]))})
        api_key = decrypt_api_key(model.get("api_key_encrypted")) if model else ""

        run_benchmarks = list(db.run_benchmarks.find({"run_id": run_id}))
        total = len(run_benchmarks)
        scores: list[float] = []

        for idx, rb in enumerate(run_benchmarks):
            rb_id = str(rb["_id"])
            if _cancelled(key):
                db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "cancelled"}})
                _upd(key, status="cancelled")
                return

            suite = db.benchmark_suites.find_one({"_id": oid(str(rb["benchmark_suite_id"]))})
            db.run_benchmarks.update_one(
                {"_id": oid(rb_id)},
                {"$set": {"status": "running", "started_at": datetime.now(timezone.utc)}},
            )
            _upd(key, current_benchmark=suite.get("display_name"), samples_done=0,
                 samples_total=run.get("sample_count") or suite.get("total_samples") or 0)
            _evt(key, "benchmark_start", benchmark=suite.get("name"), index=idx, total=total)

            try:
                score, metrics, samples = _run_single(run, rb, suite, model, api_key, key)

                db.run_benchmarks.update_one(
                    {"_id": oid(rb_id)},
                    {"$set": {
                        "status":           "completed",
                        "primary_score":    score,
                        "completed_at":     datetime.now(timezone.utc),
                        "samples_total":    metrics.get("samples_total"),
                        "samples_scored":   metrics.get("samples_scored"),
                        "samples_errored":  metrics.get("samples_errored", 0),
                        "avg_latency_s":    metrics.get("avg_latency_s"),
                        "avg_input_tokens": metrics.get("avg_input_tokens"),
                        "avg_output_tokens":metrics.get("avg_output_tokens"),
                        "subset_scores":    json.dumps(metrics.get("subset_scores", {})),
                    }},
                )

                if samples:
                    db.sample_outputs.insert_many(
                        [{**s, "run_benchmark_id": rb_id} for s in samples]
                    )

                if score is not None:
                    scores.append(score)

                _upd(key, percent=int((idx + 1) / total * 100), elapsed_seconds=int(time.monotonic() - t0))
                _evt(key, "benchmark_complete", benchmark=suite.get("name"), score=score)

            except Exception as exc:
                logger.exception(f"Benchmark {suite.get('name')} failed")
                db.run_benchmarks.update_one(
                    {"_id": oid(rb_id)},
                    {"$set": {"status": "failed", "error_message": str(exc),
                              "completed_at": datetime.now(timezone.utc)}},
                )
                _evt(key, "benchmark_failed", benchmark=suite.get("name"), error=str(exc))

        overall = sum(scores) / len(scores) if scores else None
        wall    = int(time.monotonic() - t0)
        passed  = sum(1 for rb in run_benchmarks
                      if db.run_benchmarks.find_one({"_id": rb["_id"], "status": "completed"}))

        db.evaluation_runs.update_one(
            {"_id": oid(run_id)},
            {"$set": {
                "status":           "completed",
                "overall_score":    overall,
                "passed_benchmarks": passed,
                "completed_at":     datetime.now(timezone.utc),
                "wall_time_seconds": wall,
            }},
        )
        _upd(key, status="completed", percent=100, overall_score=overall)
        _evt(key, "run_complete", overall_score=overall)

    except Exception as exc:
        logger.exception(f"Run {run_id} crashed")
        try:
            db.evaluation_runs.update_one({"_id": oid(run_id)}, {"$set": {"status": "failed"}})
        except Exception:
            pass
        _upd(key, status="failed")
        _evt(key, "run_failed", error=str(exc))
    finally:
        cancel_flags.pop(key, None)


def _run_single(run, rb, suite, model, api_key, progress_key) -> tuple[float | None, dict, list]:
    try:
        from evalscope import TaskConfig, run_task  # noqa: F401
        return _evalscope_run(run, rb, suite, model, api_key, progress_key)
    except ImportError:
        logger.warning("evalscope not installed — mock runner")
        return _mock_run(run, rb, suite, progress_key)


def _build_task_config(run, rb, suite, model, api_key) -> Any:
    from evalscope import TaskConfig

    gen: dict = {}
    if run.get("thinking_mode") and model and model.get("reasoning_format"):
        fmt     = model["reasoning_format"]
        enabled = run["thinking_mode"] == "enabled"
        if fmt == "chat_template_kwargs":
            gen["extra_body"] = {"chat_template_kwargs": {"enable_thinking": enabled}}
        elif fmt == "thinking_type":
            gen["extra_body"] = {"thinking": {"type": run["thinking_mode"]}}

    if run.get("temperature") is not None:
        gen["temperature"] = run["temperature"]
    if run.get("max_tokens"):
        gen["max_tokens"] = run["max_tokens"]
    gen["timeout"] = run.get("timeout_seconds") or 120

    return TaskConfig(
        model          = model["model_id"] if model else "",
        api_url        = model["endpoint_url"] if model else "",
        api_key        = api_key,
        datasets       = [suite["evalscope_id"]],
        dataset_args   = json.loads(suite.get("evalscope_config") or "{}"),
        generation_config = gen,
        eval_batch_size= run.get("eval_batch_size") or 8,
        limit          = run.get("sample_count"),
        ignore_errors  = True,
        dataset_hub    = "modelscope",
        work_dir       = f"./evalscope_outputs/{run.get('_id', 'unknown')}/{suite['name']}",
    )


def _evalscope_run(run, rb, suite, model, api_key, progress_key):
    from evalscope import run_task
    cfg    = _build_task_config(run, rb, suite, model, api_key)
    result = run_task(cfg)
    try:
        scores_data = getattr(result, "scores", {}) or {}
        primary     = (scores_data.get(suite["default_metric"]) or
                       scores_data.get("acc") if hasattr(scores_data, "get") else None)
        return primary, {
            "samples_total":     getattr(result, "total_samples", None),
            "samples_scored":    getattr(result, "scored_samples", None),
            "samples_errored":   getattr(result, "error_samples", 0),
            "avg_latency_s":     getattr(result, "avg_latency", None),
            "avg_input_tokens":  getattr(result, "avg_input_tokens", None),
            "avg_output_tokens": getattr(result, "avg_output_tokens", None),
            "subset_scores":     getattr(result, "subset_scores", {}),
        }, []
    except Exception as e:
        logger.warning(f"Could not parse evalscope result: {e}")
        return None, {}, []


def _mock_run(run, rb, suite, progress_key) -> tuple[float | None, dict, list]:
    import hashlib, random
    seed = int(hashlib.md5(f"{rb.get('run_id','')}-{suite['name']}".encode()).hexdigest(), 16) % 10000
    rng  = random.Random(seed)
    n    = run.get("sample_count") or min(suite.get("total_samples") or 30, 30)
    samples = []
    for i in range(n):
        if _cancelled(progress_key):
            break
        correct = rng.random() > 0.35
        lat     = round(rng.uniform(0.4, 4.5), 2)
        samples.append({
            "sample_index":   i,
            "question":       f"[Mock] Sample #{i + 1} — {suite['display_name']}",
            "expected_answer":"A",
            "model_output":   "A" if correct else "B",
            "is_correct":     correct,
            "score":          1.0 if correct else 0.0,
            "latency_s":      lat,
            "input_tokens":   rng.randint(100, 600),
            "output_tokens":  rng.randint(50, 2000),
        })
        time.sleep(0.05)
        _upd(progress_key, samples_done=i + 1, samples_total=n)

    score   = round(sum(1 for s in samples if s["is_correct"]) / len(samples), 4) if samples else None
    metrics = {
        "samples_total":     n,
        "samples_scored":    len(samples),
        "samples_errored":   0,
        "avg_latency_s":     round(sum(s["latency_s"] for s in samples) / max(len(samples), 1), 2),
        "avg_input_tokens":  round(sum(s["input_tokens"] for s in samples) / max(len(samples), 1)),
        "avg_output_tokens": round(sum(s["output_tokens"] for s in samples) / max(len(samples), 1)),
        "subset_scores":     {},
    }
    return score, metrics, samples

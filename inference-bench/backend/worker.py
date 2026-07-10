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
        import evalscope  # noqa: F401  # type: ignore  # optional heavy dep; falls back to mock
        return _evalscope_run(run, rb, suite, model, api_key, progress_key)
    except ImportError:
        logger.warning("evalscope not installed — mock runner")
        return _mock_run(run, rb, suite, progress_key)


def _build_task_config(run, rb, suite, model, api_key) -> Any:
    from evalscope import TaskConfig  # type: ignore  # optional heavy dep

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
    from evalscope import run_task  # type: ignore  # optional heavy dep
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


# ── SCHEDULER THREAD ──────────────────────────────────────────────────────────

import threading as _threading

def _scheduler_loop() -> None:
    """Check for due scheduled evaluations every 60 seconds."""
    import time as _time
    while True:
        try:
            _run_due_schedules()
        except Exception as e:
            print(f"[scheduler] Error: {e}")
        _time.sleep(60)


def _run_due_schedules() -> None:
    from database import get_db as _get_db
    from datetime import datetime, timezone as _tz
    db = _get_db()
    now = datetime.now(_tz.utc)
    due = list(db.scheduled_evaluations.find({
        "enabled": True,
        "next_run_at": {"$lte": now},
    }))
    for sched in due:
        try:
            _trigger_scheduled_eval(sched, db, now)
        except Exception as e:
            print(f"[scheduler] Failed to trigger schedule {sched['_id']}: {e}")


def _trigger_scheduled_eval(sched: dict, db, now) -> None:
    from bson import ObjectId
    from datetime import datetime, timezone as _tz
    mid = sched.get("model_id", "")
    benchmark_ids = sched.get("benchmark_ids", [])
    eval_config = sched.get("eval_config", {})

    run_doc = {
        "model_id": mid,
        "display_name": f"Scheduled run {now.strftime('%Y-%m-%d %H:%M')}",
        "status": "queued",
        "total_benchmarks": len(benchmark_ids),
        "passed_benchmarks": 0,
        "overall_score": None,
        "started_at": None,
        "completed_at": None,
        "wall_time_seconds": None,
        "created_at": now,
        **eval_config,
    }
    run_id = str(db.evaluation_runs.insert_one(run_doc).inserted_id)
    for bid in benchmark_ids:
        db.run_benchmarks.insert_one({
            "run_id": run_id, "benchmark_suite_id": bid,
            "status": "pending", "primary_score": None, "subset_scores": "{}",
            "started_at": None, "completed_at": None,
        })
    submit_evaluation(run_id)
    db.evaluation_runs.update_one({"_id": ObjectId(run_id)}, {"$set": {"status": "running"}})

    # Update schedule next_run_at
    try:
        from croniter import croniter
        c = croniter(sched["schedule_cron"], now)
        next_run = c.get_next(datetime)
    except Exception:
        next_run = None

    db.scheduled_evaluations.update_one(
        {"_id": sched["_id"]},
        {"$set": {"last_run_at": now, "next_run_at": next_run}}
    )
    print(f"[scheduler] Triggered scheduled eval run_id={run_id}")


def _monitor_loop() -> None:
    """Check for due monitor runs every 60 seconds."""
    import time as _time
    while True:
        try:
            _run_due_monitors()
        except Exception as e:
            print(f"[monitor] Error: {e}")
        _time.sleep(60)


def _run_due_monitors() -> None:
    import asyncio
    from database import get_db as _get_db
    from datetime import datetime, timezone as _tz, timedelta as _td
    db = _get_db()
    now = datetime.now(_tz.utc)
    monitors = list(db.monitor_configs.find({"enabled": True}))
    for mon in monitors:
        mid = str(mon["_id"])
        interval_min = mon.get("check_interval_minutes", 15)
        # Check if due (last result was more than interval ago)
        last = db.monitor_results.find_one({"monitor_config_id": mid}, sort=[("run_at", -1)])
        if last:
            elapsed = (now - last["run_at"]).total_seconds() / 60
            if elapsed < interval_min:
                continue
        # Run the checks
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_run_monitor_check(mon, mid, db, now))
            loop.close()
            db.monitor_results.insert_one(result)
        except Exception as e:
            print(f"[monitor] Check failed for {mid}: {e}")


async def _run_monitor_check(mon: dict, mid: str, db, now) -> dict:
    import httpx
    from database import get_db as _get_db, oid as _oid
    from encryption import decrypt_api_key as _decrypt
    from datetime import timezone as _tz

    model_id = mon.get("model_id", "")
    model = db.models.find_one({"_id": _oid(model_id)}) if model_id else None
    if not model:
        return {"monitor_config_id": mid, "run_at": now, "checks_passed": 0, "checks_failed": 1, "avg_latency_ms": None, "status": "down", "created_at": now}

    api_key = _decrypt(model.get("api_key_encrypted"))
    checks_to_run = mon.get("checks_to_run", ["connectivity", "basic_completion"])

    from validation import run_validation_suite
    model_doc = {"endpoint_url": model["endpoint_url"], "model_id": model["model_id"],
                 "supports_vision": False, "supports_reasoning": False,
                 "reasoning_format": None, "reasoning_enable_param": None,
                 "reasoning_disable_param": None, "custom_headers": "{}"}
    checks = await run_validation_suite(model_doc, api_key)
    checks = [c for c in checks if c["check_id"] in checks_to_run]

    passed = sum(1 for c in checks if c.get("status") == "pass")
    failed = sum(1 for c in checks if c.get("status") == "fail")
    latencies = [c.get("latency_ms", 0) for c in checks if c.get("latency_ms")]
    avg_lat = round(sum(latencies) / max(len(latencies), 1), 1) if latencies else None

    if failed == 0:
        status = "healthy"
    elif passed == 0:
        status = "down"
    else:
        status = "degraded"

    return {
        "monitor_config_id": mid,
        "run_at": now,
        "checks_passed": passed,
        "checks_failed": failed,
        "avg_latency_ms": avg_lat,
        "status": status,
        "created_at": now,
    }


# ── DROPLET RECONCILE THREAD ──────────────────────────────────────────────────

def _reconcile_loop() -> None:
    """Self-heal GPU droplets/deployments/benchmarks every 90s: detect droplets
    destroyed out-of-band, recover ones stuck after a failed destroy, and cascade
    those states onto orphaned deployments/benchmarks — so nothing depends on a
    user opening a page to un-stick it."""
    import time as _time
    while True:
        try:
            from orchestrator import reconcile_all
            result = reconcile_all()
            if result.get("droplets_checked") or result.get("deployments") or result.get("runs"):
                print(f"[reconcile] {result}")
        except Exception as e:
            print(f"[reconcile] Error: {e}")
        _time.sleep(90)


# Start background threads (daemon so they don't block shutdown)
_sched_thread = _threading.Thread(target=_scheduler_loop, daemon=True, name="crest-scheduler")
_sched_thread.start()

_monitor_thread = _threading.Thread(target=_monitor_loop, daemon=True, name="crest-monitor")
_monitor_thread.start()

_reconcile_thread = _threading.Thread(target=_reconcile_loop, daemon=True, name="crest-reconcile")
_reconcile_thread.start()

print("[worker] Scheduler, monitor, and reconcile threads started.")


# ── LOAD PROFILER THREAD ──────────────────────────────────────────────────────

def _load_profiler_loop() -> None:
    """Sample endpoint latency every 5 minutes for load profiling."""
    import time as _time
    while True:
        try:
            _sample_all_models()
        except Exception as e:
            print(f"[load-profiler] Error: {e}")
        _time.sleep(300)  # 5 minutes


def _sample_all_models() -> None:
    """For each model with monitoring enabled, take a latency sample."""
    import asyncio
    from database import get_db as _get_db
    from datetime import datetime, timezone as _tz
    db = _get_db()

    # Only sample models that have monitoring enabled
    enabled_monitor_model_ids = set(
        m.get("model_id") for m in db.monitor_configs.find({"enabled": True})
    )
    if not enabled_monitor_model_ids:
        return

    from bson import ObjectId
    models = list(db.models.find({"_id": {"$in": [ObjectId(mid) for mid in enabled_monitor_model_ids if mid]}}))

    for model in models:
        try:
            loop = asyncio.new_event_loop()
            sample = loop.run_until_complete(_take_load_sample(model))
            loop.close()
            if sample:
                db.load_samples.insert_one(sample)
        except Exception as e:
            print(f"[load-profiler] Sample failed for {model.get('name')}: {e}")


async def _take_load_sample(model: dict) -> dict | None:
    import httpx
    from datetime import datetime, timezone as _tz
    from encryption import decrypt_api_key as _decrypt

    api_key = _decrypt(model.get("api_key_encrypted"))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    model_id_str = model.get("model_id","")
    endpoint = model.get("endpoint_url","").rstrip("/")

    now = datetime.now(_tz.utc)
    try:
        import time as _time
        t0 = _time.monotonic()
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{endpoint}/chat/completions", headers=headers, json={
                "model": model_id_str,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            })
        latency = round((_time.monotonic() - t0) * 1000, 1)
        status = "ok" if r.status_code == 200 else "error"

        # Try to get tokens/sec from usage
        tps = None
        if r.status_code == 200:
            usage = r.json().get("usage", {})
            completion_tokens = usage.get("completion_tokens", 0)
            if completion_tokens and latency > 0:
                tps = round(completion_tokens / (latency / 1000), 1)

        return {
            "model_id": str(model["_id"]),
            "sampled_at": now,
            "latency_ms": latency,
            "status": status,
            "tokens_per_second": tps,
            "day_of_week": now.weekday(),
            "hour_of_day": now.hour,
        }
    except Exception:
        return {
            "model_id": str(model["_id"]),
            "sampled_at": now,
            "latency_ms": 30000.0,
            "status": "timeout",
            "tokens_per_second": None,
            "day_of_week": now.weekday(),
            "hour_of_day": now.hour,
        }


_load_profiler_thread = _threading.Thread(target=_load_profiler_loop, daemon=True, name="crest-load-profiler")
_load_profiler_thread.start()
print("[worker] Load profiler thread started.")

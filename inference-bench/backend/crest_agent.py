#!/usr/bin/env python3
"""Crest on-droplet agent (Benchmarking Evaluation — control channel).

Runs on the GPU droplet as a systemd service. The backend (on DO App Platform)
cannot open inbound/SSH connections to droplets — App Platform only allows
outbound HTTPS — so the droplet calls home instead: this agent polls the backend
for jobs, runs Docker locally, and POSTs progress / logs / health back.

stdlib only (no pip) so it runs on a bare AI/ML image. Configured via env
(systemd EnvironmentFile /opt/crest/agent.env):
    CREST_URL          backend base URL, e.g. https://crest-xxxx.ondigitalocean.app
    CREST_AGENT_TOKEN  per-droplet bearer token
    CREST_DROPLET_ID   droplet record id (for logging)

The backend serves the canonical copy of this file at /api/agent/script and the
systemd unit re-fetches it on every (re)start, so the agent self-heals/updates.
"""
import glob
import json
import math
import os
import shlex
import statistics
import subprocess
import threading
import time
import urllib.request
import urllib.error

CREST_URL = os.environ.get("CREST_URL", "").rstrip("/")
TOKEN = os.environ.get("CREST_AGENT_TOKEN", "")
DROPLET_ID = os.environ.get("CREST_DROPLET_ID", "")
STATE_PATH = "/opt/crest/state.json"

POLL_INTERVAL_S = 5
HEARTBEAT_INTERVAL_S = 15


# ── backend HTTP ──────────────────────────────────────────────────────────────

def _req(method: str, path: str, body: dict | None = None, timeout: int = 30):
    url = f"{CREST_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            if r.status == 204 or not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return None
        raise


def report(job_id: str, **fields) -> None:
    try:
        _req("POST", f"/api/agent/jobs/{job_id}/event", fields)
    except Exception as e:
        print(f"[agent] report failed: {e}", flush=True)


# ── local helpers ─────────────────────────────────────────────────────────────

def sh(cmd: str, timeout: int) -> tuple[int, str]:
    """Run a shell command; return (exit_code, combined_output)."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout}s)"


def http_ok(url: str, timeout: int = 10) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def friendly_error(logs: str) -> str | None:
    """Map common container-startup failures to a short, user-readable message.
    Raw logs are still kept in log_tail for debugging."""
    low = (logs or "").lower()
    if "gated repo" in low or ("access to model" in low and "restricted" in low) \
            or ("401 client error" in low and "huggingface" in low):
        return ("This model is gated on HuggingFace and needs an access token. Add an HF "
                "token with access to this model and redeploy, or choose an open model.")
    if "failed to infer device type" in low or "no cuda runtime is found" in low \
            or "0 active driver(s) found" in low:
        return ("The container image doesn't match this GPU's platform — this looks like an "
                "NVIDIA/CUDA vLLM image running on an AMD ROCm GPU. Use a ROCm image (e.g. "
                "'rocm/vllm') for AMD GPUs, or deploy on an NVIDIA GPU.")
    if "out of memory" in low or "hip out of memory" in low or "cuda out of memory" in low:
        return "The GPU ran out of memory loading this model. Try a smaller model or a larger GPU plan."
    if "no such file or directory" in low and "huggingface" in low:
        return "The model weights could not be downloaded. Check the model name and HF token."
    # Benchmark-specific failures.
    if "no matching distribution" in low or "could not find a version" in low:
        return "Could not install aiperf on the droplet. Check the droplet's network access and Python version."
    if "connection refused" in low or "failed to establish a new connection" in low \
            or "max retries exceeded" in low:
        return "aiperf could not reach the model endpoint. Make sure the deployment is still serving."
    return None


def save_state(state: dict) -> None:
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


# ── jobs ───────────────────────────────────────────────────────────────────────

def ensure_docker(job_id: str) -> bool:
    """Some DO GPU images (e.g. the AMD AI/ML image) ship GPU drivers but no
    container runtime. Install Docker on demand if it's missing. Guarded so images
    that already have Docker (NVIDIA AI/ML) are untouched."""
    rc, _ = sh("command -v docker", 10)
    if rc == 0:
        return True
    report(job_id, status="pulling", event="installing_docker")
    sh("apt-get update -y", 300)
    rc, out = sh("DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io", 900)
    if rc != 0:
        report(job_id, status="failed", event="deployment_failed",
               error=f"Docker is not installed and automatic install failed: {out[-500:]}")
        return False
    sh("systemctl enable --now docker", 60)
    rc, _ = sh("command -v docker", 10)
    return rc == 0


def run_deploy(job: dict) -> None:
    """spec: {deployment_id, container, image, run_cmd, health_url,
             pull_timeout, health_timeout, poll_interval}"""
    job_id = job["id"]
    s = job["spec"]
    container = s["container"]
    health_url = s["health_url"]

    save_state({"deployment_id": s["deployment_id"], "container": container, "health_url": health_url})

    if not ensure_docker(job_id):
        return

    # Clear any stale container from a prior attempt.
    sh(f"docker rm -f {container} 2>/dev/null || true", 60)

    report(job_id, status="pulling", event="deployment_pulling", image=s["image"])
    rc, out = sh(f"docker pull {s['image']}", s.get("pull_timeout", 1800))
    if rc != 0:
        report(job_id, status="failed", event="deployment_failed", error=f"docker pull failed: {out[-800:]}")
        return
    report(job_id, status="starting", event="image_pulled")

    rc, out = sh(s["run_cmd"], 180)
    if rc != 0:
        report(job_id, status="failed", event="deployment_failed", error=f"docker run failed: {out[-800:]}")
        return
    cid = out.strip().splitlines()[-1][:12] if out.strip() else None
    report(job_id, status="starting", event="container_started", container_id=cid)

    deadline = time.time() + s.get("health_timeout", 1800)
    interval = s.get("poll_interval", 5)
    while time.time() < deadline:
        _rc, logs = sh(f"docker logs --tail 60 {container} 2>&1", 30)
        # Crash detection that survives Docker's restart policy: a crash-looping
        # container reads as Running between restarts, so we also check Status and
        # RestartCount — an exited/dead container, or one that keeps restarting,
        # isn't coming up.
        _rc, info = sh(f"docker inspect -f '{{{{.State.Status}}}} {{{{.RestartCount}}}}' {container} 2>/dev/null || echo 'missing 0'", 30)
        parts = info.split()
        cstatus = parts[0] if parts else "missing"
        restarts = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if cstatus in ("exited", "dead", "missing") or restarts >= 3:
            sh(f"docker rm -f {container} 2>/dev/null || true", 60)  # don't leave a zombie on the GPU
            msg = friendly_error(logs) or f"Container failed to start (status={cstatus}, restarts={restarts}). See container logs below."
            report(job_id, status="failed", event="deployment_failed", error=msg, log_tail=logs[-6000:])
            return
        if http_ok(health_url):
            report(job_id, status="serving", event="deployment_serving", health="ok", log_tail=logs[-6000:])
            return
        report(job_id, status="starting", event="waiting_for_health", log_tail=logs[-6000:])
        time.sleep(interval)

    _rc, logs = sh(f"docker logs --tail 80 {container} 2>&1", 30)
    sh(f"docker rm -f {container} 2>/dev/null || true", 60)
    report(job_id, status="failed", event="deployment_failed",
           error=f"Model did not become healthy within {s.get('health_timeout', 1800)}s",
           log_tail=logs[-6000:])


# ── benchmark (aiperf) ──────────────────────────────────────────────────────────

def _pct(s: list, p: float) -> float:
    """Linear-interpolation percentile (matches numpy.percentile) on a sorted list."""
    if not s:
        return 0.0
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def _stats(values: list, extra_percentiles: list) -> dict:
    """avg/min/max/std + standard p50/p90/p95/p99 + any opt-in extras (e.g. p75)."""
    if not values:
        return {}
    s = sorted(values)
    out = {
        "avg": round(sum(s) / len(s), 4),
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
        "p50": round(_pct(s, 50), 4),
        "p90": round(_pct(s, 90), 4),
        "p95": round(_pct(s, 95), 4),
        "p99": round(_pct(s, 99), 4),
    }
    if len(s) > 1:
        out["std"] = round(statistics.stdev(s), 4)
    for p in (extra_percentiles or []):
        try:
            pi = int(p)
        except (TypeError, ValueError):
            continue
        if 0 < pi < 100:
            out[f"p{pi}"] = round(_pct(s, pi), 4)
    return out


def _load_records(workdir: str) -> list:
    """Read aiperf's per-request export (profile_export.jsonl) — one JSON record
    per request. Computing metrics from this here means we never ship raw data
    back, so arbitrary percentiles cost nothing and there's no Mongo size issue."""
    paths = (glob.glob(f"{workdir}/art/**/profile_export.jsonl", recursive=True)
             or glob.glob(f"{workdir}/**/profile_export.jsonl", recursive=True))
    if not paths:
        return []
    recs = []
    with open(paths[0], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    return recs


def _compute_metrics(records: list, extra_percentiles: list) -> dict:
    """Normalize aiperf per-request records into {metric: {avg,min,max,p50,...,unit}}
    plus throughput/duration aggregates. Excludes warmup, keeps only profiling."""
    recs = [r for r in records
            if (r.get("metadata") or {}).get("benchmark_phase", "profiling") == "profiling"] or records

    collected: dict = {}     # metric_key -> {"values": [...], "unit": str}
    starts, ends = [], []
    out_tokens_total = 0.0
    in_tokens_total = 0.0
    for r in recs:
        md = r.get("metadata") or {}
        st, en = md.get("request_start_ns"), md.get("request_end_ns")
        if isinstance(st, (int, float)):
            starts.append(st)
        if isinstance(en, (int, float)):
            ends.append(en)
        m = r.get("metrics") or {}
        for key, mv in m.items():
            if not isinstance(mv, dict):
                continue
            val = mv.get("value")
            if not isinstance(val, (int, float)):
                continue
            slot = collected.setdefault(key, {"values": [], "unit": mv.get("unit") or ""})
            slot["values"].append(float(val))
        otc = m.get("output_token_count") or m.get("output_sequence_length") or {}
        if isinstance(otc, dict) and isinstance(otc.get("value"), (int, float)):
            out_tokens_total += float(otc["value"])
        isl = m.get("input_sequence_length") or {}
        if isinstance(isl, dict) and isinstance(isl.get("value"), (int, float)):
            in_tokens_total += float(isl["value"])

    metrics: dict = {}
    for key, slot in collected.items():
        metrics[key] = {"unit": slot["unit"], **_stats(slot["values"], extra_percentiles)}

    n = len(recs)
    metrics["request_count"] = {"unit": "requests", "value": n}
    if starts and ends:
        dur = (max(ends) - min(starts)) / 1e9
        if dur > 0:
            metrics["benchmark_duration"] = {"unit": "sec", "value": round(dur, 2)}
            metrics["request_throughput"] = {"unit": "requests/sec", "value": round(n / dur, 2)}
            metrics["input_token_throughput"] = {"unit": "tokens/sec", "value": round(in_tokens_total / dur, 1)}
            metrics["output_token_throughput"] = {"unit": "tokens/sec", "value": round(out_tokens_total / dur, 1)}
    return metrics


# ── serving-state trends (from vLLM /metrics — the ONLY new source) ─────────────
# We plot KV-cache %, prefix-cache hit %, queue depth and token rates from vLLM's
# Prometheus endpoint. We deliberately do NOT read latency from here — TTFT/TPOT
# come solely from aiperf (below), the same source every other view already uses,
# so the numbers can never disagree.
SAMPLE_INTERVAL_S = 2


def _scrape_text(url: str, timeout: int = 5) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace") if r.status == 200 else None
    except Exception:
        return None


def _parse_prom(text: str) -> dict:
    """Minimal Prometheus text parse → {metric_name: summed_value}. Sums across label
    series (our droplet serves one model). Skips comments; good enough for the
    gauges/counters we read (not histogram buckets)."""
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] == "#":
            continue
        try:
            if "{" in line:
                name = line[:line.index("{")]
                rest = line[line.rindex("}") + 1:].strip()
            else:
                name, rest = line.split(None, 1)
            val = float(rest.split()[0])
        except (ValueError, IndexError):
            continue
        out[name] = out.get(name, 0.0) + val
    return out


def _prom_get(m: dict, *needles) -> float | None:
    """First metric whose name contains a needle (tolerant of vLLM v0/v1 name drift)."""
    for k, v in m.items():
        if any(nd in k for nd in needles):
            return v
    return None


SERVING_REPORT_INTERVAL_S = 5   # how often we stream partial serving trends to the UI


class _ServingSampler(threading.Thread):
    """Polls vLLM's /metrics on a timer for the whole benchmark. Buffers samples and
    also streams the serving-state series live (~every 5s) so the UI can watch KV
    cache / queue / tok/s during the run. Latency percentiles stay post-hoc (aiperf
    only exports at the end). Daemon thread; stop() ends it."""
    def __init__(self, port: int, job_id: str = ""):
        super().__init__(daemon=True)
        self._url = f"http://localhost:{port}/metrics"
        self._stop = threading.Event()
        self._t0 = time.time()
        self._job_id = job_id
        self._last_report = 0.0
        self.samples: list = []

    def run(self) -> None:
        while not self._stop.is_set():
            text = _scrape_text(self._url)
            if text:
                m = _parse_prom(text)
                kv = _prom_get(m, "cache_usage_perc")
                self.samples.append({
                    "t": round(time.time() - self._t0, 1),
                    "running": _prom_get(m, "num_requests_running"),
                    "waiting": _prom_get(m, "num_requests_waiting"),
                    "kv": (kv * 100 if isinstance(kv, float) and kv <= 1.0 else kv),
                    "hits": _prom_get(m, "prefix_cache_hits"),
                    "queries": _prom_get(m, "prefix_cache_queries"),
                    "prompt_tok": _prom_get(m, "prompt_tokens_total"),
                    "gen_tok": _prom_get(m, "generation_tokens_total"),
                })
                now = time.time()
                if self._job_id and now - self._last_report >= SERVING_REPORT_INTERVAL_S:
                    self._last_report = now
                    # Partial trends: serving only, no status/event — just updates the
                    # run doc's `trends`, which the SSE stream already relays live.
                    report(self._job_id, trends={
                        "serving": _downsample(_serving_series(self.samples)),
                        "serving_available": True,
                    })
            self._stop.wait(SAMPLE_INTERVAL_S)

    def stop(self) -> None:
        self._stop.set()


def _serving_series(samples: list) -> list:
    """Turn raw samples into display points: gauges as-is, counters as interval rates."""
    out, prev = [], None
    for s in samples:
        pt: dict = {"t": s["t"]}
        if s.get("running") is not None:
            pt["running"] = round(s["running"], 1)
        if s.get("waiting") is not None:
            pt["waiting"] = round(s["waiting"], 1)
        if s.get("kv") is not None:
            pt["kv_cache_pct"] = round(s["kv"], 1)
        if prev is not None:
            dt = s["t"] - prev["t"]
            if dt > 0:
                for src, dst in (("prompt_tok", "in_tok_s"), ("gen_tok", "out_tok_s")):
                    if s.get(src) is not None and prev.get(src) is not None:
                        pt[dst] = round(max(0.0, s[src] - prev[src]) / dt, 1)
            if all(s.get(k) is not None and prev.get(k) is not None for k in ("hits", "queries")):
                dq = s["queries"] - prev["queries"]
                if dq > 0:
                    pt["prefix_hit_pct"] = round(100.0 * max(0.0, s["hits"] - prev["hits"]) / dq, 1)
        out.append(pt)
        prev = s
    return out


def _latency_series(records: list, target_points: int = 80) -> list:
    """Exact windowed latency percentiles from aiperf's per-request export — the SAME
    records/percentile logic as the aggregate metrics, just bucketed by request start
    time. Guarantees the trend and the headline numbers agree (one source)."""
    recs = [r for r in records
            if (r.get("metadata") or {}).get("benchmark_phase", "profiling") == "profiling"] or records
    pts = []
    for r in recs:
        st = (r.get("metadata") or {}).get("request_start_ns")
        if not isinstance(st, (int, float)):
            continue
        m = r.get("metrics") or {}
        def mv(*keys):
            for k in keys:
                d = m.get(k)
                if isinstance(d, dict) and isinstance(d.get("value"), (int, float)):
                    return float(d["value"])
            return None
        pts.append((st, mv("time_to_first_token"), mv("inter_token_latency"),
                    mv("request_latency", "e2e_request_latency"),
                    mv("output_token_count", "output_sequence_length")))
    if not pts:
        return []
    pts.sort(key=lambda x: x[0])
    t0 = pts[0][0]
    window_ns = max(1e9, (pts[-1][0] - t0) / max(1, target_points))
    buckets: dict = {}
    for st, ttft, tpot, e2e, otok in pts:
        b = buckets.setdefault(int((st - t0) // window_ns),
                               {"ttft": [], "tpot": [], "e2e": [], "otok": 0.0})
        for key, val in (("ttft", ttft), ("tpot", tpot), ("e2e", e2e)):
            if val is not None:
                b[key].append(val)
        if otok is not None:
            b["otok"] += otok
    win_s = window_ns / 1e9
    out = []
    for b in sorted(buckets):
        d = buckets[b]
        pt = {"t": round(b * win_s, 1), "req": max(len(d["ttft"]), len(d["e2e"]))}
        for key, arr in (("ttft", d["ttft"]), ("tpot", d["tpot"]), ("e2e", d["e2e"])):
            if arr:
                srt = sorted(arr)
                pt[f"{key}_p50"] = round(_pct(srt, 50), 2)
                pt[f"{key}_p90"] = round(_pct(srt, 90), 2)
        if win_s > 0:
            pt["out_tok_s"] = round(d["otok"] / win_s, 1)
        out.append(pt)
    return out


def _downsample(rows: list, max_points: int = 120) -> list:
    if len(rows) <= max_points:
        return rows
    step = len(rows) / max_points
    return [rows[int(i * step)] for i in range(max_points)]


def run_benchmark(job: dict) -> None:
    """spec: {aiperf_run_id, image, aiperf_args, env, extra_percentiles, metrics_port,
    run_timeout}. Runs aiperf in a container (pip-installed at run time) against
    localhost, then computes metrics locally from the per-request export."""
    job_id = job["id"]
    s = job["spec"]

    if not ensure_docker(job_id):
        return

    report(job_id, status="running", event="benchmark_starting")
    workdir = f"/opt/crest/bench/{job_id}"
    sh(f"rm -rf {workdir}; mkdir -p {workdir}", 30)

    image = s.get("image") or "python:3.12"
    env_flags = []
    for k, v in (s.get("env") or {}).items():
        if k:
            env_flags += ["-e", f"{k}={v}"]
    aiperf_args = s.get("aiperf_args") or []
    inner = ("pip install -q aiperf && aiperf profile "
             + " ".join(shlex.quote(t) for t in aiperf_args)
             + " --artifact-dir /work/art")
    docker_argv = (["docker", "run", "--rm", "--network", "host",
                    "-v", "/root/.cache/huggingface:/root/.cache/huggingface",
                    "-v", f"{workdir}:/work"]
                   + env_flags + [image, "sh", "-lc", inner])
    cmd = " ".join(shlex.quote(t) for t in docker_argv)

    # Sample vLLM /metrics for the duration so we can plot serving-state trends.
    sampler = None
    metrics_port = s.get("metrics_port")
    if metrics_port:
        sampler = _ServingSampler(int(metrics_port), job_id=job_id)
        sampler.start()

    report(job_id, status="running", event="benchmark_running")
    rc, logs = sh(cmd, s.get("run_timeout", 3600))
    if sampler:
        sampler.stop()
    if rc != 0:
        msg = friendly_error(logs) or f"aiperf run failed (exit {rc}). See logs below."
        report(job_id, status="failed", event="benchmark_failed", error=msg, log_tail=logs[-6000:])
        sh(f"rm -rf {workdir}", 30)
        return

    try:
        records = _load_records(workdir)
    except Exception as e:
        report(job_id, status="failed", event="benchmark_failed",
               error=f"Could not read aiperf results: {e}", log_tail=logs[-6000:])
        sh(f"rm -rf {workdir}", 30)
        return

    if not records:
        report(job_id, status="failed", event="benchmark_failed",
               error="aiperf produced no results — the endpoint may have rejected all requests. See logs below.",
               log_tail=logs[-6000:])
        sh(f"rm -rf {workdir}", 30)
        return

    metrics = _compute_metrics(records, s.get("extra_percentiles") or [])
    trends = {
        "latency": _latency_series(records),
        "serving": _downsample(_serving_series(sampler.samples)) if sampler else [],
        "serving_available": bool(sampler and sampler.samples),
    }
    report(job_id, status="completed", event="benchmark_completed",
           metrics=metrics, trends=trends, log_tail=logs[-6000:])
    sh(f"rm -rf {workdir}", 30)


JOB_RUNNERS = {"deploy": run_deploy, "benchmark": run_benchmark}


def run_job(job: dict) -> None:
    runner = JOB_RUNNERS.get(job.get("type"))
    if not runner:
        report(job["id"], status="failed", event="job_failed", error=f"Unknown job type: {job.get('type')}")
        return
    try:
        runner(job)
    except Exception as e:
        report(job["id"], status="failed", event="job_failed", error=str(e))


# ── GPU metrics (nvidia-smi / rocm-smi — sent on every heartbeat) ───────────────
_gpu_vendor = None


def _detect_gpu_vendor() -> str:
    global _gpu_vendor
    if _gpu_vendor is None:
        if sh("command -v nvidia-smi", 5)[0] == 0:
            _gpu_vendor = "nvidia"
        elif sh("command -v rocm-smi", 5)[0] == 0:
            _gpu_vendor = "amd"
        else:
            _gpu_vendor = "none"
    return _gpu_vendor


def _gpu_sample() -> list:
    """Per-GPU {util%, VRAM, temp, power} from smi. Best-effort; [] if unavailable."""
    vendor = _detect_gpu_vendor()
    if vendor == "nvidia":
        rc, out = sh("nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,"
                     "temperature.gpu,power.draw --format=csv,noheader,nounits", 15)
        if rc != 0:
            return []
        gpus = []
        for line in out.strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) < 6:
                continue
            try:
                used, total = float(p[2]), float(p[3])
                gpus.append({
                    "index": int(float(p[0])), "util_pct": float(p[1]),
                    "vram_used_mb": used, "vram_total_mb": total,
                    "vram_pct": round(100.0 * used / total, 1) if total else None,
                    "temp_c": float(p[4]), "power_w": float(p[5]),
                })
            except ValueError:
                continue
        return gpus
    if vendor == "amd":
        rc, out = sh("rocm-smi --showuse --showmemuse --showtemp --showpower --json", 15)
        if rc != 0:
            return []
        try:
            data = json.loads(out)
        except Exception:
            return []
        gpus = []
        for card in sorted(data):
            if not card.lower().startswith("card"):
                continue
            d = data[card]
            def gnum(*needles):
                for k in d:
                    if any(nd.lower() in k.lower() for nd in needles):
                        try:
                            return float(str(d[k]).split()[0])
                        except (ValueError, IndexError):
                            return None
                return None
            gpus.append({
                "index": int("".join(ch for ch in card if ch.isdigit()) or 0),
                "util_pct": gnum("GPU use (%)"),
                "vram_pct": gnum("GPU Memory Allocated (VRAM%)", "GPU memory use (%)", "VRAM%"),
                "temp_c": gnum("Temperature (Sensor junction)", "Temperature (Sensor edge)", "Temperature"),
                "power_w": gnum("Average Graphics Package Power", "Socket Graphics Package Power", "Power"),
            })
        return gpus
    return []


def heartbeat() -> None:
    """Liveness + refresh the serving deployment's health/logs and a GPU snapshot,
    so the UI stays current without the backend ever connecting to the droplet."""
    payload: dict = {"droplet_id": DROPLET_ID}
    st = load_state()
    if st.get("deployment_id") and st.get("container"):
        _rc, logs = sh(f"docker logs --tail 60 {st['container']} 2>&1", 20)
        payload.update({
            "deployment_id": st["deployment_id"],
            "health": "ok" if http_ok(st.get("health_url", "")) else "down",
            "log_tail": logs[-6000:],
        })
    gpu = _gpu_sample()
    if gpu:
        payload["gpu"] = gpu
    try:
        _req("POST", "/api/agent/heartbeat", payload)
    except Exception as e:
        print(f"[agent] heartbeat failed: {e}", flush=True)


def main() -> None:
    print(f"[agent] starting for droplet {DROPLET_ID} → {CREST_URL}", flush=True)
    last_hb = 0.0
    while True:
        now = time.time()
        if now - last_hb >= HEARTBEAT_INTERVAL_S:
            heartbeat()
            last_hb = now
        try:
            job = _req("GET", "/api/agent/jobs/next")
        except Exception as e:
            print(f"[agent] poll failed: {e}", flush=True)
            job = None
        if job:
            print(f"[agent] running job {job.get('id')} ({job.get('type')})", flush=True)
            run_job(job)
            last_hb = 0.0  # heartbeat promptly after a job
        else:
            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()

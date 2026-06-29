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
    """avg/min/max/std + standard p50/p90/p99 + any opt-in extras (e.g. p75)."""
    if not values:
        return {}
    s = sorted(values)
    out = {
        "avg": round(sum(s) / len(s), 4),
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
        "p50": round(_pct(s, 50), 4),
        "p90": round(_pct(s, 90), 4),
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


def run_benchmark(job: dict) -> None:
    """spec: {aiperf_run_id, image, aiperf_args, env, extra_percentiles, run_timeout}.
    Runs aiperf in a container (pip-installed at run time) against localhost, then
    computes metrics locally from the per-request export."""
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

    report(job_id, status="running", event="benchmark_running")
    rc, logs = sh(cmd, s.get("run_timeout", 3600))
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
    report(job_id, status="completed", event="benchmark_completed", metrics=metrics, log_tail=logs[-6000:])
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


def heartbeat() -> None:
    """Liveness + refresh the serving deployment's health/logs so the UI stays
    current without the backend ever connecting to the droplet."""
    payload: dict = {"droplet_id": DROPLET_ID}
    st = load_state()
    if st.get("deployment_id") and st.get("container"):
        _rc, logs = sh(f"docker logs --tail 60 {st['container']} 2>&1", 20)
        payload.update({
            "deployment_id": st["deployment_id"],
            "health": "ok" if http_ok(st.get("health_url", "")) else "down",
            "log_tail": logs[-6000:],
        })
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

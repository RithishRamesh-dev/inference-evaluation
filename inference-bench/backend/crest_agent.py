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
import json
import os
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

def run_deploy(job: dict) -> None:
    """spec: {deployment_id, container, image, run_cmd, health_url,
             pull_timeout, health_timeout, poll_interval}"""
    job_id = job["id"]
    s = job["spec"]
    container = s["container"]
    health_url = s["health_url"]

    save_state({"deployment_id": s["deployment_id"], "container": container, "health_url": health_url})

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
            report(job_id, status="failed", event="deployment_failed",
                   error=f"Container failed to start (status={cstatus}, restarts={restarts}). Recent logs:\n{logs[-1500:]}",
                   log_tail=logs[-6000:])
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


JOB_RUNNERS = {"deploy": run_deploy}


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

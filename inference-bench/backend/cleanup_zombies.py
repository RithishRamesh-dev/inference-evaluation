"""One-time cleanup for zombie droplets / deployments / benchmarks.

Background: reconciliation historically only ran on `active` droplets and only
lazily (on a page load). A destroy that hit an auth error left the record `failed`
while the real DigitalOcean droplet kept running — and since `failed` was never
re-checked, deleting it later in the DO console never propagated. Deployments then
stayed `serving` and benchmarks stayed `queued`/`running` forever.

The code fix (destroy_failed state + un-gated, background reconcile) stops NEW
zombies. This script cleans up the ones that already exist. It talks to DO directly
so it doesn't depend on the app's reconcile loop.

Run from inference-bench/backend (same env as the app — MONGODB_URL + encryption key):

    python cleanup_zombies.py                     # DRY RUN — report only, no writes
    python cleanup_zombies.py --apply             # commit the safe fixes
    python cleanup_zombies.py --apply --redestroy # also re-attempt destroy on
                                                  #   live-but-stuck droplets

Safe fixes (require --apply):
  * droplet confirmed gone in DO (404) -> mark destroyed, cascade its deployments
    to droplet_destroyed, fail its pending benchmarks, delete its DO SSH key.
  * deployment still pulling/starting/serving on a destroyed/missing droplet
    -> droplet_destroyed.
  * benchmark still queued/running on a destroyed/missing droplet -> failed
    ("Droplet destroyed"); its lingering agent job -> failed.

Live-but-stuck droplets (DO says still running, but Crest has them
failed/destroy_failed/destroying) are the real money leak. They are ONLY reported
unless you pass --redestroy, which re-attempts the destroy.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import httpx

from database import get_db, oid
from encryption import decrypt_api_key

DO_API = "https://api.digitalocean.com"

# Droplet states worth verifying against DO (mirror orchestrator.RECONCILABLE_STATES
# plus `destroying`, which can get stuck if the app restarted mid-destroy).
CHECK_STATES = ("active", "failed", "destroy_failed", "destroying")
DEP_ACTIVE = ("pulling", "starting", "serving")
RUN_PENDING = ("queued", "running")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_droplet(client: httpx.Client, token: str, do_id: int) -> int:
    """Return the DO HTTP status for a droplet GET (200 alive, 404 gone, other=?)."""
    r = client.get(f"{DO_API}/v2/droplets/{do_id}", headers=_headers(token))
    return r.status_code


def _delete_droplet(client: httpx.Client, token: str, do_id: int) -> int:
    r = client.delete(f"{DO_API}/v2/droplets/{do_id}", headers=_headers(token))
    return r.status_code


def _delete_ssh_key(client: httpx.Client, token: str, key_id: int) -> None:
    client.delete(f"{DO_API}/v2/account/keys/{key_id}", headers=_headers(token))


def _cascade_destroyed(db, droplet: dict, detail: str, apply: bool) -> tuple[int, int]:
    """Mark a droplet destroyed and cascade to its deployments/benchmarks. Returns
    (deployments_cascaded, runs_failed) counts (computed even in dry-run)."""
    did = str(droplet["_id"])
    now = datetime.now(timezone.utc)
    deps = db.deployments.count_documents(
        {"droplet_id": did, "status": {"$nin": ["droplet_destroyed"]}})
    runs = db.aiperf_runs.count_documents(
        {"droplet_id": did, "status": {"$in": list(RUN_PENDING)}})
    if apply:
        db.gpu_droplets.update_one({"_id": droplet["_id"]}, {"$set": {
            "status": "destroyed", "status_detail": detail,
            "ip": None, "destroyed_at": now}})
        db.deployments.update_many(
            {"droplet_id": did, "status": {"$nin": ["droplet_destroyed"]}},
            {"$set": {"status": "droplet_destroyed", "droplet_destroyed_at": now}})
        db.aiperf_runs.update_many(
            {"droplet_id": did, "status": {"$in": list(RUN_PENDING)}},
            {"$set": {"status": "failed", "status_detail": "Droplet destroyed",
                      "completed_at": now}})
    return deps, runs


def cleanup(apply: bool, redestroy: bool) -> None:
    db = get_db()
    mode = "APPLY" if apply else "DRY RUN"
    print(f"=== Zombie cleanup ({mode}{' +redestroy' if redestroy else ''}) ===\n")

    live_but_stuck: list[str] = []
    unknown: list[str] = []
    destroyed = 0
    dep_cascaded = 0
    run_failed = 0

    # ── Phase 1: reconcile droplets against DO ────────────────────────────────
    droplets = list(db.gpu_droplets.find(
        {"status": {"$in": list(CHECK_STATES)}, "do_droplet_id": {"$ne": None}}))
    print(f"Phase 1 — checking {len(droplets)} droplet(s) against DigitalOcean:")
    for d in droplets:
        name = d.get("name") or str(d["_id"])
        st = d.get("status")
        do_id = d.get("do_droplet_id")
        token = decrypt_api_key(d.get("do_token_encrypted"))
        if not token:
            unknown.append(f"{name} ({st}) — no usable DO token; check manually")
            continue
        try:
            with httpx.Client(timeout=20) as client:
                code = _get_droplet(client, token, do_id)
                if code == 404:
                    deps, runs = _cascade_destroyed(
                        db, d, "Destroyed in the DigitalOcean console", apply)
                    destroyed += 1
                    dep_cascaded += deps
                    run_failed += runs
                    print(f"  · {name} ({st}) -> DESTROYED (gone in DO); "
                          f"cascade {deps} deployment(s), {runs} run(s)")
                elif code in (200, 202):
                    if st == "active":
                        continue  # alive and correctly tracked — nothing to do
                    live_but_stuck.append(f"{name} ({st}) — DO droplet {do_id} still running")
                    if redestroy:
                        dc = _delete_droplet(client, token, do_id)
                        if dc in (204, 404):
                            if d.get("do_ssh_key_id"):
                                try:
                                    _delete_ssh_key(client, token, d["do_ssh_key_id"])
                                except Exception:
                                    pass
                            deps, runs = _cascade_destroyed(
                                db, d, "Destroyed via cleanup (re-destroy)", apply)
                            destroyed += 1
                            dep_cascaded += deps
                            run_failed += runs
                            print(f"  · {name} ({st}) -> RE-DESTROYED (DO {dc}); "
                                  f"cascade {deps} deployment(s), {runs} run(s)")
                        else:
                            print(f"  · {name} ({st}) -> re-destroy FAILED (DO {dc}); check manually")
                else:
                    unknown.append(f"{name} ({st}) — DO returned {code}; check manually")
        except Exception as exc:
            unknown.append(f"{name} ({st}) — error contacting DO: {exc}")

    # ── Phase 2: orphaned deployments (droplet no longer active) ──────────────
    print("\nPhase 2 — orphaned deployments:")
    now = datetime.now(timezone.utc)
    dead_dep = 0
    for dep in db.deployments.find({"status": {"$in": list(DEP_ACTIVE)}}):
        dr = db.gpu_droplets.find_one({"_id": oid(dep["droplet_id"])}, {"status": 1}) \
            if dep.get("droplet_id") else None
        if dr is None or dr.get("status") != "active":
            dead_dep += 1
            print(f"  · deployment {dep.get('model')} ({dep.get('status')}) "
                  f"-> droplet_destroyed")
            if apply:
                db.deployments.update_one({"_id": dep["_id"]}, {"$set": {
                    "status": "droplet_destroyed", "droplet_destroyed_at": now}})
    if not dead_dep:
        print("  · none")

    # ── Phase 3: orphaned benchmarks + their agent jobs ───────────────────────
    print("\nPhase 3 — orphaned benchmarks:")
    dead_run = 0
    for run in db.aiperf_runs.find({"status": {"$in": list(RUN_PENDING)}}):
        dr = db.gpu_droplets.find_one({"_id": oid(run["droplet_id"])}, {"status": 1}) \
            if run.get("droplet_id") else None
        if dr is None or dr.get("status") != "active":
            dead_run += 1
            print(f"  · run {run['_id']} ({run.get('status')}) -> failed (Droplet no longer active)")
            if apply:
                db.aiperf_runs.update_one({"_id": run["_id"]}, {"$set": {
                    "status": "failed", "status_detail": "Droplet no longer active",
                    "completed_at": now}})
    if apply:
        # Close any agent jobs left queued/running for a gone droplet.
        for job in db.agent_jobs.find({"status": {"$in": ["queued", "running"]}}):
            dr = db.gpu_droplets.find_one({"_id": oid(job["droplet_id"])}, {"status": 1}) \
                if job.get("droplet_id") else None
            if dr is None or dr.get("status") != "active":
                db.agent_jobs.update_one({"_id": job["_id"]},
                                         {"$set": {"status": "failed", "completed_at": now}})
    if not dead_run:
        print("  · none")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n=== Summary ===")
    print(f"  droplets marked destroyed : {destroyed}")
    print(f"  deployments cascaded      : {dep_cascaded + dead_dep}")
    print(f"  benchmarks failed         : {run_failed + dead_run}")
    if live_but_stuck:
        print(f"\n  ⚠ LIVE-BUT-STUCK droplets still running on DigitalOcean "
              f"({len(live_but_stuck)}) — {'re-destroyed above' if redestroy else 'destroy these manually or re-run with --redestroy'}:")
        for s in live_but_stuck:
            print(f"      - {s}")
    if unknown:
        print(f"\n  ? Could not determine ({len(unknown)}) — check manually:")
        for s in unknown:
            print(f"      - {s}")
    if not apply:
        print("\n(DRY RUN — no changes written. Re-run with --apply to commit.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Clean up zombie droplets/deployments/benchmarks.")
    ap.add_argument("--apply", action="store_true", help="commit changes (default: dry run)")
    ap.add_argument("--redestroy", action="store_true",
                    help="also re-attempt destroy on live-but-stuck droplets")
    args = ap.parse_args()
    try:
        cleanup(apply=args.apply, redestroy=args.redestroy)
    except KeyboardInterrupt:
        sys.exit(1)

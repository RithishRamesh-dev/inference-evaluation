#!/usr/bin/env python3
"""
run.py — Kimi K2.6 Endpoint Evaluation
=======================================
Requirement-aligned test runner.
Each module maps 1:1 to a numbered requirement from the official spec.

Usage:
  python run.py                                  # all requirements
  python run.py --reqs R1 R4 R5                 # specific requirements
  python run.py --perf --perf-samples 30         # include TTFT (R12) + OTPS (R13)
  python run.py --eos-runs 1000                  # full spec EOS test
  python run.py --full-accuracy                  # run evalscope benchmarks
  python run.py --reqs R11 --full-accuracy       # accuracy only, full evalscope

Required env vars:
  EVAL_ENDPOINT_URL   https://your-endpoint/v1
  EVAL_API_KEY        your-api-key
  EVAL_MODEL          kimi-k2.6 (default)
"""
import argparse, json, os, sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

for v in ("EVAL_ENDPOINT_URL", "EVAL_API_KEY"):
    if not os.getenv(v):
        print(f"ERROR: {v} not set.\n  export {v}=...")
        sys.exit(1)

from core.common import console, get_results, print_report, ENDPOINT, MODEL
from tests import (
    r1_thinking_mode, r2_r3_parameters, r4_system_prompt,
    r5_interleaved_thinking, r6_eos_suppression, r7_image_input,
    r8_r9_observability, r10_openclaw_toolcall, r11_accuracy,
    r12_ttft, r13_otps, r14_cache, r15_r16_r17_sla,
)

REQUIREMENTS = {
    "R1":         (r1_thinking_mode,      False, "Thinking Mode Activation"),
    "R2_R3":      (r2_r3_parameters,      False, "Parameter Defaults & max_tokens"),
    "R4":         (r4_system_prompt,      False, "System Prompt — must not inject"),
    "R5":         (r5_interleaved_thinking,False,"Interleaved Thinking + Tool Calls"),
    "R6":         (r6_eos_suppression,    False, "EOS Suppression (1000-run test)"),
    "R7":         (r7_image_input,        False, "Image Input (24 official cases)"),
    "R8_R9":      (r8_r9_observability,   False, "Trace ID (OTel) & Token Stats"),
    "R10":        (r10_openclaw_toolcall, False, "OpenClaw Tool Call (12 official cases)"),
    "R11":        (r11_accuracy,          False, "Accuracy (KVV benchmarks + evalscope)"),
    "R12":        (r12_ttft,             True,  "TTFT (6 buckets, p50/p90)"),
    "R13":        (r13_otps,             True,  "OTPS (Tier1>40 claw, Tier2>15 chat)"),
    "R14":        (r14_cache,            False, "Cache (LRU Prefix Cache)"),
    "R15_R16_R17":(r15_r16_r17_sla,     False, "Rate Limit / SLA / RTO"),
}

def main():
    p = argparse.ArgumentParser(description="Kimi K2.6 Endpoint Evaluator")
    p.add_argument("--reqs", nargs="+", default=list(REQUIREMENTS),
                   help="Requirements to run (default: all)")
    p.add_argument("--perf", action="store_true",
                   help="Enable TTFT (R12) and OTPS (R13) sections")
    p.add_argument("--perf-samples", type=int, default=10, metavar="N",
                   help="Samples per TTFT/OTPS bucket (default: 10, spec: 100)")
    p.add_argument("--eos-runs", type=int, default=20, metavar="N",
                   help="EOS repetitions (default: 20, spec: 1000)")
    p.add_argument("--full-accuracy", action="store_true",
                   help="Run full evalscope benchmarks (slow, requires pip install evalscope[api])")
    p.add_argument("--accuracy-limit", type=int, default=10,
                   help="evalscope sample limit per benchmark (default: 10)")
    p.add_argument("--out", default="reports", help="Output directory")
    args = p.parse_args()

    console.print()
    console.rule("[bold white]Kimi K2.6 Endpoint Evaluation[/]")
    console.print(f"  Endpoint  : [cyan]{ENDPOINT}[/]")
    console.print(f"  Model     : [cyan]{MODEL}[/]")
    console.print(f"  Reqs      : [cyan]{args.reqs}[/]")
    console.print()

    for req_key in args.reqs:
        req_key = req_key.upper()
        if req_key not in REQUIREMENTS:
            console.print(f"  [yellow]Unknown requirement {req_key!r} — skipping[/]")
            continue
        mod, needs_perf, label = REQUIREMENTS[req_key]
        if needs_perf and not args.perf:
            console.print(f"  [dim]{req_key} ({label}) skipped — pass --perf to enable[/]")
            continue
        if req_key == "R6":
            mod.run(n_runs=args.eos_runs)
        elif req_key == "R11":
            mod.run(run_full=args.full_accuracy, evalscope_limit=args.accuracy_limit)
        elif req_key == "R12":
            mod.run(n_samples=args.perf_samples)
        elif req_key == "R13":
            mod.run(n_samples=args.perf_samples)
        else:
            mod.run()

    results = get_results()
    console.rule("[bold white]EVALUATION REPORT[/]")
    console.print(f"  Endpoint : [cyan]{ENDPOINT}[/]")
    console.print(f"  Model    : [cyan]{MODEL}[/]")
    print_report(results)

    # Save JSON report
    Path(args.out).mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(args.out) / f"eval_{ts}.json"
    with open(path, "w") as f:
        json.dump({"endpoint": ENDPOINT, "model": MODEL,
                   "timestamp": ts, "results": results}, f, indent=2)
    console.print(f"  → {path}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
run_benchmarks.py — Stage 5: Full Accuracy Benchmarking
=========================================================
Runs OCRBench, AIME 2025, and MMMU Pro against the endpoint
and compares scores against official targets (±2% tolerance).

Usage:
    python run_benchmarks.py                         # all benchmarks, both modes
    python run_benchmarks.py --benchmark aime        # AIME only
    python run_benchmarks.py --benchmark aime --mode think
    python run_benchmarks.py --benchmark aime --passes 3   # majority vote
    python run_benchmarks.py --limit 50              # dev/smoke run
    python run_benchmarks.py --benchmark ocr,mmmu    # comma-separated

Official targets (Stage 1 Section H, ±2% tolerance):
    OCRBench   think=91%    non-think=92%
    AIME 2025  think=98.4%  non-think=70.5%
    MMMU Pro   think=78.8%  non-think=74.9%

Prerequisites:
    pip install datasets huggingface_hub

Notes:
    - AIME: text-only, runs immediately
    - OCRBench + MMMU: require image support (fix IM-003/IM-004 first)
    - Results saved to ./reports/ alongside existing eval reports
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

for var in ("EVAL_ENDPOINT_URL", "EVAL_API_KEY"):
    if not os.getenv(var):
        print(f"ERROR: {var} not set.\n  export {var}=...")
        sys.exit(1)

from core.bench_common import TARGETS, TOLERANCE, save_results
from core.common import console, ENDPOINT, MODEL


def print_final_report(all_scores: list):
    console.print()
    console.rule("[bold white]STAGE 5 — ACCURACY BENCHMARK REPORT[/]")
    console.print(f"  Endpoint : [cyan]{ENDPOINT}[/]")
    console.print(f"  Model    : [cyan]{MODEL}[/]")
    console.print()

    from rich.table import Table
    table = Table(title="Accuracy Results vs Official Targets", show_lines=True)
    table.add_column("Benchmark",  style="cyan")
    table.add_column("Mode",       style="white")
    table.add_column("Score",      justify="right")
    table.add_column("Target",     justify="right")
    table.add_column("Delta",      justify="right")
    table.add_column("95% CI",     justify="center")
    table.add_column("Verdict",    justify="center")

    for s in all_scores:
        verdict = "[green]PASS[/]" if s["passed"] else "[bold red]FAIL[/]"
        ci      = f"[{s['ci_95_lower']}%, {s['ci_95_upper']}%]"
        delta   = f"{s['delta_pct']:+.1f}%"
        caveat  = " ⚠" if s.get("image_caveat") else ""
        table.add_row(
            s["benchmark"] + caveat,
            s["mode"],
            f"{s['accuracy_pct']:.1f}%",
            f"{s['target_pct']:.1f}%",
            delta,
            ci,
            verdict,
        )
    console.print(table)

    failures = [s for s in all_scores if not s["passed"]]
    if failures:
        console.print()
        console.rule("[bold red]FAILURES[/]")
        for f in failures:
            console.print(
                f"  [red]✗[/] [{f['benchmark']} {f['mode']}] "
                f"{f['accuracy_pct']:.1f}% vs target {f['target_pct']:.1f}% "
                f"(delta {f['delta_pct']:+.1f}%) — SERVICE UNAVAILABLE"
            )
    else:
        console.print("\n  [green]✅ All benchmarks within spec tolerance.[/]")

    caveats = [s for s in all_scores if s.get("image_caveat")]
    if caveats:
        console.print()
        console.print("  [yellow]⚠  Image caveat applies to:[/]")
        for s in caveats:
            console.print(f"     {s['benchmark']} [{s['mode']}]: {s['image_caveat']}")
        console.print("  Scores are NOT spec-compliant until IM-003/IM-004 (image) is fixed.")


def main():
    p = argparse.ArgumentParser(
        description="Stage 5: Full accuracy benchmark runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--benchmark", default="all",
                   help="Benchmarks: all | aime | ocr | mmmu | comma-separated (default: all)")
    p.add_argument("--mode", choices=["think", "non-think", "both"], default="both",
                   help="Which thinking mode to test (default: both)")
    p.add_argument("--passes", type=int, default=1,
                   help="AIME passes for majority vote — spec recommends 3 (default: 1)")
    p.add_argument("--limit", type=int, default=None,
                   help="Sample limit per benchmark for dev/smoke runs")
    p.add_argument("--delay", type=float, default=0.5,
                   help="Seconds between requests (default: 0.5)")
    p.add_argument("--dataset", default=None,
                   help="Path to custom aime2025.json (default: built-in problems)")
    p.add_argument("--results-dir", default="./reports",
                   help="Output directory (default: ./reports)")
    args = p.parse_args()

    benchmarks = (["aime", "ocr", "mmmu"] if args.benchmark == "all"
                  else args.benchmark.split(","))
    modes      = (["think", "non-think"] if args.mode == "both" else [args.mode])

    console.print()
    console.rule("[bold white]Stage 5 — Accuracy Benchmarking[/]")
    console.print(f"  Endpoint   : [cyan]{ENDPOINT}[/]")
    console.print(f"  Model      : [cyan]{MODEL}[/]")
    console.print(f"  Benchmarks : [cyan]{benchmarks}[/]")
    console.print(f"  Modes      : [cyan]{modes}[/]")
    console.print(f"  Limit      : [cyan]{args.limit or 'full dataset'}[/]")
    console.print(f"  Delay      : [cyan]{args.delay}s[/]")
    console.print()

    start      = time.perf_counter()
    all_scores = []

    # ── AIME ──────────────────────────────────────────────────────────────────
    if "aime" in benchmarks:
        from benchmarks.run_aime import run, BUILTIN_PROBLEMS
        if args.dataset:
            with open(args.dataset) as f:
                dataset = json.load(f)
            console.print(f"  AIME: loaded {len(dataset)} problems from {args.dataset}")
        else:
            dataset = BUILTIN_PROBLEMS
            console.print(
                "  [yellow]AIME: using built-in problems.[/] "
                "For spec-compliant results, provide --dataset path/to/aime2025.json"
            )
        if args.limit:
            dataset = dataset[:args.limit]
        for mode in modes:
            score = run(dataset, mode, args.passes, args.results_dir, args.delay)
            all_scores.append(score)

    # ── OCRBench ──────────────────────────────────────────────────────────────
    if "ocr" in benchmarks:
        from benchmarks.run_ocrbench import run, load_dataset
        dataset = load_dataset(args.limit)
        for mode in modes:
            score = run(dataset, mode, args.results_dir, args.delay)
            all_scores.append(score)

    # ── MMMU Pro ──────────────────────────────────────────────────────────────
    if "mmmu" in benchmarks:
        from benchmarks.run_mmmu import run, load_dataset
        dataset = load_dataset(args.limit)
        for mode in modes:
            score = run(dataset, mode, args.results_dir, args.delay)
            all_scores.append(score)

    # ── consolidated report ────────────────────────────────────────────────────
    print_final_report(all_scores)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_results(
        {"run_at": datetime.now(timezone.utc).isoformat(),
         "stage": 5, "tolerance": TOLERANCE, "targets": TARGETS,
         "scores": all_scores,
         "overall_pass": all(s["passed"] for s in all_scores)},
        args.results_dir,
        f"stage5_accuracy_{ts}.json",
    )

    elapsed = time.perf_counter() - start
    console.print(f"\n  Total elapsed: [cyan]{elapsed/60:.1f} minutes[/]")


if __name__ == "__main__":
    main()

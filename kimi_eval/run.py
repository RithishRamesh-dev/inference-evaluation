#!/usr/bin/env python3
"""
run.py — K2.6 Test Results
===========================
Output format matches the official K2.6 Test Results PDF:
  一、工程验收 / Interface Results  (Tests 1-9)
  二、精度验收 / Accuracy Results   (2.1 Think Mode, 2.2 Non-Think Mode)

Usage:
  python run.py                          # Interface + accuracy smoke only
  python run.py --section accuracy --aime-direct
                                         # AIME 30 problems + K2VV 12 cases (no evalscope)
  python run.py --eos-runs 1000          # Full 1000-run EOS test
  python run.py --full-accuracy          # Full evalscope (OCR + MMMU + AIME + K2VV)
  python run.py --section interface      # Interface tests only
  python run.py --section accuracy       # Accuracy only (smoke)
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

from core.client import ENDPOINT, MODEL
from tests.interface_results import run as run_interface
from tests.accuracy_results  import run as run_accuracy


def print_summary(i_results, a_results):
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    if i_results:
        i_pass = sum(1 for r in i_results if r["passed"])
        i_fail = len(i_results) - i_pass
        pct    = 100 * i_pass // len(i_results) if i_results else 0
        print(f"\n一、工程验收 / Interface Results")
        print(f"  {i_pass} PASS / {i_fail} FAIL  ({pct}%)")
        print()
        req_names = {
            1: "Thinking Mode Activation",  2: "Parameter Defaults",
            3: "max_tokens",                4: "System Prompt",
            5: "Interleaved Thinking",       6: "EOS Suppression",
            7: "Image Input Test Cases",     8: "Trace ID (OpenTelemetry)",
            9: "Token Statistics",
        }
        by_num = {}
        for r in i_results:
            by_num.setdefault(r["num"], []).append(r)
        for num in sorted(by_num):
            tests    = by_num[num]
            all_pass = all(t["passed"] for t in tests)
            fails    = [t for t in tests if not t["passed"]]
            icon     = "✓" if all_pass else "✗"
            status   = "PASS" if all_pass else f"FAIL ({len(fails)} sub-test(s))"
            print(f"  {icon}  {num}. {req_names.get(num,''):<30}  {status}")
            for t in fails:
                print(f"       ✗ {t['name']}")
                print(f"         {t['detail'][:80]}")

    if a_results:
        print(f"\n二、精度验收 / Accuracy Results")
        print(f"\n  {'':3}  {'Dataset':<30} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
        print(f"  {'':3}  {'─'*30} {'─'*9}   {'─'*9}   {'─'*8}")
        current_section = None
        for r in a_results:
            if r["section"] != current_section:
                current_section = r["section"]
                label = "2.1 Think Mode" if current_section == "2.1" else "2.2 Non-Think Mode"
                print(f"\n  [{label}]")
            icon  = "✓" if r["passed"] else "✗" if r["result"] is not None else "?"
            r_s   = f"{r['result']:.1f}%" if r["result"] is not None else "PENDING"
            d_s   = f"{r['diff']:+.1f}%"  if r["diff"] is not None   else "—"
            print(f"  {icon}  {r['dataset']:<30} {r['official']:>8.1f}%   {r_s:>9}   {d_s:>8}")


def save(i_results, a_results, out_dir):
    Path(out_dir).mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(out_dir) / f"eval_{ts}.json"
    with open(path, "w") as f:
        json.dump({"endpoint": ENDPOINT, "model": MODEL, "timestamp": ts,
                   "interface_results": i_results, "accuracy_results": a_results},
                  f, indent=2, default=str)
    print(f"\n  Report → {path}")


def main():
    p = argparse.ArgumentParser(description="K2.6 Test Results")
    p.add_argument("--section", choices=["interface", "accuracy", "all"],
                   default="all")
    p.add_argument("--eos-runs", type=int, default=20,
                   help="EOS repetitions (default: 20, spec requires 1000)")
    p.add_argument("--aime-direct", action="store_true",
                   help="Run AIME 2025 (30 problems) + K2VV ToolCall (12 cases) directly. "
                        "~30-45 min. No evalscope needed.")
    p.add_argument("--full-accuracy", action="store_true",
                   help="Run all benchmarks via evalscope (OCR, MMMU, AIME, K2VV). "
                        "Requires: pip install evalscope[api]")
    p.add_argument("--workers", type=int, default=None,
                   help="Parallel workers per benchmark (default: per-benchmark auto)")
    p.add_argument("--accuracy-limit", type=int, default=None,
                   help="evalscope sample limit per benchmark (default: full dataset)")
    p.add_argument("--out", default="reports")
    args = p.parse_args()

    i_results = []
    a_results = []

    if args.section in ("interface", "all"):
        i_results = run_interface(n_eos_runs=args.eos_runs)

    if args.section in ("accuracy", "all"):
        a_results = run_accuracy(
            run_full=args.full_accuracy,
            run_aime_direct=args.aime_direct,
            evalscope_limit=args.accuracy_limit,
            workers=args.workers,
        )

    print_summary(i_results, a_results)
    save(i_results, a_results, args.out)


if __name__ == "__main__":
    main()
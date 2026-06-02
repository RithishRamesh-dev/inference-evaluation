#!/usr/bin/env python3
"""
run.py — K2.6 Test Results
===========================
Output format matches the official K2.6 Test Results PDF exactly:
  一、工程验收 / Interface Results  (Requirements 1-9)
  二、精度验收 / Accuracy Results   (2.1 Think Mode, 2.2 Non-Think Mode)

Usage:
  python run.py                         # Interface tests + accuracy smoke
  python run.py --eos-runs 1000         # Full 1000-run EOS test (spec compliant)
  python run.py --full-accuracy         # Run full evalscope benchmarks
  python run.py --section interface     # Interface tests only
  python run.py --section accuracy      # Accuracy tests only
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

def _sep(char="═", width=72): return char * width


def print_summary(interface_results, accuracy_results):
    print()
    print(_sep())
    print("SUMMARY")
    print(_sep())

    # Interface summary
    i_pass = sum(1 for r in interface_results if r["passed"])
    i_fail = sum(1 for r in interface_results if not r["passed"])
    print(f"\n一、工程验收 / Interface Results")
    print(f"  {i_pass} PASS / {i_fail} FAIL  ({100*i_pass//(i_pass+i_fail) if interface_results else 0}%)")
    print()
    # Group by requirement number
    by_num = {}
    for r in interface_results:
        n = r["num"]
        by_num.setdefault(n, []).append(r)
    req_names = {
        1: "Thinking Mode Activation",
        2: "Parameter Defaults",
        3: "max_tokens",
        4: "System Prompt",
        5: "Interleaved Thinking",
        6: "EOS Suppression",
        7: "Image Input",
        8: "Trace ID (OpenTelemetry)",
        9: "Token Statistics",
    }
    for num in sorted(by_num):
        tests = by_num[num]
        all_pass = all(t["passed"] for t in tests)
        icon = "✓" if all_pass else "✗"
        fail_count = sum(1 for t in tests if not t["passed"])
        status = "PASS" if all_pass else f"FAIL ({fail_count} sub-test(s))"
        print(f"  {icon}  Req {num}: {req_names.get(num, '')}  — {status}")
        if not all_pass:
            for t in tests:
                if not t["passed"]:
                    print(f"       ✗ {t['name']}: {t['detail'][:80]}")

    # Accuracy summary
    if accuracy_results:
        print(f"\n二、精度验收 / Accuracy Results")
        for r in accuracy_results:
            icon = "✓" if r["passed"] else "✗"
            score_str = f"{r['result']:.1f}%" if r["result"] is not None else "PENDING"
            diff_str  = f"{r['diff']:+.1f}%" if r["diff"] is not None else "—"
            print(f"  {icon}  [{r['section']}] {r['dataset']:<28} "
                  f"official={r['official']:.1f}%  result={score_str}  diff={diff_str}")


def save_report(interface_results, accuracy_results, out_dir):
    Path(out_dir).mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(out_dir) / f"eval_{ts}.json"
    with open(path, "w") as f:
        json.dump({
            "endpoint": ENDPOINT,
            "model":    MODEL,
            "timestamp": ts,
            "interface_results": interface_results,
            "accuracy_results": accuracy_results,
        }, f, indent=2, default=str)
    print(f"\n  Report saved → {path}")


def main():
    p = argparse.ArgumentParser(description="K2.6 Test Results")
    p.add_argument("--section", choices=["interface", "accuracy", "all"],
                   default="all", help="Which section to run (default: all)")
    p.add_argument("--eos-runs", type=int, default=20,
                   help="EOS repetitions (default: 20, spec: 1000)")
    p.add_argument("--full-accuracy", action="store_true",
                   help="Run full evalscope benchmarks (slow)")
    p.add_argument("--accuracy-limit", type=int, default=None,
                   help="evalscope sample limit (default: full dataset)")
    p.add_argument("--out", default="reports", help="Report output directory")
    args = p.parse_args()

    interface_results = []
    accuracy_results  = []

    if args.section in ("interface", "all"):
        interface_results = run_interface(n_eos_runs=args.eos_runs)

    if args.section in ("accuracy", "all"):
        accuracy_results = run_accuracy(
            run_full=args.full_accuracy,
            evalscope_limit=args.accuracy_limit,
        )

    print_summary(interface_results, accuracy_results)
    save_report(interface_results, accuracy_results, args.out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
run.py — Kimi K2.6 Endpoint Evaluation
=======================================
Usage:
  python run.py                              # all sections (no perf)
  python run.py --sections A B G            # specific sections
  python run.py --perf                       # include TTFT + OTPS
  python run.py --perf --perf-samples 100 --eos-runs 1000   # full spec

Required env vars:
  EVAL_ENDPOINT_URL   https://your-endpoint/v1
  EVAL_API_KEY        your-api-key
  EVAL_MODEL          model name (default: kimi-k2)
"""
import argparse
import os
import sys

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

for v in ("EVAL_ENDPOINT_URL", "EVAL_API_KEY"):
    if not os.getenv(v):
        print(f"ERROR: {v} not set.\n  export {v}=...")
        sys.exit(1)

from core.common import console, print_report, ENDPOINT, MODEL
from sections import section_a, section_b, section_c, section_d
from sections import section_e, section_f, section_g, section_h
from sections import section_i_to_o as ito

SECTIONS = {
    "A": (section_a.run,    False, "Thinking Mode"),
    "B": (section_b.run,    False, "Parameter Defaults"),
    "C": (section_c.run,    False, "System Prompt Injection"),
    "D": (section_d.run,    False, "Interleaved Thinking"),
    "E": (section_e.run,    False, "EOS / Special Token"),
    "F": (section_f.run,    False, "Image Input"),
    "G": (section_g.run,    False, "Tool Calling"),
    "H": (section_h.run,    False, "Accuracy (Smoke)"),
    "I": (ito.run_i,        True,  "TTFT Performance"),
    "J": (ito.run_j,        True,  "OTPS Performance"),
    "K": (ito.run_k,        False, "Cache Behavior"),
    "L": (ito.run_l,        False, "Rate Limiting"),
    "M": (ito.run_m,        False, "SLA Availability"),
    "N": (ito.run_n,        False, "RTO Observability"),
    "O": (ito.run_o,        False, "Load Smoke Test"),
}

def main():
    p = argparse.ArgumentParser(description="Kimi K2.6 endpoint evaluator")
    p.add_argument("--sections", nargs="+", default=list(SECTIONS),
                   help="Sections to run (default: all). E.g. --sections A B C")
    p.add_argument("--perf", action="store_true",
                   help="Enable TTFT (I) and OTPS (J) sections")
    p.add_argument("--perf-samples", type=int, default=20, metavar="N",
                   help="Samples per TTFT/OTPS bucket (spec requires 100)")
    p.add_argument("--eos-runs", type=int, default=20, metavar="N",
                   help="EOS repetitions (spec requires 1000)")
    args = p.parse_args()

    console.print()
    console.rule("[bold white]Kimi K2.6 Endpoint Evaluation[/]")
    console.print(f"  Endpoint : [cyan]{ENDPOINT}[/]")
    console.print(f"  Model    : [cyan]{MODEL}[/]")
    console.print(f"  Sections : [cyan]{[s.upper() for s in args.sections]}[/]")
    console.print()

    for sec in [s.upper() for s in args.sections]:
        if sec not in SECTIONS:
            console.print(f"  [yellow]Unknown section {sec!r} — skipping[/]")
            continue
        fn, needs_perf, label = SECTIONS[sec]
        if needs_perf and not args.perf:
            console.print(f"  [dim]Section {sec} ({label}) skipped — pass --perf to enable[/]")
            continue
        if sec == "E":    fn(n_runs=args.eos_runs)
        elif sec == "I":  fn(n=args.perf_samples)
        elif sec == "J":  fn(n=args.perf_samples)
        else:             fn()

    print_report({"Endpoint": ENDPOINT, "Model": MODEL,
                  "Perf": str(args.perf), "EOS runs": str(args.eos_runs)})

if __name__ == "__main__":
    main()

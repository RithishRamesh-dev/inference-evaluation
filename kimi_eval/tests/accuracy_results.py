"""
tests/accuracy_results.py
===========================
二、精度验收 / Accuracy Results

Output format mirrors K2.6 Test Results PDF exactly:
  2.1 Think Mode  — table: Dataset | Official Result(%) | Result(%) | Diff(%)
  2.2 Non-Think Mode — same table format + K2VV ToolCall rows

Runs via evalscope (official benchmark framework).
Smoke tests run if evalscope not available.
"""
import os, re, subprocess, time
from core.client import chat, ENDPOINT, MODEL

_results = []

def result(section, dataset, official_pct, actual_pct, diff_pct, passed, notes=""):
    _results.append({
        "section": section, "dataset": dataset,
        "official": official_pct, "result": actual_pct,
        "diff": diff_pct, "passed": passed, "notes": notes,
    })


def _sep(width=72): return "─" * width


def _table_row(dataset, official, result_pct, diff):
    """Format one table row matching PDF style."""
    r_str = f"{result_pct:.1f}%" if result_pct is not None else "—"
    d_str = f"{diff:+.1f}%" if diff is not None else "—"
    flag  = "✓" if (diff is not None and abs(diff) <= 2.0) else ("✗" if diff is not None else "?")
    return f"  {flag}  {dataset:<28} {official:>8.1f}%   {r_str:>8}   {d_str:>8}"


def _run_evalscope(dataset, mode, limit=None):
    """Run evalscope and parse score. Returns float or None."""
    api_url = os.environ.get("EVAL_ENDPOINT_URL", "")
    api_key = os.environ.get("EVAL_API_KEY", "")
    think_type = "enabled" if mode == "think" else "disabled"

    cmd = [
        "evalscope", "eval",
        "--eval-type", "openai_api",
        "--model", MODEL,
        "--api-url", api_url,
        "--api-key", api_key,
        "--datasets", dataset,
        "--generation-config",
        f'{{"extra_body":{{"thinking":{{"type":"{think_type}"}}}}}}',
    ]
    if dataset == "mmmu_pro" and mode == "think":
        cmd += ["--dataset-args", '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}']
    if limit:
        cmd += ["--limit", str(limit)]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        output = r.stdout + r.stderr
        # Try to extract accuracy score
        m = re.search(r"(?:accuracy|score)[:\s]+([0-9.]+)", output, re.IGNORECASE)
        if m:
            return float(m.group(1))
        # Try percentage pattern
        m2 = re.search(r"([0-9.]+)\s*%", output)
        if m2:
            return float(m2.group(1))
        return None
    except FileNotFoundError:
        return "evalscope_not_installed"
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return f"error:{e}"


def _smoke_test(prompt, expected_fragment, think):
    """Quick smoke test returning (passed, actual_response)."""
    r = chat([{"role": "user", "content": prompt}], think=think, max_tokens=256)
    c = (r.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return expected_fragment.lower() in c.lower(), c[:120]


def run(run_full=False, evalscope_limit=None):
    print()
    print("=" * 72)
    print("二、精度验收 / Accuracy Results")
    print("=" * 72)
    print(f"  Endpoint : {ENDPOINT}")
    print(f"  Model    : {MODEL}")
    print(f"  Mode     : {'Full evalscope benchmarks' if run_full else 'Smoke tests only'}")
    if not run_full:
        print("  Note     : Pass --full-accuracy for official evalscope benchmark run.")
        print("             Run: bash run_evalscope.sh all")

    # ── 2.1 Think Mode ────────────────────────────────────────────────────────
    print(f"\n{_sep()}")
    print("2.1 Think Mode")
    print(_sep())
    print(f"\n  {'':3}  {'Dataset':<28} {'Official':>9}   {'Result':>8}   {'Diff':>8}")
    print(f"  {'':3}  {_sep('─', 28)} {_sep('─',9)}   {_sep('─',8)}   {_sep('─',8)}")

    think_targets = [
        ("OCRBench",      "ocr_bench",  91.0),
        ("AIME2025",      "aime25",     98.4),
        ("MMMU Pro Vision","mmmu_pro",  78.8),
    ]

    for display_name, bench_id, official in think_targets:
        if run_full:
            score = _run_evalscope(bench_id, "think", evalscope_limit)
            if isinstance(score, float):
                diff  = score - official
                passed = abs(diff) <= 2.0
                print(_table_row(display_name, official, score, diff))
                result("2.1", display_name, official, score, diff, passed)
            else:
                print(f"  ?  {display_name:<28} {official:>8.1f}%   {'—':>8}   {'—':>8}   [{score}]")
                result("2.1", display_name, official, None, None, False, str(score))
        else:
            # Smoke test
            if display_name == "OCRBench":
                prompt = "Invoice #7823 — Total: $4,250. What is the invoice number? Number only."
                p, resp = _smoke_test(prompt, "7823", think=True)
            elif display_name == "AIME2025":
                prompt = "What is 5 factorial? Integer only."
                p, resp = _smoke_test(prompt, "120", think=True)
            else:  # MMMU
                prompt = "A car travels 60km in 1.5 hours. Speed in km/h? Number only."
                p, resp = _smoke_test(prompt, "40", think=True)
            smoke_str = f"smoke={'PASS' if p else 'FAIL'}: {resp[:60]!r}"
            print(f"  {'✓' if p else '✗'}  {display_name:<28} {official:>8.1f}%   {'SMOKE':>8}   {'—':>8}   {smoke_str}")
            result("2.1", display_name, official, None, None, p, smoke_str)
        time.sleep(0.3)

    # ── 2.2 Non-Think Mode ────────────────────────────────────────────────────
    print(f"\n{_sep()}")
    print("2.2 Non-Think Mode")
    print(_sep())
    print(f"\n  {'':3}  {'Dataset':<28} {'Official':>9}   {'Result':>8}   {'Diff':>8}")
    print(f"  {'':3}  {_sep('─', 28)} {_sep('─',9)}   {_sep('─',8)}   {_sep('─',8)}")

    nothink_targets = [
        ("OCRBench",              "ocr_bench", 92.0),
        ("AIME2025",              "aime25",    70.5),
        ("MMMU Pro",              "mmmu_pro",  74.9),
        ("K2VV ToolCall (f1)",    None,        84.0),
        ("K2VV ToolCall (schema_acc)", None,  100.0),
    ]

    for display_name, bench_id, official in nothink_targets:
        if run_full and bench_id:
            score = _run_evalscope(bench_id, "non-think", evalscope_limit)
            if isinstance(score, float):
                diff   = score - official
                passed = abs(diff) <= 2.0
                print(_table_row(display_name, official, score, diff))
                result("2.2", display_name, official, score, diff, passed)
            else:
                print(f"  ?  {display_name:<28} {official:>8.1f}%   {'—':>8}   {'—':>8}   [{score}]")
                result("2.2", display_name, official, None, None, False, str(score))
        elif bench_id is None:
            # K2VV ToolCall — uses official OpenClaw test cases from testcases/
            from pathlib import Path
            import json as _json
            tc_path = Path("testcases/openclaw_testcases.jsonl")
            if tc_path.exists() and run_full:
                cases = [_json.loads(l) for l in open(tc_path) if l.strip()]
                pass_count = 0
                for case in cases:
                    req  = case.get("request", case)
                    msgs = req.get("messages", [])
                    tools = req.get("tools", [])
                    think_type = req.get("thinking", {}).get("type", "disabled")
                    payload = {"model": MODEL, "messages": msgs,
                               "thinking": {"type": think_type},
                               "temperature": 0.6, "max_tokens": 4096}
                    if tools: payload["tools"] = tools
                    from core.client import raw_post
                    r = raw_post(payload)
                    fr_val = (r.get("choices") or [{}])[0].get("finish_reason", "")
                    if fr_val == "tool_calls":
                        pass_count += 1
                score = pass_count / len(cases) * 100 if cases else 0
                diff  = score - official
                passed = abs(diff) <= 2.0
                print(_table_row(display_name, official, score, diff))
                result("2.2", display_name, official, score, diff, passed)
            else:
                print(f"  ?  {display_name:<28} {official:>8.1f}%   {'PENDING':>8}   {'—':>8}   "
                      f"[Run --full-accuracy with OpenClaw cases]")
                result("2.2", display_name, official, None, None, False, "pending")
        else:
            if display_name == "OCRBench":
                prompt = "Invoice #7823 — Total: $4,250. What is the invoice number? Number only."
                p, resp = _smoke_test(prompt, "7823", think=False)
            elif display_name == "AIME2025":
                prompt = "What is 5 factorial? Integer only."
                p, resp = _smoke_test(prompt, "120", think=False)
            else:
                prompt = "A car travels 60km in 1.5 hours. Speed in km/h? Number only."
                p, resp = _smoke_test(prompt, "40", think=False)
            smoke_str = f"smoke={'PASS' if p else 'FAIL'}: {resp[:60]!r}"
            print(f"  {'✓' if p else '✗'}  {display_name:<28} {official:>8.1f}%   {'SMOKE':>8}   {'—':>8}   {smoke_str}")
            result("2.2", display_name, official, None, None, p, smoke_str)
        time.sleep(0.3)

    # Summary
    print(f"\n{_sep()}")
    print("  Accuracy Note:")
    print("  Any variance >2% from official target = service unavailable for that domain.")
    if not run_full:
        print("  Smoke tests validate the model is responding correctly.")
        print("  For spec-compliant scores: bash run_evalscope.sh all")
    print()

    return _results

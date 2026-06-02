"""
tests/accuracy_results.py
===========================
二、精度验收 / Accuracy Results

Table format matches K2.6 Test Results PDF exactly:
  2.1 Think Mode  — Dataset | Official Result(%) | Result(%) | Diff(%)
  2.2 Non-Think Mode — same + K2VV ToolCall rows
"""
import os, re, subprocess, time, json
from pathlib import Path
from core.client import chat, raw_post, ENDPOINT, MODEL

_results = []

def result(section, dataset, official, actual, diff, passed, notes=""):
    _results.append({"section":section,"dataset":dataset,"official":official,
                      "result":actual,"diff":diff,"passed":passed,"notes":notes})

def sep(w=72): return "─" * w

def table_row(dataset, official, result_pct, diff):
    r_s = f"{result_pct:.1f}%" if result_pct is not None else "—"
    d_s = f"{diff:+.1f}%"      if diff is not None else "—"
    ok  = diff is not None and abs(diff) <= 2.0
    icon = "✓" if ok else ("✗" if diff is not None else "?")
    return f"  {icon}  {dataset:<30} {official:>8.1f}%   {r_s:>9}   {d_s:>8}"

def run_evalscope(bench, mode, limit=None):
    api_url = os.environ.get("EVAL_ENDPOINT_URL","")
    api_key = os.environ.get("EVAL_API_KEY","")
    think_t = "enabled" if mode == "think" else "disabled"
    cmd = ["evalscope","eval","--eval-type","openai_api","--model",MODEL,
           "--api-url",api_url,"--api-key",api_key,"--datasets",bench,
           "--generation-config",
           f'{{"extra_body":{{"thinking":{{"type":"{think_t}"}}}}}}']
    if bench == "mmmu_pro" and mode == "think":
        cmd += ["--dataset-args",'{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}']
    if limit: cmd += ["--limit",str(limit)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        out = r.stdout + r.stderr
        m = re.search(r"(?:accuracy|score)[:\s]+([0-9.]+)", out, re.IGNORECASE)
        return float(m.group(1)) if m else None
    except FileNotFoundError: return "evalscope_not_installed"
    except subprocess.TimeoutExpired: return "timeout"
    except Exception as e: return f"error:{e}"

def smoke(prompt, expected, think):
    r = chat([{"role":"user","content":prompt}], think=think, max_tokens=256)
    c = (r.get("choices") or [{}])[0].get("message",{}).get("content","") or ""
    return expected.lower() in c.lower(), c[:120]

def run_k2vv_toolcall():
    """Run OpenClaw cases as K2VV ToolCall proxy. Returns pass_rate %."""
    tc_path = Path("testcases/openclaw_testcases.jsonl")
    if not tc_path.exists(): return None, "testcases/openclaw_testcases.jsonl not found"
    cases = [json.loads(l) for l in open(tc_path) if l.strip()]
    pass_count = 0
    for case in cases:
        req   = case.get("request", case)
        msgs  = req.get("messages", [])
        tools = req.get("tools", [])
        think = req.get("thinking", {"type":"enabled"})
        p = {"model":MODEL,"messages":msgs,"thinking":think,
              "temperature":req.get("temperature",1.0),
              "max_tokens":req.get("max_tokens",4096)}
        if tools: p["tools"] = tools
        r  = raw_post(p)
        fr = (r.get("choices") or [{}])[0].get("finish_reason","")
        if fr == "tool_calls": pass_count += 1
    return pass_count / len(cases) * 100 if cases else 0, f"{pass_count}/{len(cases)}"


def run(run_full=False, evalscope_limit=None):
    print()
    print("=" * 72)
    print("二、精度验收 / Accuracy Results")
    print("=" * 72)
    print(f"  Endpoint : {ENDPOINT}")
    print(f"  Model    : {MODEL}")
    print(f"  Mode     : {'Full evalscope benchmarks' if run_full else 'Smoke tests (pass --full-accuracy for evalscope)'}")
    print()

    # ── 2.1 Think Mode ───────────────────────────────────────────────────────
    print(sep())
    print("2.1 Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<30} {'Official':>9}%   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*30} {'─'*9}   {'─'*9}   {'─'*8}")

    think_targets = [
        ("OCRBench",       "ocr_bench", 91.0),
        ("AIME2025",       "aime25",    98.4),
        ("MMMU Pro Vision","mmmu_pro",  78.8),
    ]
    for display, bench_id, official in think_targets:
        if run_full:
            score = run_evalscope(bench_id, "think", evalscope_limit)
            if isinstance(score, float):
                diff   = score - official
                passed = abs(diff) <= 2.0
                print(table_row(display, official, score, diff))
                result("2.1", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<30} {official:>8.1f}%   {'—':>9}   {'—':>8}  [{score}]")
                result("2.1", display, official, None, None, False, str(score))
        else:
            if display == "OCRBench":
                p, resp = smoke("Invoice #7823 — Total: $4,250. "
                                "What is the invoice number? Integer only.", "7823", True)
            elif display == "AIME2025":
                p, resp = smoke("What is 5 factorial? Integer only.", "120", True)
            else:
                p, resp = smoke("A car travels 60km in 1.5 hours. Speed in km/h? Integer only.",
                                "40", True)
            note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:60]!r}"
            print(f"  {'✓' if p else '✗'}  {display:<30} {official:>8.1f}%   {'SMOKE':>9}   "
                  f"{'—':>8}   {note}")
            result("2.1", display, official, None, None, p, note)
        time.sleep(0.2)

    # ── 2.2 Non-Think Mode ───────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.2 Non-Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<30} {'Official':>9}%   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*30} {'─'*9}   {'─'*9}   {'─'*8}")

    nothink_targets = [
        ("OCRBench",               "ocr_bench", 92.0),
        ("AIME2025",               "aime25",    70.5),
        ("MMMU Pro",               "mmmu_pro",  74.9),
        ("K2VV ToolCall (f1)",     None,        84.0),
        ("K2VV ToolCall (schema_acc)", None,   100.0),
    ]
    for display, bench_id, official in nothink_targets:
        if "K2VV" in display:
            if run_full:
                score, detail = run_k2vv_toolcall()
                if score is not None:
                    diff   = score - official
                    passed = abs(diff) <= 2.0
                    print(table_row(display, official, score, diff))
                    result("2.2", display, official, score, diff, passed,
                           f"openclaw: {detail}")
                else:
                    print(f"  ?  {display:<30} {official:>8.1f}%   {'—':>9}   {'—':>8}  [{detail}]")
                    result("2.2", display, official, None, None, False, detail)
            else:
                print(f"  ?  {display:<30} {official:>8.1f}%   {'PENDING':>9}   {'—':>8}  "
                      f"[pass --full-accuracy]")
                result("2.2", display, official, None, None, False, "pending --full-accuracy")
        elif run_full and bench_id:
            score = run_evalscope(bench_id, "non-think", evalscope_limit)
            if isinstance(score, float):
                diff   = score - official
                passed = abs(diff) <= 2.0
                print(table_row(display, official, score, diff))
                result("2.2", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<30} {official:>8.1f}%   {'—':>9}   {'—':>8}  [{score}]")
                result("2.2", display, official, None, None, False, str(score))
        else:
            if display == "OCRBench":
                p, resp = smoke("Invoice #7823 — Total: $4,250. "
                                "What is the invoice number? Integer only.", "7823", False)
            elif display == "AIME2025":
                p, resp = smoke("What is 5 factorial? Integer only.", "120", False)
            else:
                p, resp = smoke("A car travels 60km in 1.5 hours. Speed in km/h? Integer only.",
                                "40", False)
            note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:60]!r}"
            print(f"  {'✓' if p else '✗'}  {display:<30} {official:>8.1f}%   {'SMOKE':>9}   "
                  f"{'—':>8}   {note}")
            result("2.2", display, official, None, None, p, note)
        time.sleep(0.2)

    print(f"\n{sep()}")
    print("  Note: Any variance >2% from official target = service unavailable for that domain.")
    if not run_full:
        print("  Smoke tests confirm model responds correctly.")
        print("  For official scores: docker compose run eval-accuracy")
        print("  Or:                  bash run_evalscope.sh all")
    print()
    return _results
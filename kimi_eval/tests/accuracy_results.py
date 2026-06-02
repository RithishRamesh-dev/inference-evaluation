"""
tests/accuracy_results.py
===========================
二、精度验收 / Accuracy Results

Table format matches K2.6 Test Results PDF exactly:
  2.1 Think Mode  — Dataset | Official Result(%) | Result(%) | Diff(%)
  2.2 Non-Think Mode — same + K2VV ToolCall rows

Benchmarks:
  - AIME 2025     : runs directly against our 30-problem dataset (no evalscope needed)
  - K2VV ToolCall : runs openclaw_testcases.jsonl (no evalscope needed)
  - OCRBench      : requires evalscope (pass --full-accuracy)
  - MMMU Pro      : requires evalscope (pass --full-accuracy)
"""
import json, os, re, subprocess, time
from pathlib import Path
from core.client import chat, stream, raw_post, ENDPOINT, MODEL, HEADERS
import httpx

_results = []

def result(section, dataset, official, actual, diff, passed, notes=""):
    _results.append({"section": section, "dataset": dataset,
                      "official": official, "result": actual,
                      "diff": diff, "passed": passed, "notes": notes})

def sep(w=72): return "─" * w

def row(dataset, official, result_pct, diff):
    r_s  = f"{result_pct:.1f}%" if result_pct is not None else "PENDING"
    d_s  = f"{diff:+.1f}%"      if diff is not None        else "—"
    icon = "✓" if (diff is not None and abs(diff) <= 2.0) else \
           "✗" if diff is not None else "?"
    return f"  {icon}  {dataset:<30} {official:>8.1f}%   {r_s:>9}   {d_s:>8}"


# ── AIME 2025 — direct evaluation ────────────────────────────────────────────
def run_aime(think: bool, limit: int = None) -> tuple[float, str]:
    """
    Run AIME 2025 problems against the endpoint.
    Returns (score_pct, detail_string).
    AIME answers are integers 000-999. Extract the last integer from response.
    Uses streaming to avoid TM-004 timeout on non-streaming path.
    """
    path = Path("datasets/aime2025.json")
    if not path.exists():
        return None, "datasets/aime2025.json not found"

    problems = json.load(open(path))
    if limit:
        problems = problems[:limit]

    correct = 0
    details = []
    mode    = "think" if think else "non-think"

    for i, prob in enumerate(problems):
        pid     = prob["id"]
        problem = prob["problem"]
        answer  = int(prob["answer"])

        prompt = (
            f"{problem}\n\n"
            f"Give your final answer as a single integer between 0 and 999. "
            f"Write ONLY the integer on the last line."
        )

        # Use streaming to avoid TM-004 timeout
        content_parts = []
        fr_val = None
        timed_out = False
        try:
            payload = {
                "model":       MODEL,
                "messages":    [{"role": "user", "content": prompt}],
                "thinking":    {"type": "enabled" if think else "disabled"},
                "temperature": 1.0 if think else 0.6,
                "max_tokens":  8192,
                "stream":      True,
            }
            with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                              headers=HEADERS, json=payload, timeout=300) as r:
                for line in r.iter_lines():
                    if not line.startswith("data:") or "[DONE]" in line:
                        continue
                    try:
                        chunk  = json.loads(line[5:].strip())
                        choice = (chunk.get("choices") or [{}])[0]
                        delta  = choice.get("delta", {})
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                        if choice.get("finish_reason"):
                            fr_val = choice["finish_reason"]
                    except Exception:
                        pass
        except Exception as e:
            if "timed out" in str(e).lower():
                timed_out = True
            details.append(f"{pid}: TIMEOUT")
            print(f"    [{i+1:02d}/{len(problems)}] {pid} → TIMEOUT")
            continue

        response_text = "".join(content_parts).strip()

        # Extract answer: find all integers in response, take the last one
        integers = re.findall(r'\b(\d{1,3})\b', response_text)
        predicted = int(integers[-1]) if integers else -1
        is_correct = (predicted == answer)
        if is_correct:
            correct += 1

        details.append(f"{pid}: predicted={predicted} actual={answer} "
                        f"{'✓' if is_correct else '✗'}")
        print(f"    [{i+1:02d}/{len(problems)}] {pid} → "
              f"predicted={predicted} actual={answer} "
              f"{'CORRECT' if is_correct else 'WRONG'}")

        time.sleep(0.5)

    score = correct / len(problems) * 100 if problems else 0
    detail = f"{correct}/{len(problems)} correct = {score:.1f}%"
    return score, detail


# ── K2VV ToolCall — uses openclaw_testcases.jsonl ────────────────────────────
def run_k2vv() -> tuple[float, float, str]:
    """
    Run K2VV ToolCall benchmark using official openclaw test cases.
    Returns (f1_pct, schema_acc_pct, detail).

    f1: proportion of cases that return finish_reason=tool_calls
    schema_acc: proportion with valid tool call schema (name + arguments present)
    """
    path = Path("testcases/openclaw_testcases.jsonl")
    if not path.exists():
        return None, None, "testcases/openclaw_testcases.jsonl not found"

    cases = [json.loads(l) for l in open(path) if l.strip()]
    tc_correct = 0
    schema_correct = 0

    for i, case in enumerate(cases):
        req   = case.get("request", case)
        msgs  = req.get("messages", [])
        tools = req.get("tools", [])
        think = req.get("thinking", {"type": "enabled"})
        payload = {
            "model":       MODEL,
            "messages":    msgs,
            "thinking":    think,
            "temperature": req.get("temperature", 1.0),
            "max_tokens":  req.get("max_tokens", 4096),
        }
        if tools:
            payload["tools"] = tools

        try:
            r = httpx.post(f"{ENDPOINT}/chat/completions",
                           headers=HEADERS, json=payload, timeout=180)
            data   = r.json()
            choice = (data.get("choices") or [{}])[0]
            fr_val = choice.get("finish_reason", "")
            m_obj  = choice.get("message", {}) or {}
            tcs    = m_obj.get("tool_calls") or []

            fr_ok = (fr_val == "tool_calls")
            if fr_ok:
                tc_correct += 1

            # Schema accuracy: tool_calls must have name + valid JSON arguments
            schema_ok = False
            if tcs:
                tc0  = tcs[0].get("function", {})
                name = tc0.get("name", "")
                args = tc0.get("arguments", "")
                try:
                    json.loads(args)
                    schema_ok = bool(name) and True
                except Exception:
                    schema_ok = False
            if fr_ok and schema_ok:
                schema_correct += 1

            icon = "✓" if fr_ok else "✗"
            think_t = think.get("type", "?")
            print(f"    [{i+1:02d}/{len(cases)}] {icon} "
                  f"finish={fr_val} tcs={len(tcs)} "
                  f"schema={'ok' if schema_ok else 'fail'} "
                  f"think={think_t}")
        except Exception as e:
            print(f"    [{i+1:02d}/{len(cases)}] ERROR: {e}")

        time.sleep(0.5)

    f1_pct     = tc_correct   / len(cases) * 100 if cases else 0
    schema_pct = schema_correct / len(cases) * 100 if cases else 0
    detail = (f"tool_calls={tc_correct}/{len(cases)} f1={f1_pct:.1f}%  "
              f"schema_ok={schema_correct}/{len(cases)} schema_acc={schema_pct:.1f}%")
    return f1_pct, schema_pct, detail


# ── evalscope wrapper ─────────────────────────────────────────────────────────
def run_evalscope(bench, mode, limit=None):
    api_url  = os.environ.get("EVAL_ENDPOINT_URL", "")
    api_key  = os.environ.get("EVAL_API_KEY", "")
    think_t  = "enabled" if mode == "think" else "disabled"
    cmd = [
        "evalscope", "eval",
        "--eval-type", "openai_api",
        "--model", MODEL,
        "--api-url", api_url,
        "--api-key", api_key,
        "--datasets", bench,
        "--generation-config",
        f'{{"extra_body":{{"thinking":{{"type":"{think_t}"}}}}}}',
    ]
    if bench == "mmmu_pro" and mode == "think":
        cmd += ["--dataset-args",
                '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}']
    if limit:
        cmd += ["--limit", str(limit)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        out = r.stdout + r.stderr
        m = re.search(r"(?:accuracy|score)[:\s]+([0-9.]+)", out, re.IGNORECASE)
        if m: return float(m.group(1))
        # Try percentage
        m2 = re.search(r"([0-9]{1,3}\.[0-9]+)\s*%", out)
        if m2: return float(m2.group(1))
        return None
    except FileNotFoundError:
        return "evalscope_not_installed"
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return f"error:{e}"


# ── smoke test ────────────────────────────────────────────────────────────────
def smoke(prompt, expected, think):
    r = chat([{"role": "user", "content": prompt}], think=think, max_tokens=256)
    c = (r.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return expected.lower() in c.lower(), c[:120]


# ── MAIN ──────────────────────────────────────────────────────────────────────
def run(run_full=False, run_aime_direct=False, evalscope_limit=None):
    print()
    print("=" * 72)
    print("二、精度验收 / Accuracy Results")
    print("=" * 72)
    print(f"  Endpoint : {ENDPOINT}")
    print(f"  Model    : {MODEL}")

    if run_full:
        print("  Mode     : Full — AIME direct + K2VV ToolCall + evalscope (OCR/MMMU)")
    elif run_aime_direct:
        print("  Mode     : AIME direct (30 problems) + K2VV ToolCall (12 cases)")
        print("             OCRBench / MMMU: smoke only (pass --full-accuracy for evalscope)")
    else:
        print("  Mode     : Smoke tests only")
        print("             Pass --aime-direct for AIME 30-problem + K2VV ToolCall runs")
        print("             Pass --full-accuracy for full evalscope benchmarks")

    # ── 2.1 Think Mode ───────────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.1 Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<30} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*30} {'─'*9}   {'─'*9}   {'─'*8}")

    # OCRBench Think
    if run_full:
        score = run_evalscope("ocr_bench", "think", evalscope_limit)
        if isinstance(score, float):
            diff = score - 91.0; passed = abs(diff) <= 2.0
            print(row("OCRBench", 91.0, score, diff))
            result("2.1", "OCRBench", 91.0, score, diff, passed)
        else:
            print(f"  ?  {'OCRBench':<30} {91.0:>8.1f}%   {'—':>9}   {'—':>8}  [{score}]")
            result("2.1", "OCRBench", 91.0, None, None, False, str(score))
    else:
        p, resp = smoke("Invoice number #7823. What is the invoice number? Integer only.", "7823", True)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'OCRBench':<30} {91.0:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.1", "OCRBench", 91.0, None, None, p, note)

    # AIME 2025 Think
    print(f"\n  Running AIME 2025 (think mode) — 30 problems")
    if run_full or run_aime_direct:
        score, detail = run_aime(think=True, limit=None)
        if score is not None:
            diff = score - 98.4; passed = abs(diff) <= 2.0
            print(row("AIME2025", 98.4, score, diff))
            print(f"  Detail   : {detail}")
            result("2.1", "AIME2025", 98.4, score, diff, passed, detail)
        else:
            print(f"  ?  {'AIME2025':<30} {98.4:>8.1f}%   {'—':>9}   {'—':>8}  [{detail}]")
            result("2.1", "AIME2025", 98.4, None, None, False, detail)
    else:
        p, resp = smoke("What is 5 factorial? Integer only.", "120", True)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'AIME2025':<30} {98.4:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.1", "AIME2025", 98.4, None, None, p, note)

    # MMMU Pro Vision Think
    if run_full:
        score = run_evalscope("mmmu_pro", "think", evalscope_limit)
        if isinstance(score, float):
            diff = score - 78.8; passed = abs(diff) <= 2.0
            print(row("MMMU Pro Vision", 78.8, score, diff))
            result("2.1", "MMMU Pro Vision", 78.8, score, diff, passed)
        else:
            print(f"  ?  {'MMMU Pro Vision':<30} {78.8:>8.1f}%   {'—':>9}   {'—':>8}  [{score}]")
            result("2.1", "MMMU Pro Vision", 78.8, None, None, False, str(score))
    else:
        p, resp = smoke("A car goes 60km in 1.5h. Speed in km/h? Integer only.", "40", True)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'MMMU Pro Vision':<30} {78.8:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.1", "MMMU Pro Vision", 78.8, None, None, p, note)

    # ── 2.2 Non-Think Mode ───────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.2 Non-Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<30} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*30} {'─'*9}   {'─'*9}   {'─'*8}")

    # OCRBench Non-Think
    if run_full:
        score = run_evalscope("ocr_bench", "non-think", evalscope_limit)
        if isinstance(score, float):
            diff = score - 92.0; passed = abs(diff) <= 2.0
            print(row("OCRBench", 92.0, score, diff))
            result("2.2", "OCRBench", 92.0, score, diff, passed)
        else:
            print(f"  ?  {'OCRBench':<30} {92.0:>8.1f}%   {'—':>9}   {'—':>8}  [{score}]")
            result("2.2", "OCRBench", 92.0, None, None, False, str(score))
    else:
        p, resp = smoke("Invoice number #7823. What is the invoice number? Integer only.", "7823", False)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'OCRBench':<30} {92.0:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.2", "OCRBench", 92.0, None, None, p, note)

    # AIME 2025 Non-Think
    print(f"\n  Running AIME 2025 (non-think mode) — 30 problems")
    if run_full or run_aime_direct:
        score, detail = run_aime(think=False, limit=None)
        if score is not None:
            diff = score - 70.5; passed = abs(diff) <= 2.0
            print(row("AIME2025", 70.5, score, diff))
            print(f"  Detail   : {detail}")
            result("2.2", "AIME2025", 70.5, score, diff, passed, detail)
        else:
            print(f"  ?  {'AIME2025':<30} {70.5:>8.1f}%   {'—':>9}   {'—':>8}  [{detail}]")
            result("2.2", "AIME2025", 70.5, None, None, False, detail)
    else:
        p, resp = smoke("What is 5 factorial? Integer only.", "120", False)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'AIME2025':<30} {70.5:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.2", "AIME2025", 70.5, None, None, p, note)

    # MMMU Pro Non-Think
    if run_full:
        score = run_evalscope("mmmu_pro", "non-think", evalscope_limit)
        if isinstance(score, float):
            diff = score - 74.9; passed = abs(diff) <= 2.0
            print(row("MMMU Pro", 74.9, score, diff))
            result("2.2", "MMMU Pro", 74.9, score, diff, passed)
        else:
            print(f"  ?  {'MMMU Pro':<30} {74.9:>8.1f}%   {'—':>9}   {'—':>8}  [{score}]")
            result("2.2", "MMMU Pro", 74.9, None, None, False, str(score))
    else:
        p, resp = smoke("A car goes 60km in 1.5h. Speed in km/h? Integer only.", "40", False)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'MMMU Pro':<30} {74.9:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.2", "MMMU Pro", 74.9, None, None, p, note)

    # K2VV ToolCall — always runs if run_full or run_aime_direct (uses our test cases)
    print(f"\n  Running K2VV ToolCall — 12 official OpenClaw cases")
    if run_full or run_aime_direct:
        f1, schema_acc, detail = run_k2vv()
        if f1 is not None:
            # f1 score
            diff_f1 = f1 - 84.0; passed_f1 = abs(diff_f1) <= 2.0
            print(row("K2VV ToolCall (f1)", 84.0, f1, diff_f1))
            result("2.2", "K2VV ToolCall (f1)", 84.0, f1, diff_f1, passed_f1, detail)
            # schema_acc score
            diff_sa = schema_acc - 100.0; passed_sa = abs(diff_sa) <= 2.0
            print(row("K2VV ToolCall (schema_acc)", 100.0, schema_acc, diff_sa))
            result("2.2", "K2VV ToolCall (schema_acc)", 100.0, schema_acc, diff_sa, passed_sa, detail)
            print(f"  Detail   : {detail}")
        else:
            for name, official in [("K2VV ToolCall (f1)", 84.0),
                                   ("K2VV ToolCall (schema_acc)", 100.0)]:
                print(f"  ?  {name:<30} {official:>8.1f}%   {'—':>9}   {'—':>8}  [{detail}]")
                result("2.2", name, official, None, None, False, detail)
    else:
        for name, official in [("K2VV ToolCall (f1)", 84.0),
                               ("K2VV ToolCall (schema_acc)", 100.0)]:
            print(f"  ?  {name:<30} {official:>8.1f}%   {'PENDING':>9}   {'—':>8}  "
                  f"[pass --aime-direct or --full-accuracy]")
            result("2.2", name, official, None, None, False, "pending")

    print(f"\n{sep()}")
    print("  Note: Any variance >2% from official target = service unavailable for that domain.")
    print()
    return _results
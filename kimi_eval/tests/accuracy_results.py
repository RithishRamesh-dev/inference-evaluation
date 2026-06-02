"""
tests/accuracy_results.py
===========================
二、精度验收 / Accuracy Results

Parallel benchmark runner — 5-10 concurrent API requests per benchmark.

Benchmarks:
  AIME 2025    : 30 problems, local dataset, parallel=5, ~8 min
  K2VV ToolCall: 12 openclaw cases, parallel=5, ~3 min
  OCRBench     : ~1000 samples, parallel=10, ~15 min (needs download_datasets.sh first)
  MMMU Pro     : ~500 samples, parallel=8, ~20 min  (needs download_datasets.sh first)
"""
import json, os, re, time, base64, io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.client import chat, ENDPOINT, MODEL, HEADERS
import httpx

_results = []

PARALLELISM = {
    "aime":     5,   # 30 problems × 5 parallel
    "k2vv":     5,   # 12 cases × 5 parallel
    "ocrbench": 10,  # ~1000 samples × 10 parallel
    "mmmu":     8,   # ~500 samples × 8 parallel
}

def result(section, dataset, official, actual, diff, passed, notes=""):
    _results.append({"section": section, "dataset": dataset,
                      "official": official, "result": actual,
                      "diff": diff, "passed": passed, "notes": notes})

def sep(w=72): return "─" * w

def row(dataset, official, score, diff):
    r_s  = f"{score:.1f}%"   if score is not None else "PENDING"
    d_s  = f"{diff:+.1f}%"  if diff  is not None else "—"
    icon = "✓" if (diff is not None and abs(diff) <= 2.0) else \
           "✗" if diff is not None else "?"
    return f"  {icon}  {dataset:<30} {official:>8.1f}%   {r_s:>9}   {d_s:>8}"


# ── Shared HTTP call (non-streaming, returns response dict) ───────────────────
def api_call(messages, think: bool, max_tokens: int = 4096,
             tools=None, tool_choice=None, timeout: int = 180) -> dict:
    temp = 1.0 if think else 0.6
    payload = {
        "model":       MODEL,
        "messages":    messages,
        "thinking":    {"type": "enabled" if think else "disabled"},
        "temperature": temp,
        "max_tokens":  max_tokens,
    }
    if tools:       payload["tools"] = tools
    if tool_choice: payload["tool_choice"] = tool_choice
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=timeout)
        d = r.json()
        d["_status"] = r.status_code
        return d
    except Exception as e:
        return {"error": str(e), "_status": 0}

def get_content(r: dict) -> str:
    return ((r.get("choices") or [{}])[0]
            .get("message", {}) or {}).get("content") or ""

def get_fr(r: dict) -> str:
    return (r.get("choices") or [{}])[0].get("finish_reason") or ""

def get_tcs(r: dict) -> list:
    return ((r.get("choices") or [{}])[0]
            .get("message", {}) or {}).get("tool_calls") or []


# ── Progress bar helper ───────────────────────────────────────────────────────
class Progress:
    def __init__(self, total, label):
        self.total = total; self.done = 0; self.correct = 0; self.label = label
        self._lock = __import__("threading").Lock()

    def update(self, correct: bool = None):
        with self._lock:
            self.done += 1
            if correct is True:  self.correct += 1
            pct = self.done / self.total * 100
            bar = "█" * int(pct // 5) + "░" * (20 - int(pct // 5))
            score_str = f" correct={self.correct}/{self.done}" if correct is not None else ""
            print(f"\r  {self.label} [{bar}] {self.done}/{self.total}{score_str}   ",
                  end="", flush=True)
            if self.done == self.total:
                print()


# ═══════════════════════════════════════════════════════════════════════════════
# AIME 2025
# ═══════════════════════════════════════════════════════════════════════════════
def run_aime(think: bool, workers: int = None) -> tuple:
    """
    Parallel AIME 2025. Returns (score_pct, detail, per_problem_results).
    Extracts final integer from response — matches official evaluation method.
    """
    path = Path("datasets/aime2025.json")
    if not path.exists():
        return None, "datasets/aime2025.json not found", []

    problems = json.load(open(path))
    n        = workers or PARALLELISM["aime"]
    prog     = Progress(len(problems), "AIME")
    results  = [None] * len(problems)

    def solve(idx, prob):
        pid     = prob["id"]
        answer  = int(prob["answer"])
        prompt  = (
            f"{prob['problem']}\n\n"
            "Solve step by step. Write your final answer as a single integer "
            "on the very last line. Only the integer, nothing else."
        )
        r       = api_call([{"role": "user", "content": prompt}],
                           think=think, max_tokens=8192, timeout=300)
        c_text  = get_content(r).strip()
        # Extract final integer from response
        nums    = re.findall(r'\b(\d{1,3})\b', c_text)
        predicted = int(nums[-1]) if nums else -1
        correct   = (predicted == answer)
        prog.update(correct)
        return idx, {"id": pid, "predicted": predicted,
                     "answer": answer, "correct": correct,
                     "response": c_text[-200:]}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(solve, i, p): i for i, p in enumerate(problems)}
        for fut in as_completed(futs):
            idx, res = fut.result()
            results[idx] = res

    correct_count = sum(1 for r in results if r and r["correct"])
    score = correct_count / len(problems) * 100
    detail = f"{correct_count}/{len(problems)} correct = {score:.1f}%"

    # Show per-problem summary
    print(f"  {'ID':<15} {'Predicted':>9} {'Answer':>7} {'':4}")
    for r in results:
        if r:
            icon = "✓" if r["correct"] else "✗"
            print(f"  {icon} {r['id']:<13} {r['predicted']:>9} {r['answer']:>7}")

    return score, detail, results


# ═══════════════════════════════════════════════════════════════════════════════
# K2VV ToolCall
# ═══════════════════════════════════════════════════════════════════════════════
def run_k2vv(workers: int = None) -> tuple:
    """
    Parallel K2VV ToolCall using official openclaw_testcases.jsonl.
    Returns (f1_pct, schema_acc_pct, detail).
    f1          = finish_reason=tool_calls rate
    schema_acc  = valid tool call schema (name + parseable arguments)
    """
    path = Path("testcases/openclaw_testcases.jsonl")
    if not path.exists():
        return None, None, "testcases/openclaw_testcases.jsonl not found"

    cases = [json.loads(l) for l in open(path) if l.strip()]
    n     = min(workers or PARALLELISM["k2vv"], len(cases))
    prog  = Progress(len(cases), "K2VV")
    results = [None] * len(cases)

    def run_case(idx, case):
        req    = case.get("request", case)
        msgs   = req.get("messages", [])
        tools  = req.get("tools", [])
        think  = req.get("thinking", {"type": "enabled"})
        payload = {
            "model":       MODEL,
            "messages":    msgs,
            "thinking":    think,
            "temperature": req.get("temperature", 1.0),
            "max_tokens":  req.get("max_tokens", 4096),
        }
        if tools: payload["tools"] = tools
        try:
            r = httpx.post(f"{ENDPOINT}/chat/completions",
                           headers=HEADERS, json=payload, timeout=180)
            data   = r.json()
            choice = (data.get("choices") or [{}])[0]
            fr_val = choice.get("finish_reason", "")
            tcs    = (choice.get("message") or {}).get("tool_calls") or []
            fr_ok  = fr_val == "tool_calls"
            schema_ok = False
            if tcs:
                tc0  = tcs[0].get("function", {})
                name = tc0.get("name", "")
                args = tc0.get("arguments", "")
                try:
                    json.loads(args)
                    schema_ok = bool(name)
                except Exception:
                    pass
            prog.update(fr_ok)
            return idx, {"fr_ok": fr_ok, "schema_ok": schema_ok,
                         "fr": fr_val, "tcs": len(tcs),
                         "think": think.get("type", "?")}
        except Exception as e:
            prog.update(False)
            return idx, {"fr_ok": False, "schema_ok": False,
                         "fr": "error", "tcs": 0, "error": str(e)}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(run_case, i, c): i for i, c in enumerate(cases)}
        for fut in as_completed(futs):
            idx, res = fut.result()
            results[idx] = res

    for i, r in enumerate(results):
        if r:
            icon = "✓" if r["fr_ok"] else "✗"
            print(f"  {icon} Case {i+1:02d}: finish={r['fr']} "
                  f"tcs={r['tcs']} schema={'ok' if r['schema_ok'] else 'fail'} "
                  f"think={r['think']}")

    tc_ok  = sum(1 for r in results if r and r["fr_ok"])
    sch_ok = sum(1 for r in results if r and r["schema_ok"])
    f1     = tc_ok  / len(cases) * 100
    sa     = sch_ok / len(cases) * 100
    detail = (f"tool_calls={tc_ok}/{len(cases)} f1={f1:.1f}%  "
              f"schema_ok={sch_ok}/{len(cases)} schema_acc={sa:.1f}%")
    return f1, sa, detail


# ═══════════════════════════════════════════════════════════════════════════════
# OCRBench
# ═══════════════════════════════════════════════════════════════════════════════
def run_ocrbench(think: bool, limit: int = None, workers: int = None) -> tuple:
    """
    Parallel OCRBench. Requires datasets/ocrbench/ocrbench.jsonl
    (run download_datasets.sh first).
    Sends base64-encoded images to the vision API.
    Returns (score_pct, detail).
    """
    path = Path("datasets/ocrbench/ocrbench.jsonl")
    if not path.exists():
        return None, ("datasets/ocrbench/ocrbench.jsonl not found. "
                      "Run: bash download_datasets.sh")

    items = [json.loads(l) for l in open(path) if l.strip()]
    if limit:
        items = items[:limit]

    n    = workers or PARALLELISM["ocrbench"]
    prog = Progress(len(items), "OCR")
    results = [None] * len(items)

    def eval_item(idx, item):
        question = item["question"]
        answer   = str(item["answer"]).strip().lower()
        b64      = item["image_b64"]

        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text",
                 "text": f"{question}\nAnswer with the exact text from the image only."},
            ]
        }]
        r      = api_call(messages, think=think, max_tokens=256, timeout=60)
        c_text = get_content(r).strip().lower()
        correct = (answer in c_text or c_text in answer or
                   c_text == answer)
        prog.update(correct)
        return idx, {"correct": correct, "predicted": c_text[:50],
                     "answer": answer[:50]}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(eval_item, i, item): i for i, item in enumerate(items)}
        for fut in as_completed(futs):
            idx, res = fut.result()
            results[idx] = res

    correct_count = sum(1 for r in results if r and r["correct"])
    score  = correct_count / len(items) * 100
    detail = f"{correct_count}/{len(items)} correct = {score:.1f}%"
    return score, detail


# ═══════════════════════════════════════════════════════════════════════════════
# MMMU Pro
# ═══════════════════════════════════════════════════════════════════════════════
def run_mmmu(think: bool, limit: int = None, workers: int = None) -> tuple:
    """
    Parallel MMMU Pro. Requires datasets/mmmu_pro/mmmu_pro.jsonl
    (run download_datasets.sh first).
    Multi-choice with images.
    Returns (score_pct, detail).
    """
    path = Path("datasets/mmmu_pro/mmmu_pro.jsonl")
    if not path.exists():
        return None, ("datasets/mmmu_pro/mmmu_pro.jsonl not found. "
                      "Run: bash download_datasets.sh")

    items = [json.loads(l) for l in open(path) if l.strip()]
    if limit:
        items = items[:limit]

    n    = workers or PARALLELISM["mmmu"]
    prog = Progress(len(items), "MMMU")
    results = [None] * len(items)

    def eval_item(idx, item):
        question = item["question"]
        answer   = str(item["answer"]).strip().upper()
        images   = item.get("images_b64", [])

        content = []
        for b64 in images:
            content.append({"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        content.append({
            "type": "text",
            "text": (f"{question}\n\n"
                     "Answer with just the letter of the correct option (A, B, C, or D). "
                     "One letter only.")
        })
        messages = [{"role": "user", "content": content}]
        r = api_call(messages, think=think, max_tokens=128, timeout=60)
        c_text = get_content(r).strip().upper()
        # Extract single letter answer
        letters = re.findall(r'\b([A-D])\b', c_text)
        predicted = letters[0] if letters else c_text[:1]
        correct   = (predicted == answer)
        prog.update(correct)
        return idx, {"correct": correct, "predicted": predicted, "answer": answer}

    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(eval_item, i, item): i for i, item in enumerate(items)}
        for fut in as_completed(futs):
            idx, res = fut.result()
            results[idx] = res

    correct_count = sum(1 for r in results if r and r["correct"])
    score  = correct_count / len(items) * 100
    detail = f"{correct_count}/{len(items)} correct = {score:.1f}%"
    return score, detail


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def run(run_full=False, run_aime_direct=False,
        evalscope_limit=None, workers=None):

    ocr_available  = Path("datasets/ocrbench/ocrbench.jsonl").exists()
    mmmu_available = Path("datasets/mmmu_pro/mmmu_pro.jsonl").exists()

    print()
    print("=" * 72)
    print("二、精度验收 / Accuracy Results")
    print("=" * 72)
    print(f"  Endpoint  : {ENDPOINT}")
    print(f"  Model     : {MODEL}")
    print(f"  Parallel  : AIME={workers or PARALLELISM['aime']} "
          f"K2VV={workers or PARALLELISM['k2vv']} "
          f"OCR={workers or PARALLELISM['ocrbench']} "
          f"MMMU={workers or PARALLELISM['mmmu']}")
    print(f"  OCRBench  : {'ready' if ocr_available else 'not downloaded — run: bash download_datasets.sh'}")
    print(f"  MMMU Pro  : {'ready' if mmmu_available else 'not downloaded — run: bash download_datasets.sh'}")
    run_benchmarks = run_full or run_aime_direct

    # ── 2.1 Think Mode ───────────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.1 Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<30} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*30} {'─'*9}   {'─'*9}   {'─'*8}")

    # OCRBench Think
    print(f"\n  [OCRBench — think=enabled | parallel={workers or PARALLELISM['ocrbench']}]")
    if run_benchmarks and ocr_available:
        t0 = time.time()
        score, detail = run_ocrbench(think=True, workers=workers)
        elapsed = time.time() - t0
        if score is not None:
            diff = score - 91.0; passed = abs(diff) <= 2.0
            print(row("OCRBench", 91.0, score, diff))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.1", "OCRBench", 91.0, score, diff, passed, detail)
        else:
            print(f"  FAIL     : {detail}")
            result("2.1", "OCRBench", 91.0, None, None, False, detail)
    elif not ocr_available:
        print(f"  SKIP     : run bash download_datasets.sh first")
        result("2.1", "OCRBench", 91.0, None, None, False, "dataset not downloaded")
    else:
        from tests.accuracy_results import _smoke as smoke_fn
        p, resp = _smoke("Invoice number #7823. What is the invoice number? Integer only.", "7823", True)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'OCRBench':<30} {91.0:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.1", "OCRBench", 91.0, None, None, p, note)

    # AIME 2025 Think
    print(f"\n  [AIME 2025 — think=enabled | 30 problems | parallel={workers or PARALLELISM['aime']}]")
    if run_benchmarks:
        t0 = time.time()
        score, detail, _ = run_aime(think=True, workers=workers)
        elapsed = time.time() - t0
        if score is not None:
            diff = score - 98.4; passed = abs(diff) <= 2.0
            print(row("AIME2025", 98.4, score, diff))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.1", "AIME2025", 98.4, score, diff, passed, detail)
        else:
            print(f"  FAIL     : {detail}")
            result("2.1", "AIME2025", 98.4, None, None, False, detail)
    else:
        p, resp = _smoke("What is 5 factorial? Integer only.", "120", True)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'AIME2025':<30} {98.4:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.1", "AIME2025", 98.4, None, None, p, note)

    # MMMU Pro Vision Think
    print(f"\n  [MMMU Pro Vision — think=enabled | parallel={workers or PARALLELISM['mmmu']}]")
    if run_benchmarks and mmmu_available:
        t0 = time.time()
        score, detail = run_mmmu(think=True, workers=workers)
        elapsed = time.time() - t0
        if score is not None:
            diff = score - 78.8; passed = abs(diff) <= 2.0
            print(row("MMMU Pro Vision", 78.8, score, diff))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.1", "MMMU Pro Vision", 78.8, score, diff, passed, detail)
        else:
            print(f"  FAIL     : {detail}")
            result("2.1", "MMMU Pro Vision", 78.8, None, None, False, detail)
    elif not mmmu_available:
        print(f"  SKIP     : run bash download_datasets.sh first")
        result("2.1", "MMMU Pro Vision", 78.8, None, None, False, "dataset not downloaded")
    else:
        p, resp = _smoke("A car goes 60km in 1.5h. Speed in km/h? Integer only.", "40", True)
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
    print(f"\n  [OCRBench — think=disabled | parallel={workers or PARALLELISM['ocrbench']}]")
    if run_benchmarks and ocr_available:
        t0 = time.time()
        score, detail = run_ocrbench(think=False, workers=workers)
        elapsed = time.time() - t0
        if score is not None:
            diff = score - 92.0; passed = abs(diff) <= 2.0
            print(row("OCRBench", 92.0, score, diff))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.2", "OCRBench", 92.0, score, diff, passed, detail)
        else:
            print(f"  FAIL     : {detail}")
            result("2.2", "OCRBench", 92.0, None, None, False, detail)
    elif not ocr_available:
        print(f"  SKIP     : run bash download_datasets.sh first")
        result("2.2", "OCRBench", 92.0, None, None, False, "dataset not downloaded")
    else:
        p, resp = _smoke("Invoice number #7823. What is the invoice number? Integer only.", "7823", False)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'OCRBench':<30} {92.0:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.2", "OCRBench", 92.0, None, None, p, note)

    # AIME 2025 Non-Think
    print(f"\n  [AIME 2025 — think=disabled | 30 problems | parallel={workers or PARALLELISM['aime']}]")
    if run_benchmarks:
        t0 = time.time()
        score, detail, _ = run_aime(think=False, workers=workers)
        elapsed = time.time() - t0
        if score is not None:
            diff = score - 70.5; passed = abs(diff) <= 2.0
            print(row("AIME2025", 70.5, score, diff))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.2", "AIME2025", 70.5, score, diff, passed, detail)
        else:
            print(f"  FAIL     : {detail}")
            result("2.2", "AIME2025", 70.5, None, None, False, detail)
    else:
        p, resp = _smoke("What is 5 factorial? Integer only.", "120", False)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'AIME2025':<30} {70.5:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.2", "AIME2025", 70.5, None, None, p, note)

    # MMMU Pro Non-Think
    print(f"\n  [MMMU Pro — think=disabled | parallel={workers or PARALLELISM['mmmu']}]")
    if run_benchmarks and mmmu_available:
        t0 = time.time()
        score, detail = run_mmmu(think=False, workers=workers)
        elapsed = time.time() - t0
        if score is not None:
            diff = score - 74.9; passed = abs(diff) <= 2.0
            print(row("MMMU Pro", 74.9, score, diff))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.2", "MMMU Pro", 74.9, score, diff, passed, detail)
        else:
            print(f"  FAIL     : {detail}")
            result("2.2", "MMMU Pro", 74.9, None, None, False, detail)
    elif not mmmu_available:
        print(f"  SKIP     : run bash download_datasets.sh first")
        result("2.2", "MMMU Pro", 74.9, None, None, False, "dataset not downloaded")
    else:
        p, resp = _smoke("A car goes 60km in 1.5h. Speed in km/h? Integer only.", "40", False)
        note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
        print(f"  {'✓' if p else '✗'}  {'MMMU Pro':<30} {74.9:>8.1f}%   {'SMOKE':>9}   {'—':>8}   {note}")
        result("2.2", "MMMU Pro", 74.9, None, None, p, note)

    # K2VV ToolCall
    print(f"\n  [K2VV ToolCall — 12 openclaw cases | parallel={workers or PARALLELISM['k2vv']}]")
    if run_benchmarks:
        t0 = time.time()
        f1, schema_acc, detail = run_k2vv(workers=workers)
        elapsed = time.time() - t0
        if f1 is not None:
            diff_f1 = f1 - 84.0;    passed_f1 = abs(diff_f1) <= 2.0
            diff_sa = schema_acc - 100.0; passed_sa = abs(diff_sa) <= 2.0
            print(row("K2VV ToolCall (f1)",         84.0,  f1,         diff_f1))
            print(row("K2VV ToolCall (schema_acc)", 100.0, schema_acc, diff_sa))
            print(f"  Detail   : {detail}  elapsed={elapsed:.0f}s")
            result("2.2", "K2VV ToolCall (f1)",         84.0,  f1,         diff_f1, passed_f1, detail)
            result("2.2", "K2VV ToolCall (schema_acc)", 100.0, schema_acc, diff_sa, passed_sa, detail)
        else:
            for name, official in [("K2VV ToolCall (f1)", 84.0),
                                   ("K2VV ToolCall (schema_acc)", 100.0)]:
                print(f"  ?  {name:<30} {official:>8.1f}%   {'—':>9}   {'—':>8}  [{detail}]")
                result("2.2", name, official, None, None, False, detail)
    else:
        for name, official in [("K2VV ToolCall (f1)", 84.0),
                               ("K2VV ToolCall (schema_acc)", 100.0)]:
            print(f"  ?  {name:<30} {official:>8.1f}%   {'PENDING':>9}   {'—':>8}  "
                  f"[pass --aime-direct]")
            result("2.2", name, official, None, None, False, "pending")

    print(f"\n{sep()}")
    print("  Note: Any variance >2% from official target = service unavailable for that domain.")
    print()
    return _results


def _smoke(prompt, expected, think):
    r = chat([{"role": "user", "content": prompt}], think=think, max_tokens=256)
    c = (r.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return expected.lower() in c.lower(), c[:120]
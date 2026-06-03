"""
tests/accuracy_results.py — 二、精度验收 / Accuracy Results

Uses evalscope natively for all official benchmarks.
Parallelism via eval_batch_size (maps to ThreadPoolExecutor max_workers).

Root cause of AIME timeouts:
  - timeout=None → evalscope default OpenAI client has no hard cap
  - retries=5 (default) → each stuck request retries 5×, wasting 10+ min per problem
  - TM-004 bug → reasoning tokens consume max_tokens budget, model never finishes
  Fix: timeout=90s per request, retries=1, max_tokens=4096 for AIME

Benchmarks:
  aime25        — AIME 2025, 30 problems,    acc
  ocr_bench     — OCRBench,  1000 samples,   acc
  mmmu_pro      — MMMU Pro,  1730 samples,   acc  (vision / standard-4opt)
  k2_verifier   — K2VV,      2000 samples,   trigger_similarity + schema_accuracy
  kimi_verifier — Param,     22 probes,      param_immutable_reject_rate + param_default_accept_rate
"""
import json, os, time
from evalscope import run_task, TaskConfig
from evalscope.report import Report
from core.client import ENDPOINT, MODEL

_results = []


def result(section, dataset, official, actual, diff, passed, notes=""):
    _results.append({"section": section, "dataset": dataset,
                      "official": official, "result": actual,
                      "diff": diff, "passed": passed, "notes": notes})

def sep(w=72): return "─" * w

def row(dataset, official, score, diff):
    r_s  = f"{score:.1f}%"  if score is not None else "PENDING"
    d_s  = f"{diff:+.1f}%"  if diff  is not None else "—"
    icon = "✓" if (diff is not None and abs(diff) <= 2.0) else \
           "✗" if diff is not None else "?"
    return f"  {icon}  {dataset:<32} {official:>8.1f}%   {r_s:>9}   {d_s:>8}"

def smoke(prompt, expected, think):
    from core.client import chat
    r = chat([{"role": "user", "content": prompt}], think=think, max_tokens=256)
    c = (r.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return expected.lower() in c.lower(), c[:120]


# ── evalscope runner ──────────────────────────────────────────────────────────
def evalscope_run(datasets, gen_config, batch_size, limit=None,
                  dataset_args=None, work_dir="./outputs") -> dict:
    """Run evalscope and return {dataset_name: Report}."""
    cfg = TaskConfig(
        model=MODEL,
        api_url=ENDPOINT,
        api_key=os.environ.get("EVAL_API_KEY", "EMPTY"),
        datasets=datasets,
        dataset_args=dataset_args or {},
        generation_config=gen_config,
        eval_batch_size=batch_size,
        limit=limit,
        work_dir=work_dir,
        dataset_hub="modelscope",
        ignore_errors=True,
        no_timestamp=True,
    )
    try:
        r = run_task(task_cfg=cfg)
        if isinstance(r, Report):   return {datasets[0]: r}
        if isinstance(r, dict):     return r
        if isinstance(r, list):     return {d: v for d, v in zip(datasets, r)
                                            if isinstance(v, Report)}
        return {}
    except Exception as e:
        print(f"    evalscope error: {e}")
        return {}


def get_score(reports, dataset, metric="acc") -> float | None:
    report = reports.get(dataset)
    if not isinstance(report, Report): return None
    if metric in ("acc", "accuracy"):
        s = report.score
        return s * 100 if s is not None and s <= 1.0 else s
    for m in report.metrics:
        if metric.lower() in m.name.lower():
            s = m.score
            return s * 100 if s <= 1.0 else s
    return None


def get_k2vv(reports) -> tuple:
    report = reports.get("k2_verifier")
    if not isinstance(report, Report): return None, None
    f1 = sa = None
    for m in report.metrics:
        s = m.score * 100 if m.score <= 1.0 else m.score
        if "trigger" in m.name.lower() or "similarity" in m.name.lower(): f1 = s
        if "schema"  in m.name.lower():                                    sa = s
    return f1, sa


def get_kimi_verifier(reports) -> tuple:
    report = reports.get("kimi_verifier")
    if not isinstance(report, Report): return None, None, None
    reject = accept = error = None
    for m in report.metrics:
        s = m.score * 100 if m.score <= 1.0 else m.score
        if "reject" in m.name.lower(): reject = s
        if "accept" in m.name.lower(): accept = s
        if "error"  in m.name.lower(): error  = s
    return reject, accept, error


# ══════════════════════════════════════════════════════════════════════════════
def run(run_full=False, run_aime_direct=False, evalscope_limit=None,
        batch_size=8, **kwargs):

    run_bench = run_full or run_aime_direct
    bs        = kwargs.get("workers") or batch_size
    ts        = str(int(time.time()))

    print()
    print("=" * 72)
    print("二、精度验收 / Accuracy Results")
    print("=" * 72)
    print(f"  Endpoint     : {ENDPOINT}")
    print(f"  Model        : {MODEL}")
    print(f"  Batch size   : {bs} parallel requests")
    print(f"  Timeout      : 90s per request, 1 retry (prevents TM-004 infinite loops)")
    print(f"  Mode         : {'Full evalscope benchmarks' if run_bench else 'Smoke tests only'}")
    if not run_bench:
        print("  Tip          : pass --aime-direct for full evalscope run")

    # ── Generation configs ────────────────────────────────────────────────────
    # KEY FIX: timeout=90, retries=1, retry_interval=5
    # This prevents stuck AIME problems from blocking for 10+ minutes.
    # With batch_size=8 + timeout=90: worst case per batch = 90s (not 10 min).
    BASE = dict(retries=1, retry_interval=5, timeout=90.0)

    GEN_THINK   = {**BASE,
                   "extra_body":  {"thinking": {"type": "enabled"}},
                   "temperature": 1.0,
                   "max_tokens":  4096}   # 4096 prevents infinite TM-004 reasoning loops

    GEN_NOTHINK = {**BASE,
                   "extra_body":  {"thinking": {"type": "disabled"}},
                   "temperature": 0.6,
                   "max_tokens":  4096}

    # OCRBench and MMMU only need short answers — can use smaller max_tokens
    GEN_VISION  = {**BASE,
                   "extra_body":  {"thinking": {"type": "enabled"}},
                   "temperature": 1.0,
                   "max_tokens":  1024}   # images → short answers, no need for 4096

    GEN_VIS_NT  = {**BASE,
                   "extra_body":  {"thinking": {"type": "disabled"}},
                   "temperature": 0.6,
                   "max_tokens":  1024}

    # ── 2.1 Think Mode ────────────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.1 Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<32} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*32} {'─'*9}   {'─'*9}   {'─'*8}")

    if run_bench:
        # AIME: separate run with think config (4096 max_tokens)
        print(f"\n  [AIME2025 think | 30 problems | batch={bs} | timeout=90s | max_tokens=4096]")
        t0 = time.time()
        aime_think = evalscope_run(
            datasets=["aime25"],
            gen_config=GEN_THINK,
            batch_size=bs, limit=evalscope_limit,
            work_dir=f"./outputs/aime_think_{ts}",
        )
        print(f"  Completed in {time.time()-t0:.0f}s")
        s = get_score(aime_think, "aime25")
        if s is not None:
            diff = s - 98.4; passed = abs(diff) <= 2.0
            print(row("AIME2025", 98.4, s, diff))
            result("2.1", "AIME2025", 98.4, s, diff, passed)
        else:
            print(f"  ?  {'AIME2025':<32} {98.4:>8.1f}%   {'—':>9}   {'—':>8}  [score not parsed]")
            result("2.1", "AIME2025", 98.4, None, None, False, "score not parsed")

        # OCRBench + MMMU: separate run with vision config (1024 max_tokens)
        print(f"\n  [OCRBench + MMMU Pro Vision | batch={bs} | timeout=90s | max_tokens=1024]")
        t0 = time.time()
        vis_think = evalscope_run(
            datasets=["ocr_bench", "mmmu_pro"],
            gen_config=GEN_VISION,
            batch_size=bs, limit=evalscope_limit,
            dataset_args={"mmmu_pro": {"extra_params": {"dataset_format": "vision"}}},
            work_dir=f"./outputs/vis_think_{ts}",
        )
        print(f"  Completed in {time.time()-t0:.0f}s")
        for display, ds_key, official in [
            ("OCRBench",        "ocr_bench", 91.0),
            ("MMMU Pro Vision", "mmmu_pro",  78.8),
        ]:
            s = get_score(vis_think, ds_key)
            if s is not None:
                diff = s - official; passed = abs(diff) <= 2.0
                print(row(display, official, s, diff))
                result("2.1", display, official, s, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}  [not parsed]")
                result("2.1", display, official, None, None, False, "not parsed")
    else:
        for prompt, expected, display, official in [
            ("Invoice #7823. What is the invoice number? Integer only.", "7823",
             "OCRBench", 91.0),
            ("What is 5 factorial? Integer only.", "120", "AIME2025", 98.4),
            ("A car: 60km in 1.5h. Speed km/h? Integer only.", "40",
             "MMMU Pro Vision", 78.8),
        ]:
            p, resp = smoke(prompt, expected, think=True)
            note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
            print(f"  {'✓' if p else '✗'}  {display:<32} {official:>8.1f}%"
                  f"   {'SMOKE':>9}   {'—':>8}   {note}")
            result("2.1", display, official, None, None, p, note)

    # ── 2.2 Non-Think Mode ────────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.2 Non-Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<32} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*32} {'─'*9}   {'─'*9}   {'─'*8}")

    if run_bench:
        # AIME non-think
        print(f"\n  [AIME2025 non-think | 30 problems | batch={bs} | timeout=90s | max_tokens=4096]")
        t0 = time.time()
        aime_nt = evalscope_run(
            datasets=["aime25"],
            gen_config=GEN_NOTHINK,
            batch_size=bs, limit=evalscope_limit,
            work_dir=f"./outputs/aime_nothink_{ts}",
        )
        print(f"  Completed in {time.time()-t0:.0f}s")
        s = get_score(aime_nt, "aime25")
        if s is not None:
            diff = s - 70.5; passed = abs(diff) <= 2.0
            print(row("AIME2025", 70.5, s, diff))
            result("2.2", "AIME2025", 70.5, s, diff, passed)
        else:
            print(f"  ?  {'AIME2025':<32} {70.5:>8.1f}%   {'—':>9}   {'—':>8}  [not parsed]")
            result("2.2", "AIME2025", 70.5, None, None, False, "not parsed")

        # OCRBench + MMMU non-think
        print(f"\n  [OCRBench + MMMU Pro Std | batch={bs} | timeout=90s | max_tokens=1024]")
        t0 = time.time()
        vis_nt = evalscope_run(
            datasets=["ocr_bench", "mmmu_pro"],
            gen_config=GEN_VIS_NT,
            batch_size=bs, limit=evalscope_limit,
            dataset_args={"mmmu_pro": {"extra_params": {
                "dataset_format": "standard (4 options)"}}},
            work_dir=f"./outputs/vis_nothink_{ts}",
        )
        print(f"  Completed in {time.time()-t0:.0f}s")
        for display, ds_key, official in [
            ("OCRBench", "ocr_bench", 92.0),
            ("MMMU Pro", "mmmu_pro",  74.9),
        ]:
            s = get_score(vis_nt, ds_key)
            if s is not None:
                diff = s - official; passed = abs(diff) <= 2.0
                print(row(display, official, s, diff))
                result("2.2", display, official, s, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}  [not parsed]")
                result("2.2", display, official, None, None, False, "not parsed")

        # K2VV + kimi_verifier — both non-think, separate run for clarity
        print(f"\n  [K2VV (k2_verifier 2000) + Param (kimi_verifier 22) | batch={bs}]")
        t0 = time.time()
        nt_extra = evalscope_run(
            datasets=["k2_verifier", "kimi_verifier"],
            gen_config=GEN_NOTHINK,
            batch_size=bs, limit=evalscope_limit,
            dataset_args={"kimi_verifier": {"subset_list": ["kimi"]}},
            work_dir=f"./outputs/extra_nothink_{ts}",
        )
        print(f"  Completed in {time.time()-t0:.0f}s")

        # K2VV scores
        f1, schema_acc = get_k2vv(nt_extra)
        for display, official, score in [
            ("K2VV ToolCall (f1)",         84.0,  f1),
            ("K2VV ToolCall (schema_acc)", 100.0, schema_acc),
        ]:
            if score is not None:
                diff = score - official; passed = abs(diff) <= 2.0
                print(row(display, official, score, diff))
                result("2.2", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}  [not parsed]")
                result("2.2", display, official, None, None, False, "not parsed")

        # kimi_verifier scores
        print(f"\n  [Kimi Param Compliance — kimi_verifier subset=kimi]")
        reject, accept, error = get_kimi_verifier(nt_extra)
        for display, official, score in [
            ("Param Reject Rate (immutable)", 100.0, reject),
            ("Param Accept Rate (defaults)",  100.0, accept),
        ]:
            if score is not None:
                diff = score - official; passed = abs(diff) <= 2.0
                print(row(display, official, score, diff))
                result("2.2", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}  [not parsed]")
                result("2.2", display, official, None, None, False, "not parsed")

        if error is not None:
            icon = "✓" if error == 0 else "✗"
            print(f"  {icon}  {'Inference Error Rate':<32}   target=0.0%   "
                  f"actual={error:.1f}%"
                  f"{'  OK' if error == 0 else '  WARN: transport errors detected'}")
            result("2.2", "Inference Error Rate", 0.0, error, None, error == 0)
    else:
        for prompt, expected, display, official in [
            ("Invoice #7823. What is the invoice number? Integer only.", "7823",
             "OCRBench", 92.0),
            ("What is 5 factorial? Integer only.", "120", "AIME2025", 70.5),
            ("A car: 60km in 1.5h. Speed km/h? Integer only.", "40",
             "MMMU Pro", 74.9),
        ]:
            p, resp = smoke(prompt, expected, think=False)
            note = f"smoke={'PASS' if p else 'FAIL'}: {resp[:50]!r}"
            print(f"  {'✓' if p else '✗'}  {display:<32} {official:>8.1f}%"
                  f"   {'SMOKE':>9}   {'—':>8}   {note}")
            result("2.2", display, official, None, None, p, note)

        for display, official in [
            ("K2VV ToolCall (f1)",         84.0),
            ("K2VV ToolCall (schema_acc)", 100.0),
            ("Param Reject Rate",          100.0),
            ("Param Accept Rate",          100.0),
        ]:
            print(f"  ?  {display:<32} {official:>8.1f}%   {'PENDING':>9}   {'—':>8}"
                  f"  [pass --aime-direct]")
            result("2.2", display, official, None, None, False, "pending")

    print(f"\n{sep()}")
    print("  Accuracy rule : variance >2% = service unavailable for that domain.")
    print("  Param rule    : both Reject Rate and Accept Rate must be 100% for compliance.")
    print()
    return _results
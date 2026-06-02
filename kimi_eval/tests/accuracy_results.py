"""
tests/accuracy_results.py — 二、精度验收 / Accuracy Results

Uses evalscope natively for all four official benchmarks.
Parallelism controlled via eval_batch_size.

Benchmarks:
  aime25        — AIME 2025, 30 problems, acc metric
  ocr_bench     — OCRBench, 1000 samples, acc metric
  mmmu_pro      — MMMU Pro (vision for think, standard-4opt for non-think), acc metric
  k2_verifier   — K2VV ToolCall, 2000 samples, trigger_similarity + schema_accuracy
  kimi_verifier — Kimi Param Compliance, synthetic probes,
                  param_immutable_reject_rate + param_default_accept_rate
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
def evalscope_run(datasets: list, gen_config: dict, batch_size: int,
                  limit: int = None, dataset_args: dict = None,
                  work_dir: str = "./outputs") -> dict[str, Report]:
    """
    Run evalscope and return {dataset_name: Report}.
    Report.score    = primary metric (0-100 scale or 0-1 — we normalise)
    Report.metrics  = list of Metric objects with .name and .score
    """
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
        result_obj = run_task(task_cfg=cfg)
        # run_task returns Report | list[Report] | dict
        if isinstance(result_obj, Report):
            return {datasets[0]: result_obj}
        if isinstance(result_obj, dict):
            return result_obj
        if isinstance(result_obj, list):
            return {d: r for d, r in zip(datasets, result_obj) if isinstance(r, Report)}
        return {}
    except Exception as e:
        print(f"    evalscope error: {e}")
        return {}


def get_score(reports: dict, dataset: str, metric: str = "acc") -> float | None:
    """Extract a named metric from the Report for dataset."""
    report = reports.get(dataset)
    if not isinstance(report, Report):
        return None
    # Primary score (first metric)
    if metric in ("acc", "accuracy"):
        score = report.score
        return score * 100 if score <= 1.0 else score
    # Named metric
    for m in report.metrics:
        if metric.lower() in m.name.lower():
            s = m.score
            return s * 100 if s <= 1.0 else s
    return None


def get_kimi_verifier_scores(reports: dict) -> tuple[float | None, float | None, float | None]:
    """
    Extract kimi_verifier metrics:
      param_immutable_reject_rate, param_default_accept_rate, inference_error_rate
    """
    report = reports.get("kimi_verifier")
    if not isinstance(report, Report):
        return None, None, None
    reject_rate = accept_rate = error_rate = None
    for m in report.metrics:
        nm = m.name.lower()
        s  = m.score * 100 if m.score <= 1.0 else m.score
        if "reject" in nm:  reject_rate = s
        if "accept" in nm:  accept_rate = s
        if "error"  in nm:  error_rate  = s
    return reject_rate, accept_rate, error_rate


def get_k2vv_scores(reports: dict) -> tuple[float | None, float | None]:
    """Extract k2_verifier trigger_similarity (f1) and schema_accuracy."""
    report = reports.get("k2_verifier")
    if not isinstance(report, Report):
        return None, None
    f1 = schema_acc = None
    for m in report.metrics:
        nm = m.name.lower()
        s  = m.score * 100 if m.score <= 1.0 else m.score
        if "trigger" in nm or "similarity" in nm: f1 = s
        if "schema"  in nm:                       schema_acc = s
    return f1, schema_acc


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
    print(f"  Batch size   : {bs} parallel requests (eval_batch_size)")
    print(f"  Mode         : {'Full evalscope benchmarks' if run_bench else 'Smoke tests only'}")
    if not run_bench:
        print("  Tip          : pass --aime-direct for full evalscope benchmark run")

    # ── Generation configs — Anthropic-style thinking as per spec ─────────────
    GEN_THINK   = {
        "extra_body": {"thinking": {"type": "enabled"}},
        "temperature": 1.0,
        "max_tokens": 8192,
    }
    GEN_NOTHINK = {
        "extra_body": {"thinking": {"type": "disabled"}},
        "temperature": 0.6,
        "max_tokens": 4096,
    }

    # ── 2.1 Think Mode ────────────────────────────────────────────────────────
    print(f"\n{sep()}")
    print("2.1 Think Mode")
    print(sep())
    print(f"\n  {'':3}  {'Dataset':<32} {'Official%':>9}   {'Result':>9}   {'Diff':>8}")
    print(f"  {'':3}  {'─'*32} {'─'*9}   {'─'*9}   {'─'*8}")

    if run_bench:
        print(f"\n  Running think-mode benchmarks (batch_size={bs})...")
        print(f"  aime25 | ocr_bench | mmmu_pro (vision format)")
        t0 = time.time()
        think_reports = evalscope_run(
            datasets=["aime25", "ocr_bench", "mmmu_pro"],
            gen_config=GEN_THINK,
            batch_size=bs,
            limit=evalscope_limit,
            dataset_args={
                "mmmu_pro": {
                    "extra_params": {"dataset_format": "vision"},
                }
            },
            work_dir=f"./outputs/think_{ts}",
        )
        elapsed = time.time() - t0
        print(f"\n  Think-mode completed in {elapsed:.0f}s")
        print()

        for display, ds_key, official in [
            ("OCRBench",        "ocr_bench", 91.0),
            ("AIME2025",        "aime25",    98.4),
            ("MMMU Pro Vision", "mmmu_pro",  78.8),
        ]:
            score = get_score(think_reports, ds_key)
            if score is not None:
                diff = score - official; passed = abs(diff) <= 2.0
                print(row(display, official, score, diff))
                result("2.1", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}"
                      f"  [not found in report]")
                result("2.1", display, official, None, None, False,
                       "score not parsed from evalscope report")
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
        print(f"\n  Running non-think benchmarks (batch_size={bs})...")
        print(f"  aime25 | ocr_bench | mmmu_pro (standard 4-opt) | k2_verifier | kimi_verifier")
        t0 = time.time()
        nothink_reports = evalscope_run(
            datasets=["aime25", "ocr_bench", "mmmu_pro", "k2_verifier", "kimi_verifier"],
            gen_config=GEN_NOTHINK,
            batch_size=bs,
            limit=evalscope_limit,
            dataset_args={
                "mmmu_pro": {
                    "extra_params": {"dataset_format": "standard (4 options)"},
                },
                "kimi_verifier": {
                    # Use 'kimi' subset — Anthropic-style thinking format
                    "subset_list": ["kimi"],
                },
            },
            work_dir=f"./outputs/nothink_{ts}",
        )
        elapsed = time.time() - t0
        print(f"\n  Non-think completed in {elapsed:.0f}s")
        print()

        # OCRBench, AIME, MMMU
        for display, ds_key, official in [
            ("OCRBench",  "ocr_bench", 92.0),
            ("AIME2025",  "aime25",    70.5),
            ("MMMU Pro",  "mmmu_pro",  74.9),
        ]:
            score = get_score(nothink_reports, ds_key)
            if score is not None:
                diff = score - official; passed = abs(diff) <= 2.0
                print(row(display, official, score, diff))
                result("2.2", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}"
                      f"  [not found in report]")
                result("2.2", display, official, None, None, False,
                       "score not parsed from evalscope report")

        # K2VV ToolCall (k2_verifier)
        f1, schema_acc = get_k2vv_scores(nothink_reports)
        for display, official, score in [
            ("K2VV ToolCall (f1)",         84.0,  f1),
            ("K2VV ToolCall (schema_acc)", 100.0, schema_acc),
        ]:
            if score is not None:
                diff = score - official; passed = abs(diff) <= 2.0
                print(row(display, official, score, diff))
                result("2.2", display, official, score, diff, passed)
            else:
                print(f"  ?  {display:<32} {official:>8.1f}%   {'—':>9}   {'—':>8}"
                      f"  [k2_verifier metric not parsed]")
                result("2.2", display, official, None, None, False,
                       "k2_verifier metric not found")

        # Kimi Param Compliance (kimi_verifier)
        print(f"\n  [Kimi Param Compliance — kimi_verifier (subset: kimi)]")
        reject_rate, accept_rate, error_rate = get_kimi_verifier_scores(nothink_reports)
        # Spec: both rates must be 1.0 (100%) for compliant vendor
        kv_data = [
            ("Param Reject Rate (immutable)",  reject_rate, 100.0),
            ("Param Accept Rate (defaults)",   accept_rate, 100.0),
            ("Inference Error Rate",           error_rate,   0.0),
        ]
        for display, score, target in kv_data:
            if score is not None:
                if display.startswith("Inference"):
                    passed = score == 0.0
                    diff   = score   # lower=better; 0% is ideal
                    icon   = "✓" if passed else "✗"
                    print(f"  {icon}  {display:<32}   target=0.0%   actual={score:.1f}%"
                          f"{'  OK' if passed else '  FAIL (transport errors detected)'}")
                else:
                    passed = abs(score - target) <= 2.0
                    diff   = score - target
                    print(row(display, target, score, diff))
                result("2.2", display, target, score, diff if not display.startswith("Inference") else None, passed)
            else:
                print(f"  ?  {display:<32}   [kimi_verifier metric not parsed]")
                result("2.2", display, target, None, None, False, "not parsed")
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
    print("  Accuracy rule: variance >2% from official target = service unavailable.")
    print("  kimi_verifier rule: param_immutable_reject_rate AND param_default_accept_rate")
    print("  must both be 1.0 (100%) for a compliant vendor deployment.")
    print()
    return _results
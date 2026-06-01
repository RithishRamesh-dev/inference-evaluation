"""
tests/r11_accuracy.py
Requirement 11 — Accuracy (Smoke + evalscope integration)
Spec targets:
  Think:     OCRBench=91%, AIME2025=98.4%, MMMU Pro Vision=78.8%
  Non-Think: OCRBench=92%, AIME2025=70.5%, MMMU Pro=74.9%,
             K2VV ToolCall f1=84%, schema_acc=100%
"""
import subprocess, json, time, re
from pathlib import Path
from core.common import call, record, console

SEC = "R11"

TARGETS = {
    "think":     {"ocr": 91.0, "aime": 98.4, "mmmu": 78.8},
    "non_think": {"ocr": 92.0, "aime": 70.5, "mmmu": 74.9,
                  "k2vv_f1": 84.0, "k2vv_schema": 100.0},
}

SMOKE_TESTS = [
    # (question, expected_answer_fragment, think_mode, label)
    ("What is 5 factorial?", "120", True,  "AIME-smoke-think: 5!=120"),
    ("What is 5 factorial?", "120", False, "AIME-smoke-nonthink: 5!=120"),
    ("Invoice #7823 Total $4250. What is the invoice number? Number only.", "7823", False, "OCR-smoke: invoice number"),
    ("A car travels 60 km in 1.5 hours. Speed in km/h? Number only.", "40", False, "OCR-smoke: speed calc"),
    ("If A>B>C and B>D, which is smallest?", "c", False, "MMMU-smoke: logic"),
]


def run_smoke():
    """Quick sanity check that accuracy is in the right ballpark."""
    console.print("  Running smoke accuracy tests...")
    pass_count = 0
    for prompt, expected, think, label in SMOKE_TESTS:
        r = call([{"role":"user","content":prompt}], think=think, max_tokens=256)
        content = (r.get("choices") or [{}])[0].get("message", {}).get("content", "").lower()
        passed = expected.lower() in content
        if passed: pass_count += 1
        record(SEC, f"R11-smoke {label}", passed, f"expected={expected} got={content[:60]}")
        console.print(f"  {'✓' if passed else '✗'} {label} | got: {content[:60]}")
        time.sleep(0.3)
    return pass_count, len(SMOKE_TESTS)


def run_evalscope(benchmark: str, mode: str, limit: int = 10) -> dict:
    """
    Run evalscope against official benchmark datasets.
    Returns score dict or error.
    """
    import os
    api_url  = os.environ.get("EVAL_ENDPOINT_URL", "")
    api_key  = os.environ.get("EVAL_API_KEY", "")
    model    = os.environ.get("EVAL_MODEL", "kimi-k2.6")
    think_val = "true" if mode == "think" else "false"

    cmd = [
        "evalscope", "eval",
        "--eval-type", "openai_api",
        "--model", model,
        "--api-url", api_url,
        "--api-key", api_key,
        "--datasets", benchmark,
        "--generation-config",
        f'{{"extra_body":{{"thinking":{{"type":"{"enabled" if mode=="think" else "disabled"}"}}}}}}',
        "--limit", str(limit),
    ]
    if benchmark == "mmmu_pro" and mode == "think":
        cmd += ["--dataset-args", '{"mmmu_pro":{"extra_params":{"dataset_format":"vision"}}}']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr
        # Try to extract score from evalscope output
        score_match = re.search(r"accuracy[:\s]+([0-9.]+)", output, re.IGNORECASE)
        score = float(score_match.group(1)) if score_match else None
        return {"score": score, "output": output[:1000], "returncode": result.returncode}
    except FileNotFoundError:
        return {"error": "evalscope not installed. Run: pip install evalscope[api]"}
    except subprocess.TimeoutExpired:
        return {"error": "evalscope timeout (>600s)"}
    except Exception as e:
        return {"error": str(e)}


def run(run_full: bool = False, evalscope_limit: int = 10):
    console.rule(f"[bold white]{SEC} — Accuracy Requirements[/]")
    console.print(f"  Official targets: think OCR=91% AIME=98.4% MMMU=78.8%")
    console.print(f"  Official targets: non-think OCR=92% AIME=70.5% MMMU=74.9% K2VV-f1=84%")
    console.print()

    # Smoke tests always run
    passed_smoke, total_smoke = run_smoke()
    record(SEC, f"R11-smoke All smoke accuracy tests",
           passed_smoke == total_smoke,
           f"{passed_smoke}/{total_smoke} smoke tests pass")

    if not run_full:
        console.print(f"\n  [dim]Full evalscope benchmarks skipped (pass --full-accuracy to run).[/]")
        console.print(f"  [dim]Run: bash run_evalscope.sh all[/]")
        console.print()
        return

    # Full evalscope benchmarks
    console.print(f"\n  Running evalscope benchmarks (limit={evalscope_limit} samples)...")
    benchmarks = [
        ("aime25",   "think",     TARGETS["think"]["aime"]),
        ("aime25",   "non_think", TARGETS["non_think"]["aime"]),
        ("ocr_bench","think",     TARGETS["think"]["ocr"]),
        ("ocr_bench","non_think", TARGETS["non_think"]["ocr"]),
        ("mmmu_pro", "think",     TARGETS["think"]["mmmu"]),
        ("mmmu_pro", "non_think", TARGETS["non_think"]["mmmu"]),
    ]
    for bench, mode, target in benchmarks:
        result = run_evalscope(bench, mode, evalscope_limit)
        if "error" in result:
            record(SEC, f"R11 {bench} [{mode}]", False, result["error"])
            console.print(f"  ✗ {bench} [{mode}]: {result['error']}")
        else:
            score = result.get("score")
            if score is not None:
                passed = score >= target - 2.0  # ±2% tolerance
                record(SEC, f"R11 {bench} [{mode}] score≥{target-2}%",
                       passed, f"score={score:.1f}% target={target}% delta={score-target:+.1f}%")
                console.print(f"  {'✓' if passed else '✗'} {bench} [{mode}]: {score:.1f}% (target {target}%)")
            else:
                record(SEC, f"R11 {bench} [{mode}] evalscope", False,
                       "Could not parse score from evalscope output")
                console.print(f"  ? {bench} [{mode}]: score not parsed from evalscope")

    console.print()

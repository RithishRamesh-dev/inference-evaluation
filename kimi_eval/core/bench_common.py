"""
core/bench_common.py
====================
Shared utilities for Stage 5 benchmark runners.
Reuses the HTTP client from core/common.py — no duplication.
"""

import json
import math
import re
from pathlib import Path

# Reuse the same HTTP client from the main eval harness
from core.common import call as _raw_call, ENDPOINT, MODEL, TIMEOUT, HEADERS

# ── official targets from Stage 1 spec ───────────────────────────────────────
TARGETS = {
    "ocrbench": {"think": 91.0,  "non_think": 92.0},
    "aime2025": {"think": 98.4,  "non_think": 70.5},
    "mmmu_pro": {"think": 78.8,  "non_think": 74.9},
}
TOLERANCE = 2.0   # ±2% — beyond this = service unavailable per spec


# ── benchmark-specific HTTP call ─────────────────────────────────────────────
def bcall(messages: list, think: bool = False, temperature: float = None,
          max_tokens: int = 2048) -> tuple:
    """
    Send one chat completion request for benchmark use.
    Returns (content, reasoning_content, raw_response_dict).
    On error returns ("", "", {"error": ...}).
    """
    import httpx, os
    temp = temperature if temperature is not None else (1.0 if think else 0.6)
    payload = {
        "model":           MODEL,
        "messages":        messages,
        "enable_thinking": think,
        "temperature":     temp,
        "max_tokens":      max_tokens,
    }
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=TIMEOUT)
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg    = choice.get("message") or {}
        return (
            msg.get("content") or "",
            msg.get("reasoning_content") or "",
            data,
        )
    except Exception as e:
        return "", "", {"error": str(e)}


# ── statistics ────────────────────────────────────────────────────────────────
def confidence_interval_95(n_correct: int, n_total: int) -> tuple:
    """Wilson score 95% confidence interval."""
    if n_total == 0:
        return 0.0, 0.0
    p      = n_correct / n_total
    z      = 1.96
    denom  = 1 + z**2 / n_total
    centre = (p + z**2 / (2 * n_total)) / denom
    margin = (z * math.sqrt(p * (1-p) / n_total + z**2 / (4 * n_total**2))) / denom
    return round(max(0, centre - margin) * 100, 2), round(min(1, centre + margin) * 100, 2)


def score_result(benchmark: str, mode: str, n_correct: int, n_total: int) -> dict:
    """Compute accuracy, CI, delta vs target, and pass/fail verdict."""
    accuracy = n_correct / n_total * 100 if n_total else 0
    target   = TARGETS[benchmark][mode]
    delta    = accuracy - target
    ci_lo, ci_hi = confidence_interval_95(n_correct, n_total)
    passed   = delta >= -TOLERANCE
    return {
        "benchmark":     benchmark,
        "mode":          mode,
        "n_total":       n_total,
        "n_correct":     n_correct,
        "accuracy_pct":  round(accuracy, 2),
        "target_pct":    target,
        "delta_pct":     round(delta, 2),
        "tolerance_pct": TOLERANCE,
        "ci_95_lower":   ci_lo,
        "ci_95_upper":   ci_hi,
        "passed":        passed,
        "verdict":       "PASS" if passed else "FAIL — service unavailable",
    }


# ── answer extraction helpers ─────────────────────────────────────────────────
def extract_integer(text: str):
    """
    Extract the AIME answer integer from model output.
    Priority order:
      1. ANSWER: NNN on the first few lines (our enforced format)
      2. \\boxed{N} anywhere in text
      3. Explicit 'Answer: N' / 'answer is N' phrase
      4. Last standalone integer on any line
    All values > 999 are taken mod 1000 (AIME convention: answers are 000-999).
    Returns None only if no integer is found anywhere.
    """
    if not text:
        return None

    def clamp(val: int) -> int:
        return val % 1000 if val >= 1000 else val

    # 1. ANSWER: NNN on first 3 lines (our enforced prompt format)
    for line in text[:300].strip().splitlines()[:3]:
        m = re.match(r"^\s*answer\s*:\s*(\d+)\s*$", line.strip(), re.IGNORECASE)
        if m:
            return clamp(int(m.group(1)))

    # 2. \boxed{N} or $\boxed{N}$ — most reliable LaTeX answer marker
    boxed = re.findall(r"\\boxed\{(\d+)\}", text)
    if boxed:
        return clamp(int(boxed[-1]))

    # 3. Explicit answer phrase: "answer is N", "Answer: N", "final answer is N"
    phrases = re.findall(
        r"(?:answer is|the answer is|final answer(?:\s+is)?|answer:)\s*\**\s*(\d+)\s*\**",
        text, re.IGNORECASE
    )
    if phrases:
        return clamp(int(phrases[-1]))

    # 4. "therefore N", "thus N", "equals N" — common math conclusion phrases
    conclusions = re.findall(
        r"(?:therefore|thus|so|equals?|=|is)\s+(?:the\s+)?(?:answer\s+is\s+)?(\d{1,4})\b",
        text, re.IGNORECASE
    )
    if conclusions:
        candidates = [clamp(int(x)) for x in conclusions]
        # Return last one that is a plausible AIME answer
        for c in reversed(candidates):
            if 0 <= c <= 999:
                return c

    # 5. Last non-empty line containing a standalone integer
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for line in reversed(lines):
        nums = re.findall(r"\b(\d+)\b", line)
        if nums:
            return clamp(int(nums[-1]))

    return None


def extract_choice(text: str):
    """Extract A/B/C/D/E choice from model output (for MMMU)."""
    patterns = [
        r"\b(?:answer is|answer:|the answer)\s*[:\s]*([ABCDE])\b",
        r"^\s*([ABCDE])[.):]\s",
        r"\b([ABCDE])\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).upper()
    letters = re.findall(r"\b([ABCDE])\b", text.upper())
    return letters[-1] if letters else None


def normalize_ocr(text: str) -> str:
    """Normalize OCR answer for string comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())


# ── output helpers ────────────────────────────────────────────────────────────
def save_results(results: dict, out_dir: str, filename: str) -> str:
    import json as _json
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / filename
    with open(path, "w") as f:
        _json.dump(results, f, indent=2)
    print(f"  Saved → {path}")
    return str(path)


def print_score(result: dict):
    verdict = "✅ PASS" if result["passed"] else "❌ FAIL"
    print(f"\n  {verdict}  {result['benchmark'].upper()} [{result['mode']}]")
    print(f"  Score  : {result['accuracy_pct']:.1f}%")
    print(f"  Target : {result['target_pct']:.1f}%  (±{result['tolerance_pct']}%)")
    print(f"  Delta  : {result['delta_pct']:+.1f}%")
    print(f"  95% CI : [{result['ci_95_lower']}%, {result['ci_95_upper']}%]")
    print(f"  n      : {result['n_correct']}/{result['n_total']} correct")
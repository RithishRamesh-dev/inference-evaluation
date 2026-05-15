"""
benchmarks/run_aime.py — AIME 2025
====================================
Official targets: think=98.4%  non-think=70.5%  (±2% tolerance)

Prompt and extraction method follow the official Kaggle AIME 2025
benchmark notebook exactly:
  - Prompt: "reason step by step, put final answer in \\boxed{}"
  - Extractor: find last \\boxed{N} in response

Dataset: datasets/aime2025.json (30 official problems, verified answers)
"""

import json
import re
import time
from collections import Counter
from pathlib import Path

from core.bench_common import bcall, score_result, save_results, print_score, TARGETS

# ── Official dataset path ─────────────────────────────────────────────────────
OFFICIAL_DATASET = "datasets/aime2025.json"

# ── Official prompt (exact from Kaggle AIME 2025 benchmark notebook) ──────────
SYSTEM_PROMPT = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive."
)

# Max tokens — large enough to capture full response including \\boxed{} answer.
# The TM-004 bug causes reasoning_content to leak into content in non-think mode,
# making responses very long. 16000 ensures we always get the complete answer.
MAX_TOKENS = 16000


# ── Official extractor (from Kaggle notebook, simplified for integer answers) ──
def extract_boxed(text: str):
    """
    Extract the last \\boxed{N} from model output.
    This matches the official Kaggle AIME 2025 benchmark extraction method.
    Handles: \\boxed{588}, $\\boxed{070}$, \\boxed{1,176}, \\boxed{40320} etc.
    Values > 999 are taken mod 1000 (AIME answers are always 000-999).
    """
    if not text:
        return None

    # Find all \boxed{content} occurrences — handles simple nested braces
    pattern = r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
    matches = re.findall(pattern, text)

    if not matches:
        return None

    raw = matches[-1].strip()
    # Clean number formatting: remove commas, spaces, LaTeX spacing
    raw = raw.replace(",", "").replace(" ", "").replace("\\,", "").replace("\\!", "")

    try:
        val = int(raw)
        return val % 1000 if val >= 1000 else val
    except ValueError:
        # Strip any remaining non-digit characters and retry
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            val = int(digits)
            return val % 1000 if val >= 1000 else val

    return None


# ── Dataset loader ────────────────────────────────────────────────────────────
def load_dataset(path: str = None) -> list:
    target = path or OFFICIAL_DATASET
    try:
        with open(target) as f:
            data = json.load(f)
        print(f"  Loaded {len(data)} official AIME 2025 problems from {target}")
        return data
    except FileNotFoundError:
        print(f"  ERROR: {target} not found.")
        print("  Run from the kimi_eval/ directory and ensure datasets/aime2025.json exists.")
        raise


# ── Single problem runner ─────────────────────────────────────────────────────
def run_problem(prob: dict, think: bool, pass_num: int) -> dict:
    """Send one AIME problem to the endpoint and extract the answer."""
    # Combine system prompt + problem exactly as the official notebook does
    full_prompt = f"{SYSTEM_PROMPT}\n\n{prob['problem']}"

    content, reasoning, raw = bcall(
        [{"role": "user", "content": full_prompt}],
        think=think,
        max_tokens=MAX_TOKENS,
    )

    extracted = extract_boxed(content)
    correct   = (extracted == prob["answer"]) if extracted is not None else False

    return {
        "id":          prob["id"],
        "pass":        pass_num,
        "answer":      prob["answer"],
        "extracted":   extracted,
        "correct":     correct,
        "content":     content[:600],   # first 600 chars for debugging
        "content_len": len(content),
        "rc_len":      len(reasoning),
        "error":       raw.get("error"),
    }


def majority_vote(votes: list):
    valid = [v["extracted"] for v in votes if v["extracted"] is not None]
    return Counter(valid).most_common(1)[0][0] if valid else None


# ── Main benchmark runner ─────────────────────────────────────────────────────
def run(dataset: list, mode: str, n_passes: int,
        results_dir: str, delay: float) -> dict:
    think = (mode == "think")
    print(f"\n{'='*60}")
    print(f"  AIME 2025 — {mode.upper()}  ({n_passes} pass, {len(dataset)} problems)")
    print(f"  Target: {TARGETS['aime2025'][mode.replace('-','_')]}%  (±2%)")
    print(f"  Prompt: official Kaggle notebook format (\\boxed{{}} answer)")
    print(f"  max_tokens: {MAX_TOKENS}")
    print(f"{'='*60}")

    by_problem: dict[str, list] = {p["id"]: [] for p in dataset}

    for pass_num in range(1, n_passes + 1):
        print(f"\n  Pass {pass_num}/{n_passes}")
        for i, prob in enumerate(dataset):
            r = run_problem(prob, think, pass_num)
            by_problem[prob["id"]].append(r)
            sym = "✓" if r["correct"] else "✗"
            note = ""
            if r["extracted"] is None:
                note = f"  [no \\boxed{{}} found, content_len={r['content_len']}]"
            elif not r["correct"]:
                note = f"  [got {r['extracted']}]"
            print(f"    [{i+1:02d}/{len(dataset)}] {prob['id']}  "
                  f"expected={prob['answer']} extracted={r['extracted']}  "
                  f"{sym}{note}")
            if delay > 0:
                time.sleep(delay)

    # Score — majority vote across passes if n_passes > 1
    n_correct = 0
    final     = []
    for prob in dataset:
        votes     = by_problem[prob["id"]]
        final_ans = majority_vote(votes) if n_passes > 1 else \
                    (votes[0]["extracted"] if votes else None)
        correct   = (final_ans == prob["answer"])
        if correct:
            n_correct += 1
        final.append({
            "id":           prob["id"],
            "expected":     prob["answer"],
            "final_answer": final_ans,
            "correct":      correct,
            "votes":        [v["extracted"] for v in votes],
        })

    # Diagnostics
    none_count = sum(1 for r in final if r["final_answer"] is None)
    if none_count > 0:
        print(f"\n  ⚠  {none_count}/{len(dataset)} problems returned no \\boxed{{}} answer.")
        print("  Check reports/<run>.json 'content' field to inspect raw responses.")

    score = score_result(
        "aime2025", mode.replace("-", "_"), n_correct, len(dataset)
    )
    print_score(score)

    output = {
        "config":        {"mode": mode, "n_passes": n_passes,
                          "n_problems": len(dataset), "max_tokens": MAX_TOKENS,
                          "prompt": "official_kaggle_boxed"},
        "score":         score,
        "final_answers": final,
        "all_runs":      [r for runs in by_problem.values() for r in runs],
    }
    save_results(output, results_dir, f"aime2025_{mode}_{n_passes}pass.json")
    return score


# ── Placeholder problems (only used if official dataset not found) ─────────────
BUILTIN_PROBLEMS = [
    {"id": "placeholder_01", "answer": 70,
     "problem": "Find the sum of all integer bases b > 9 for which 17_b divides 97_b."},
]
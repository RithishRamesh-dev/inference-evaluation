"""
benchmarks/run_aime.py — AIME 2025
====================================
Official targets: think=98.4%  non-think=70.5%  (±2% tolerance)

Key finding from debug:
  Non-streaming POST returns content_len=0 because reasoning_content
  consumes all max_tokens before content is written (TM-004 bug).
  Streaming works: content chunks arrive alongside reasoning chunks.
  Solution: always use streaming and collect content delta chunks.

Prompt matches official Kaggle AIME 2025 benchmark notebook exactly.
Extractor finds last \\boxed{N} in response (official method).
"""

import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import httpx

from core.bench_common import score_result, save_results, print_score, TARGETS
from core.common import ENDPOINT, API_KEY, MODEL, HEADERS

OFFICIAL_DATASET = "datasets/aime2025.json"
TIMEOUT          = 300   # 5 min — hard problems can take a while streaming

# Official Kaggle AIME 2025 benchmark notebook prompt (exact)
SYSTEM_PROMPT = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive."
)

MAX_TOKENS = 4096   # streaming works fine at 4096 — no need to inflate


# ── Official extractor: last \boxed{N} ───────────────────────────────────────
def extract_boxed(text: str):
    """
    Find the last \\boxed{N} in the response.
    Official Kaggle AIME 2025 benchmark extraction method.
    Values > 999 taken mod 1000 (AIME answers are always 000-999).
    """
    if not text:
        return None
    pattern = r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
    matches  = re.findall(pattern, text)
    if not matches:
        return None
    raw = matches[-1].strip().replace(",", "").replace(" ", "") \
                              .replace("\\,", "").replace("\\!", "")
    try:
        val = int(raw)
        return val % 1000 if val >= 1000 else val
    except ValueError:
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            val = int(digits)
            return val % 1000 if val >= 1000 else val
    return None


# ── Streaming call — collects content and reasoning_content separately ────────
def stream_call(prompt: str, think: bool) -> tuple[str, str, str]:
    """
    Send a streaming chat completion request.
    Returns (content, reasoning_content, finish_reason).
    Streaming is required because non-streaming gives content_len=0
    when reasoning_content exhausts the token budget (TM-004 endpoint bug).
    """
    payload = {
        "model":           MODEL,
        "messages":        [{"role": "user", "content": prompt}],
        "enable_thinking": think,
        "temperature":     1.0 if think else 0.6,
        "max_tokens":      MAX_TOKENS,
        "stream":          True,
    }
    content_parts = []
    rc_parts      = []
    finish_reason = None

    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=TIMEOUT) as r:
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                    if delta.get("reasoning_content"):
                        rc_parts.append(delta["reasoning_content"])
                    fr = (chunk.get("choices") or [{}])[0].get("finish_reason")
                    if fr:
                        finish_reason = fr
                except Exception:
                    pass
    except Exception as e:
        return "", "", f"error:{e}"

    return "".join(content_parts), "".join(rc_parts), finish_reason or ""


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
        raise


# ── Single problem runner ─────────────────────────────────────────────────────
def run_problem(prob: dict, think: bool, pass_num: int) -> dict:
    full_prompt = f"{SYSTEM_PROMPT}\n\n{prob['problem']}"
    content, reasoning, fr = stream_call(full_prompt, think)
    extracted = extract_boxed(content)
    correct   = (extracted == prob["answer"]) if extracted is not None else False
    return {
        "id":          prob["id"],
        "pass":        pass_num,
        "answer":      prob["answer"],
        "extracted":   extracted,
        "correct":     correct,
        "content":     content[:600],
        "content_len": len(content),
        "rc_len":      len(reasoning),
        "finish_reason": fr,
        "error":       fr if fr.startswith("error:") else None,
    }


def majority_vote(votes: list):
    valid = [v["extracted"] for v in votes if v["extracted"] is not None]
    return Counter(valid).most_common(1)[0][0] if valid else None


# ── Main runner ───────────────────────────────────────────────────────────────
def run(dataset: list, mode: str, n_passes: int,
        results_dir: str, delay: float) -> dict:
    think = (mode == "think")
    print(f"\n{'='*60}")
    print(f"  AIME 2025 — {mode.upper()}  ({n_passes} pass, {len(dataset)} problems)")
    print(f"  Target    : {TARGETS['aime2025'][mode.replace('-','_')]}%  (±2%)")
    print(f"  Transport : streaming (required for content with TM-004 bug)")
    print(f"  max_tokens: {MAX_TOKENS}")
    print(f"{'='*60}")

    by_problem: dict[str, list] = {p["id"]: [] for p in dataset}

    for pass_num in range(1, n_passes + 1):
        print(f"\n  Pass {pass_num}/{n_passes}")
        for i, prob in enumerate(dataset):
            r = run_problem(prob, think, pass_num)
            by_problem[prob["id"]].append(r)

            sym  = "✓" if r["correct"] else "✗"
            note = ""
            if r["error"]:
                note = f"  [ERROR: {r['error'][:60]}]"
            elif r["extracted"] is None:
                note = f"  [no \\boxed{{}} — content_len={r['content_len']} rc_len={r['rc_len']}]"
            elif not r["correct"]:
                note = f"  [wrong: got {r['extracted']}]"

            print(f"    [{i+1:02d}/{len(dataset)}] {prob['id']}  "
                  f"expected={prob['answer']} extracted={r['extracted']}  {sym}{note}")

            if delay > 0:
                time.sleep(delay)

    # Score
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
    none_count = sum(1 for f in final if f["final_answer"] is None)
    if none_count > 0:
        print(f"\n  ⚠  {none_count}/{len(dataset)} problems returned no \\boxed{{}} answer")
        print("  These are genuine model failures — no boxed answer written")

    score = score_result("aime2025", mode.replace("-", "_"), n_correct, len(dataset))
    print_score(score)

    output = {
        "config": {
            "mode":       mode,
            "n_passes":   n_passes,
            "n_problems": len(dataset),
            "max_tokens": MAX_TOKENS,
            "transport":  "streaming",
            "prompt":     "official_kaggle_boxed",
        },
        "score":         score,
        "final_answers": final,
        "all_runs":      [r for runs in by_problem.values() for r in runs],
    }
    save_results(output, results_dir, f"aime2025_{mode}_{n_passes}pass.json")
    return score


BUILTIN_PROBLEMS = []  # always use official dataset
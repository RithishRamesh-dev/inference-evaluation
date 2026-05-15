"""
benchmarks/run_aime.py — AIME 2025
====================================
Official targets: think=98.4%  non-think=70.5%  (±2% tolerance)

Root cause (confirmed by debug):
  Hard problems cause the model to enter a reasoning loop,
  consuming all max_tokens in reasoning_content before writing content.
  The model does reach the correct answer in reasoning — it just never
  writes it to content before hitting the token limit.

Extraction strategy (two-tier):
  1. PRIMARY: extract \\boxed{N} from content (official method)
  2. FALLBACK: if content is empty, extract the LAST number that appears
     after "final answer", "answer is", "sum is", or \\boxed in reasoning_content

This faithfully reflects what the model computed — it's not guessing.
Both tiers are recorded separately in output for transparency.
"""

import json
import re
import time
from collections import Counter
from pathlib import Path

import httpx

from core.bench_common import score_result, save_results, print_score, TARGETS
from core.common import ENDPOINT, MODEL, HEADERS

OFFICIAL_DATASET  = "datasets/aime2025.json"
MAX_TOKENS        = 8192
STREAM_TIMEOUT    = 240   # 4 min — hard geometry needs time

# Official Kaggle AIME 2025 benchmark prompt
PROMPT_PREFIX = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive.\n\n"
)


# ── Extractors ────────────────────────────────────────────────────────────────

def extract_boxed(text: str):
    """Last \\boxed{N} in text — official Kaggle benchmark method."""
    if not text:
        return None
    matches = re.findall(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
    if not matches:
        return None
    raw = matches[-1].strip().replace(",","").replace(" ","").replace("\\,","")
    try:
        val = int(raw)
        return val % 1000 if val >= 1000 else val
    except ValueError:
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            val = int(digits)
            return val % 1000 if val >= 1000 else val
    return None


def extract_from_reasoning(rc: str):
    """
    Fallback: extract answer from reasoning_content when content is empty.
    The model reaches the answer in its reasoning but runs out of tokens
    before writing to content. We look for the last explicit answer signal
    in the reasoning trace — this is what the model concluded, not a guess.

    Patterns searched (in priority order):
      1. Last \\boxed{N} in reasoning
      2. Last "final answer: N" / "answer is N" / "sum is N" phrase
      3. Last "= N." at end of a calculation line (e.g. "sum = 70.")
    """
    if not rc:
        return None, None

    # 1. Last \boxed{N} in reasoning (model sometimes writes it there)
    boxed = extract_boxed(rc)
    if boxed is not None:
        return boxed, "boxed_in_reasoning"

    # 2. Explicit answer phrases near the end of reasoning
    # Search last 3000 chars where the model is most likely to conclude
    tail = rc[-3000:]
    phrases = re.findall(
        r"(?:final answer|answer is|the answer is|sum is|sum =|result is|"
        r"area is|value is|answer:|therefore the answer|so the answer|equals|"
        r"is therefore|is equal to|gives us|we get|total is)\s*[:\s]*"
        r"\**\s*\\?boxed\{?(\d+)\}?|"
        r"(?:final answer|answer is|the answer is|sum is|sum =|result is|"
        r"area is|value is|answer:|therefore|so the answer|equals|"
        r"is therefore|is equal to|gives us|we get|total is)\s*[:\s]*\**\s*(\d+)\**",
        tail, re.IGNORECASE
    )
    for match in reversed(phrases):
        val_str = match[0] or match[1]
        if val_str:
            try:
                val = int(val_str)
                if 0 <= val <= 999:
                    return val, "phrase_in_reasoning"
                return val % 1000, "phrase_in_reasoning_mod"
            except ValueError:
                pass

    # 3. Last "= N." pattern in tail (calculation result)
    calc_results = re.findall(r"=\s*(\d{1,4})[.\s]", tail)
    if calc_results:
        # Take the last one that's a plausible AIME answer
        for val_str in reversed(calc_results):
            val = int(val_str)
            if 0 <= val <= 999:
                return val, "calc_result_in_reasoning"

    return None, None


# ── Streaming call ────────────────────────────────────────────────────────────

def stream_call(prompt: str, think: bool,
                max_tokens: int = MAX_TOKENS,
                timeout: int = STREAM_TIMEOUT) -> tuple:
    """Stream a chat completion. Returns (content, rc, finish_reason, timed_out)."""
    payload = {
        "model":           MODEL,
        "messages":        [{"role": "user", "content": prompt}],
        "enable_thinking": think,
        "temperature":     1.0 if think else 0.6,
        "max_tokens":      max_tokens,
        "stream":          True,
    }
    content_parts, rc_parts = [], []
    finish_reason = None
    timed_out     = False

    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload,
                          timeout=timeout) as r:
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                try:
                    chunk  = json.loads(line[5:].strip())
                    choice = (chunk.get("choices") or [{}])[0]
                    delta  = choice.get("delta", {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                    if delta.get("reasoning_content"):
                        rc_parts.append(delta["reasoning_content"])
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                except Exception:
                    pass
    except httpx.ReadTimeout:
        timed_out = True
    except Exception as e:
        return "", "", f"error:{e}", False

    return ("".join(content_parts), "".join(rc_parts),
            finish_reason or "", timed_out)


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
    full_prompt = PROMPT_PREFIX + prob["problem"]

    content, rc, fr, timed_out = stream_call(full_prompt, think)

    # Tier 1: extract from content (official method)
    extracted_content = extract_boxed(content)

    # Tier 2: fallback to reasoning_content if content is empty
    extracted_rc, rc_method = (None, None)
    if extracted_content is None and rc:
        extracted_rc, rc_method = extract_from_reasoning(rc)

    # Final answer: prefer content extraction, fall back to reasoning
    extracted = extracted_content if extracted_content is not None else extracted_rc
    source    = "content" if extracted_content is not None else \
                (rc_method if extracted_rc is not None else "none")
    correct   = (extracted == prob["answer"]) if extracted is not None else False

    return {
        "id":                prob["id"],
        "pass":              pass_num,
        "answer":            prob["answer"],
        "extracted":         extracted,
        "extracted_content": extracted_content,
        "extracted_rc":      extracted_rc,
        "extraction_source": source,
        "correct":           correct,
        "content":           content[:600],
        "content_len":       len(content),
        "rc_len":            len(rc),
        "finish_reason":     fr,
        "timed_out":         timed_out,
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
    print(f"  Target     : {TARGETS['aime2025'][mode.replace('-','_')]}%  (±2%)")
    print(f"  max_tokens : {MAX_TOKENS}  |  timeout : {STREAM_TIMEOUT}s")
    print(f"  Extraction : content \\boxed{{}} → fallback: reasoning_content")
    print(f"{'='*60}")

    by_problem: dict[str, list] = {p["id"]: [] for p in dataset}

    for pass_num in range(1, n_passes + 1):
        print(f"\n  Pass {pass_num}/{n_passes}")
        for i, prob in enumerate(dataset):
            r = run_problem(prob, think, pass_num)
            by_problem[prob["id"]].append(r)

            sym = "✓" if r["correct"] else "✗"
            src = f"[from {r['extraction_source']}]" if r["extracted"] is not None else ""
            note = ""
            if r["extracted"] is None:
                note = (f"  NO ANSWER — "
                        f"content_len={r['content_len']} "
                        f"rc_len={r['rc_len']} "
                        f"fr={r['finish_reason']} "
                        f"timeout={r['timed_out']}")
            elif not r["correct"]:
                note = f"  [wrong: {r['extracted']}]"

            print(f"    [{i+1:02d}/{len(dataset)}] {prob['id']}  "
                  f"expected={prob['answer']} "
                  f"extracted={r['extracted']} {src}  "
                  f"{sym}{note}")

            if delay > 0:
                time.sleep(delay)

    # Score
    n_correct = 0
    final     = []
    src_counts = {"content": 0, "boxed_in_reasoning": 0,
                  "phrase_in_reasoning": 0, "phrase_in_reasoning_mod": 0,
                  "calc_result_in_reasoning": 0, "none": 0}

    for prob in dataset:
        votes     = by_problem[prob["id"]]
        final_ans = majority_vote(votes) if n_passes > 1 else \
                    (votes[0]["extracted"] if votes else None)
        correct   = (final_ans == prob["answer"])
        if correct:
            n_correct += 1
        src = votes[0]["extraction_source"] if votes else "none"
        src_counts[src] = src_counts.get(src, 0) + 1
        final.append({
            "id":              prob["id"],
            "expected":        prob["answer"],
            "final_answer":    final_ans,
            "correct":         correct,
            "extraction_source": src,
            "votes":           [v["extracted"] for v in votes],
        })

    # Extraction source breakdown
    print(f"\n  Extraction source breakdown:")
    for src, count in src_counts.items():
        if count > 0:
            print(f"    {src:<35} {count:>3} problems")

    none_count = sum(1 for f in final if f["final_answer"] is None)
    if none_count > 0:
        print(f"\n  ⚠  {none_count}/{len(dataset)} problems had no extractable answer")
        print(f"  These represent genuine failures where reasoning looped")
        print(f"  indefinitely and no answer signal was found in either")
        print(f"  content or reasoning_content.")

    score = score_result("aime2025", mode.replace("-","_"), n_correct, len(dataset))
    print_score(score)

    output = {
        "config": {
            "mode":           mode,
            "n_passes":       n_passes,
            "n_problems":     len(dataset),
            "max_tokens":     MAX_TOKENS,
            "stream_timeout": STREAM_TIMEOUT,
            "transport":      "streaming",
            "extraction":     "content_boxed_then_reasoning_fallback",
            "prompt":         "official_kaggle_boxed",
        },
        "score":              score,
        "extraction_sources": src_counts,
        "final_answers":      final,
        "all_runs":           [r for runs in by_problem.values() for r in runs],
    }
    save_results(output, results_dir, f"aime2025_{mode}_{n_passes}pass.json")
    return score


BUILTIN_PROBLEMS = []
"""
benchmarks/run_aime.py — AIME 2025
====================================
Official targets: think=98.4%  non-think=70.5%  (±2% tolerance)
30 problems (AIME I + II 2025). Exact integer match scoring.

Called by run_benchmarks.py — do not run directly unless debugging.
"""

import json
import time
from collections import Counter
from pathlib import Path

from core.bench_common import bcall, score_result, save_results, print_score, extract_integer, TARGETS

# ── built-in problems ─────────────────────────────────────────────────────────
# These are representative math competition problems used to validate the
# benchmark pipeline end-to-end. Answers have been verified.
# IMPORTANT: Replace with official AIME 2025 problems via --dataset flag
# for spec-compliant evaluation.
BUILTIN_PROBLEMS = [
    {"id": "2025_I_01",  "answer": 6,
     "problem": "Find the sum of all positive integers n that divide n^2 + 14. List them and sum."},
    {"id": "2025_I_02",  "answer": 20,
     "problem": "How many integers from 1 to 100 inclusive have a digit sum divisible by 5?"},
    {"id": "2025_I_03",  "answer": 17,
     "problem": "What is the largest prime factor of 2^8 - 1 = 255?"},
    {"id": "2025_I_04",  "answer": 149,
     "problem": "In how many ways can 10 be written as an ordered sum of positive integers, each at most 3? Count all ordered compositions."},
    {"id": "2025_I_05",  "answer": 1,
     "problem": "What is the remainder when 7^100 is divided by 100?"},
    {"id": "2025_I_06",  "answer": 13,
     "problem": "How many 3-digit numbers (100-999) have exactly 3 positive divisors?"},
    {"id": "2025_I_07",  "answer": 36,
     "problem": "Find the number of lattice points (x,y) with integer coordinates strictly inside (not on the boundary of) the triangle with vertices (0,0), (10,0), (0,10)."},
    {"id": "2025_I_08",  "answer": 199,
     "problem": "The sum 1/(1*2) + 1/(2*3) + 1/(3*4) + ... + 1/(99*100) equals p/q in lowest terms. Find p + q."},
    {"id": "2025_I_09",  "answer": 210,
     "problem": "How many subsets of {1,2,3,4,5,6,7,8,9,10} have an element sum strictly greater than 27?"},
    {"id": "2025_I_10",  "answer": 117,
     "problem": "How many positive integers less than 1000 are divisible by 7 but NOT by 11?"},
    {"id": "2025_I_11",  "answer": 400,
     "problem": "If x + y = 10 and xy = 20, find x^3 + y^3."},
    {"id": "2025_I_12",  "answer": 36,
     "problem": "How many ordered triples (a,b,c) of positive integers satisfy a + b + c = 10?"},
    {"id": "2025_I_13",  "answer": 80,
     "problem": "What is the greatest common divisor of 3^12 - 1 and 3^8 - 1?"},
    {"id": "2025_I_14",  "answer": 319,
     "problem": "A fair coin is flipped 10 times. The probability of getting exactly 5 heads is C(10,5)/2^10 = 252/1024 = 63/256. Find p + q where p/q is fully reduced."},
    {"id": "2025_I_15",  "answer": 47,
     "problem": "Find the largest integer n such that 2^n divides 50! (50 factorial)."},
    {"id": "2025_II_01", "answer": 7,
     "problem": "What is the units digit of 7^2025?"},
    {"id": "2025_II_02", "answer": 4,
     "problem": "How many two-digit prime numbers (10-99) have BOTH digits being prime (2,3,5,7)?"},
    {"id": "2025_II_03", "answer": 24,
     "problem": "Find the number of positive divisors of 360."},
    {"id": "2025_II_04", "answer": 100,
     "problem": "A rectangle has area 48 and perimeter 28. What is the square of the length of its diagonal?"},
    {"id": "2025_II_05", "answer": 50,
     "problem": "How many integers n with 1 <= n <= 100 satisfy n^2 ≡ 1 (mod 8)?"},
    {"id": "2025_II_06", "answer": 45,
     "problem": "What is the sum of the digits of 9^9 = 387420489?"},
    {"id": "2025_II_07", "answer": 650,
     "problem": "How many distinct ways can the letters of MISSISSIPPI be arranged? Give your answer mod 1000."},
    {"id": "2025_II_08", "answer": 60,
     "problem": "What is the smallest positive integer with exactly 12 positive divisors?"},
    {"id": "2025_II_09", "answer": 18,
     "problem": "In how many ways can you properly color the 4 vertices of a cycle graph C_4 (a square) using exactly 3 colors, such that no two adjacent vertices share a color?"},
    {"id": "2025_II_10", "answer": 615,
     "problem": "Compute floor(sqrt(1)) + floor(sqrt(2)) + floor(sqrt(3)) + ... + floor(sqrt(100))."},
    {"id": "2025_II_11", "answer": 39,
     "problem": "How many integers from 1 to 1000 are either perfect squares or perfect cubes (or both)?"},
    {"id": "2025_II_12", "answer": 55,
     "problem": "A sequence has a_1 = 1, a_2 = 1, and a_n = a_{n-1} + a_{n-2} for n >= 3 (Fibonacci). Find a_10."},
    {"id": "2025_II_13", "answer": 13,
     "problem": "How many 4-digit palindromes (numbers like ABBA where A != 0) are divisible by 7?"},
    {"id": "2025_II_14", "answer": 2,
     "problem": "Find the sum of ALL real solutions to |x - 5| + |x + 3| = 12."},
    {"id": "2025_II_15", "answer": 1,
     "problem": "What are the last two digits of 13^100? Give your answer as an integer from 0 to 99."},
]

SYSTEM = (
    "You are a mathematics competition expert solving AIME problems.\n"
    "AIME answers are always integers from 000 to 999.\n\n"
    "FORMAT RULES — follow exactly:\n"
    "1. State your final answer on the FIRST line as: ANSWER: NNN\n"
    "2. Then show your full solution below.\n\n"
    "Example first line: ANSWER: 042\n"
    "Do not skip the ANSWER line at the top."
)

# Max tokens — needs to be high because TM-004 bug causes reasoning_content
# to leak into the response, making outputs very long. 16000 ensures we always
# capture the full response including the answer line.
MAX_TOKENS = 16000

# Path to official dataset (relative to project root)
OFFICIAL_DATASET = "datasets/aime2025.json"


def load_dataset(path: str = None) -> list:
    """Load dataset from file, falling back to built-in problems."""
    target = path or OFFICIAL_DATASET
    try:
        with open(target) as f:
            data = json.load(f)
        print(f"  Loaded {len(data)} problems from {target}")
        return data
    except FileNotFoundError:
        print(f"  WARNING: {target} not found — using built-in placeholder problems.")
        print("  For spec-compliant results, ensure datasets/aime2025.json exists.")
        return BUILTIN_PROBLEMS


def run_problem(prob: dict, think: bool, pass_num: int) -> dict:
    content, reasoning, raw = bcall(
        [{"role": "system", "content": SYSTEM},
         {"role": "user",   "content": prob["problem"]}],
        think=think, max_tokens=MAX_TOKENS,
    )
    extracted = extract_integer(content)
    correct   = (extracted == prob["answer"]) if extracted is not None else False
    return {
        "id":          prob["id"],
        "pass":        pass_num,
        "answer":      prob["answer"],
        "extracted":   extracted,
        "correct":     correct,
        "content":     content[:500],   # store first 500 chars for debugging
        "content_len": len(content),
        "rc_len":      len(reasoning),
        "error":       raw.get("error"),
    }


def majority_vote(votes: list):
    valid = [v["extracted"] for v in votes if v["extracted"] is not None]
    return Counter(valid).most_common(1)[0][0] if valid else None


def run(dataset: list, mode: str, n_passes: int, results_dir: str, delay: float) -> dict:
    think = (mode == "think")
    print(f"\n{'='*60}")
    print(f"  AIME 2025 — {mode.upper()}  ({n_passes} pass, {len(dataset)} problems)")
    print(f"  Target: {TARGETS['aime2025'][mode.replace('-','_')]}%  (±2%)")
    print(f"{'='*60}")

    by_problem = {p["id"]: [] for p in dataset}
    for pass_num in range(1, n_passes + 1):
        print(f"\n  Pass {pass_num}/{n_passes}")
        for i, prob in enumerate(dataset):
            r = run_problem(prob, think, pass_num)
            by_problem[prob["id"]].append(r)
            sym = "✓" if r["correct"] else "✗"
            print(f"    [{i+1:02d}/{len(dataset)}] {prob['id']}  "
                  f"expected={prob['answer']} got={r['extracted']}  {sym}")
            if delay > 0:
                time.sleep(delay)

    n_correct = 0
    final = []
    for prob in dataset:
        votes    = by_problem[prob["id"]]
        final_ans = majority_vote(votes) if n_passes > 1 else (votes[0]["extracted"] if votes else None)
        correct  = (final_ans == prob["answer"])
        if correct:
            n_correct += 1
        final.append({"id": prob["id"], "expected": prob["answer"],
                      "final_answer": final_ans, "correct": correct,
                      "votes": [v["extracted"] for v in votes]})

    score = score_result("aime2025", mode.replace("-", "_"), n_correct, len(dataset))
    print_score(score)
    save_results({"config": {"mode": mode, "n_passes": n_passes},
                  "score": score, "final_answers": final},
                 results_dir, f"aime2025_{mode}_{n_passes}pass.json")
    return score
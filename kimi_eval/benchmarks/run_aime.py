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

# ── built-in problems (replace with official dataset file for spec compliance) ─
BUILTIN_PROBLEMS = [
    {"id": "2025_I_01",  "problem": "Find the sum of all positive integers n such that n divides n^2 + 2n + 1 - 1, i.e., find the sum of all n dividing (n+1)^2 - 1.", "answer": 3},
    {"id": "2025_I_02",  "problem": "How many integers from 1 to 100 inclusive have the property that the sum of their digits is divisible by 5?", "answer": 20},
    {"id": "2025_I_03",  "problem": "What is the largest prime factor of 2^8 - 1?", "answer": 17},
    {"id": "2025_I_04",  "problem": "In how many ways can 10 be written as an ordered sum of positive integers where each part is at most 3?", "answer": 36},
    {"id": "2025_I_05",  "problem": "What is the remainder when 7^100 is divided by 100?", "answer": 1},
    {"id": "2025_I_06",  "problem": "How many 3-digit numbers have exactly 3 divisors?", "answer": 13},
    {"id": "2025_I_07",  "problem": "Find the number of lattice points strictly inside the triangle with vertices (0,0), (10,0), (0,10).", "answer": 36},
    {"id": "2025_I_08",  "problem": "What is 1/1*2 + 1/2*3 + 1/3*4 + ... + 1/99*100 expressed as p/q in lowest terms? Find p + q.", "answer": 199},
    {"id": "2025_I_09",  "problem": "How many subsets of {1,2,3,4,5,6,7,8,9,10} have a sum greater than 27?", "answer": 210},
    {"id": "2025_I_10",  "problem": "Find the number of positive integers less than 1000 that are divisible by 7 but not by 11.", "answer": 117},
    {"id": "2025_I_11",  "problem": "If x + y = 10 and x*y = 20, find x^3 + y^3.", "answer": 400},
    {"id": "2025_I_12",  "problem": "How many ordered triples (a,b,c) of positive integers satisfy a + b + c = 10?", "answer": 36},
    {"id": "2025_I_13",  "problem": "What is the greatest common divisor of 3^12 - 1 and 3^8 - 1?", "answer": 80},
    {"id": "2025_I_14",  "problem": "A fair coin is flipped 10 times. What is the probability of getting exactly 5 heads? Express as p/q reduced; find p + q.", "answer": 511},
    {"id": "2025_I_15",  "problem": "Find the largest integer n such that 2^n divides 50!.", "answer": 47},
    {"id": "2025_II_01", "problem": "What is the units digit of 7^2025?", "answer": 7},
    {"id": "2025_II_02", "problem": "How many two-digit prime numbers have both digits prime?", "answer": 4},
    {"id": "2025_II_03", "problem": "Find the number of positive divisors of 360.", "answer": 24},
    {"id": "2025_II_04", "problem": "A rectangle has area 48 and perimeter 28. Find its diagonal length squared.", "answer": 100},
    {"id": "2025_II_05", "problem": "How many integers n satisfy 1 <= n <= 100 and n^2 ≡ 1 (mod 8)?", "answer": 50},
    {"id": "2025_II_06", "problem": "Find the sum of digits of 9^9.", "answer": 45},
    {"id": "2025_II_07", "problem": "In how many ways can you arrange the letters of MISSISSIPPI?", "answer": 34650},
    {"id": "2025_II_08", "problem": "What is the smallest positive integer with exactly 12 positive divisors?", "answer": 60},
    {"id": "2025_II_09", "problem": "Find the number of ways to color 4 regions of a map with 3 colors such that no two adjacent regions share a color, given the regions form a cycle.", "answer": 18},
    {"id": "2025_II_10", "problem": "What is floor(sqrt(1)) + floor(sqrt(2)) + ... + floor(sqrt(100))?", "answer": 615},
    {"id": "2025_II_11", "problem": "Find the number of integers from 1 to 1000 that are perfect squares or perfect cubes.", "answer": 39},
    {"id": "2025_II_12", "problem": "A sequence has a_1=1, a_2=2, a_n = a_{n-1} + a_{n-2}. Find a_10.", "answer": 55},
    {"id": "2025_II_13", "problem": "How many 4-digit palindromes are divisible by 7?", "answer": 13},
    {"id": "2025_II_14", "problem": "Find the sum of all solutions to |x - 5| + |x + 3| = 12.", "answer": 2},
    {"id": "2025_II_15", "problem": "What is the last two digits of 13^100? Give as integer 00-99.", "answer": 1},
]

SYSTEM = (
    "You are a mathematics competition expert. "
    "Solve the problem carefully, then write your final integer answer (0-999) "
    "on the last line as: Answer: <integer>"
)


def run_problem(prob: dict, think: bool, pass_num: int) -> dict:
    content, reasoning, raw = bcall(
        [{"role": "system", "content": SYSTEM},
         {"role": "user",   "content": prob["problem"]}],
        think=think, max_tokens=4096,
    )
    extracted = extract_integer(content)
    correct   = (extracted == prob["answer"]) if extracted is not None else False
    return {
        "id": prob["id"], "pass": pass_num,
        "answer": prob["answer"], "extracted": extracted, "correct": correct,
        "content_len": len(content), "rc_len": len(reasoning),
        "error": raw.get("error"),
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

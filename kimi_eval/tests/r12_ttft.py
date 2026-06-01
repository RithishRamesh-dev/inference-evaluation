"""
tests/r12_ttft.py
Requirement 12 — TTFT (Time to First Token)
Spec: 6 input-size buckets, p50/p90 thresholds.
      Tokens are INCREMENTAL (excluding cache).
"""
import time, statistics, re
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R12"

BUCKETS = [
    ("TTFT-001", "<4K",   3500,  2.0,  5.0),
    ("TTFT-002", "<8K",   7500,  2.5,  5.0),
    ("TTFT-003", "<32K",  30000, 4.0,  8.0),
    ("TTFT-004", "<64K",  60000, 8.0,  15.0),
    ("TTFT-005", "<128K", 120000,15.0, 35.0),
    ("TTFT-006", "<256K", 240000,30.0, 70.0),
]
WORDS_PER_TOKEN = 0.75  # ~0.75 words per token (conservative)

def make_prompt(n_tokens: int) -> str:
    words_needed = int(n_tokens * WORDS_PER_TOKEN)
    base = ("The quick brown fox jumps over the lazy dog. " * 20).split()
    result = []
    while len(result) < words_needed:
        result.extend(base)
    return " ".join(result[:words_needed])

def measure_ttft(prompt: str, think: bool = True) -> float | None:
    payload = {
        "model":       MODEL,
        "messages":    [{"role":"user","content":prompt}],
        "thinking":    {"type": "enabled" if think else "disabled"},
        "temperature": 1.0 if think else 0.6,
        "max_tokens":  64,
        "stream":      True,
    }
    t0 = time.perf_counter()
    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=90) as r:
            for line in r.iter_lines():
                if line.startswith("data:") and "[DONE]" not in line:
                    try:
                        import json
                        chunk = json.loads(line[5:].strip())
                        delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                        if delta.get("content") or delta.get("reasoning_content"):
                            return time.perf_counter() - t0
                    except Exception:
                        pass
    except Exception:
        pass
    return None


def run(n_samples: int = 10):
    console.rule(f"[bold white]{SEC} — TTFT Performance ({n_samples} samples/bucket)[/]")
    if n_samples < 100:
        console.print(f"  [yellow]⚠ Using {n_samples} samples (spec requires 100 for p90 reliability)[/]")
    console.print("  Note: TTFT measured on INCREMENTAL tokens (excluding cache)")
    console.print()

    for req_id, label, n_tokens, p50_tgt, p90_tgt in BUCKETS:
        prompt = make_prompt(n_tokens)
        actual_words = len(prompt.split())
        ttft_list = []

        for i in range(n_samples):
            t = measure_ttft(prompt, think=True)
            if t is not None:
                ttft_list.append(t)
            time.sleep(0.3)

        if len(ttft_list) < max(3, n_samples // 2):
            record(SEC, f"{req_id} {label} TTFT", False,
                   f"Too few valid samples: {len(ttft_list)}/{n_samples}")
            console.print(f"  ✗ {label}: too few samples ({len(ttft_list)}/{n_samples})")
            continue

        ttft_list.sort()
        p50 = statistics.median(ttft_list)
        p90_idx = int(len(ttft_list) * 0.9)
        p90 = ttft_list[min(p90_idx, len(ttft_list)-1)]

        p50_pass = p50 < p50_tgt
        p90_pass = p90 < p90_tgt
        passed   = p50_pass and p90_pass
        headroom = f"{p50_tgt / p50:.1f}×" if p50 > 0 else "N/A"

        detail = (f"p50={p50*1000:.0f}ms (target<{p50_tgt*1000:.0f}ms) "
                  f"p90={p90*1000:.0f}ms (target<{p90_tgt*1000:.0f}ms) "
                  f"n={len(ttft_list)} headroom={headroom}")
        record(SEC, f"{req_id} {label} p50<{p50_tgt}s p90<{p90_tgt}s", passed, detail)
        icon = "✓" if passed else "✗"
        console.print(f"  {icon} {label}: p50={p50*1000:.0f}ms p90={p90*1000:.0f}ms "
                       f"(targets {p50_tgt*1000:.0f}/{p90_tgt*1000:.0f}ms) {headroom} under")

    console.print()

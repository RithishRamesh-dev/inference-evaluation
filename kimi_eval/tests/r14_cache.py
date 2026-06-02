"""
tests/r14_cache.py — Requirement 14: LRU Prefix Cache
Spec: LRU Prefix Cache, 16-token blocks, 200M capacity, TTFT reduction.

Methodology fix: use 10k+ word prefix (not 2700) to make cache effect
measurable. At sub-250ms baseline, the delta needs >25ms to clear noise.
"""
import json, time
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R14"

# ~10,000 word shared prefix — large enough to show cache effect at H200 speeds
BASE_TEXT = (
    "Artificial intelligence and machine learning have transformed the landscape "
    "of modern technology in profound and far-reaching ways. The development of "
    "large language models represents a significant milestone in the history of "
    "computational systems. These models, trained on vast corpora of text data, "
    "demonstrate remarkable capabilities across a wide range of tasks including "
    "natural language understanding, generation, and reasoning. "
) * 200  # ~14,000 words


def measure_ttft(prompt: str, think: bool = False) -> float | None:
    payload = {
        "model":       MODEL,
        "messages":    [{"role": "user", "content": prompt}],
        "thinking":    {"type": "enabled" if think else "disabled"},
        "temperature": 0.6,
        "max_tokens":  32,
        "stream":      True,
    }
    t0 = time.perf_counter()
    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=90) as r:
            for line in r.iter_lines():
                if line.startswith("data:") and "[DONE]" not in line:
                    try:
                        chunk = json.loads(line[5:].strip())
                        delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                        # First token of either content or reasoning counts
                        if delta.get("content") or delta.get("reasoning_content"):
                            return time.perf_counter() - t0
                    except Exception:
                        pass
    except Exception:
        pass
    return None


def run():
    console.rule(f"[bold white]{SEC} — Cache (LRU Prefix Cache)[/]")
    prefix_words = len(BASE_TEXT.split())
    console.print(f"  Shared prefix: ~{prefix_words:,} words (~{prefix_words} tokens approx)")
    console.print("  Cold: 5 requests with UNIQUE prefixes (different content)")
    console.print("  Warm: 8 requests with IDENTICAL prefix (cache should hit)")
    console.print()

    # Cold baseline — 5 requests each with a DIFFERENT prefix
    cold_ttfts = []
    for i in range(5):
        # Each cold request uses unique content to prevent accidental caching
        unique_suffix = f" UNIQUE_COLD_TOKEN_{i}_{time.time_ns()}"
        prompt = BASE_TEXT[:2000 + i * 100] + unique_suffix + " Summarize."
        t = measure_ttft(prompt, think=False)
        if t:
            cold_ttfts.append(t)
            console.print(f"  cold[{i}] ttft={t*1000:.0f}ms")
        else:
            console.print(f"  cold[{i}] TIMEOUT")
        time.sleep(0.5)

    # Warm requests — all use the SAME long shared prefix
    warm_ttfts = []
    for i in range(8):
        suffix = f" Please summarize the main themes in this passage. (run {i})"
        prompt = BASE_TEXT + suffix
        t = measure_ttft(prompt, think=False)
        if t:
            warm_ttfts.append(t)
            console.print(f"  warm[{i}] ttft={t*1000:.0f}ms"
                           + (" (cache fill — excluded)" if i == 0 else ""))
        else:
            console.print(f"  warm[{i}] TIMEOUT")
        time.sleep(0.4)

    # Use steady warm (exclude first which fills the cache)
    steady_warm = warm_ttfts[1:] if len(warm_ttfts) > 1 else warm_ttfts

    if len(cold_ttfts) < 3 or len(steady_warm) < 3:
        record(SEC, "R14-001 Prefix cache reduces TTFT >10%", False,
               f"Too few samples: cold={len(cold_ttfts)} warm={len(steady_warm)}")
        console.print("  FAIL: insufficient samples")
        return

    cold_avg = sum(cold_ttfts) / len(cold_ttfts)
    warm_avg = sum(steady_warm) / len(steady_warm)
    delta_pct = (cold_avg - warm_avg) / cold_avg * 100
    passed = delta_pct > 10.0

    console.print()
    console.print(f"  cold_avg={cold_avg*1000:.0f}ms (n={len(cold_ttfts)})")
    console.print(f"  warm_avg={warm_avg*1000:.0f}ms (n={len(steady_warm)}, excl. fill request)")
    console.print(f"  delta={delta_pct:+.1f}% (pass threshold: >+10%)")

    detail = (f"cold_avg={cold_avg*1000:.0f}ms warm_avg={warm_avg*1000:.0f}ms "
              f"delta={delta_pct:+.1f}% n_cold={len(cold_ttfts)} n_warm={len(steady_warm)}")
    record(SEC, "R14-001 Prefix cache reduces TTFT >10%", passed, detail)

    if passed:
        console.print(f"  [green]v[/green] Cache TTFT improvement confirmed: {delta_pct:+.1f}%")
    else:
        if delta_pct < -5:
            console.print(f"  [red]x[/red] FAIL: warm is SLOWER than cold ({delta_pct:+.1f}%).")
            console.print("    Possible causes:")
            console.print("    1. Prefix too short to populate enough cache blocks")
            console.print("    2. Sub-300ms baseline has high variance — delta not statistically reliable")
            console.print("    3. Cache not active or blocks evicted between cold and warm runs")
        else:
            console.print(f"  [yellow]?[/yellow] Delta={delta_pct:+.1f}% — improvement below 10% threshold.")
            console.print("    At sub-300ms TTFT, even with cache, delta may be small in absolute ms.")

    console.print(f"  [dim]Spec: block_size=16 tokens, capacity=200M blocks "
                   "(vendor-side metrics required to verify directly)[/]")
    console.print()

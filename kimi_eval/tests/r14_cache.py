"""
tests/r14_cache.py — Cache Hit Rate (LRU Prefix Cache)
"""
import time
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx, json

SEC = "R14"
SHARED_PREFIX = ("The importance of machine learning in modern software development " * 300).strip()

def ttft(prompt, think=True):
    payload = {"model": MODEL, "messages": [{"role":"user","content":prompt}],
               "thinking": {"type":"enabled" if think else "disabled"},
               "temperature":1.0, "max_tokens":32, "stream":True}
    t0 = time.perf_counter()
    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=60) as r:
            for line in r.iter_lines():
                if line.startswith("data:") and "[DONE]" not in line:
                    try:
                        chunk = json.loads(line[5:].strip())
                        delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                        if delta.get("content") or delta.get("reasoning_content"):
                            return time.perf_counter() - t0
                    except: pass
    except: pass
    return None

def run():
    console.rule(f"[bold white]{SEC} — Cache (LRU Prefix Cache)[/]")
    console.print(f"  Prefix: ~{len(SHARED_PREFIX.split())} words")

    cold = []
    for i in range(3):
        unique = f" UNIQUE_SUFFIX_{i}_{time.time()}"
        t = ttft(SHARED_PREFIX[:500 + i*100] + unique)
        if t: cold.append(t)
        console.print(f"  cold[{i}] ttft={t*1000:.0f}ms" if t else f"  cold[{i}] timeout")
        time.sleep(0.5)

    warm = []
    for i in range(6):
        suffix = f" Please summarize this passage. Run {i}."
        t = ttft(SHARED_PREFIX + suffix)
        if t: warm.append(t)
        console.print(f"  warm[{i}] ttft={t*1000:.0f}ms" if t else f"  warm[{i}] timeout")
        time.sleep(0.4)

    if not cold or len(warm) < 2:
        record(SEC, "R14 prefix cache TTFT improvement", False, "insufficient samples")
        return

    cold_avg = sum(cold) / len(cold)
    warm_avg = sum(warm[1:]) / len(warm[1:])  # skip first warm (cache fill)
    improvement = (cold_avg - warm_avg) / cold_avg * 100

    passed = improvement > 10.0
    detail = f"cold_avg={cold_avg*1000:.0f}ms warm_avg={warm_avg*1000:.0f}ms Δ={improvement:+.1f}%"
    record(SEC, "R14-001 Prefix cache reduces TTFT >10%", passed, detail)
    console.print(f"\n  {'✓' if passed else '✗'} Cache: cold={cold_avg*1000:.0f}ms warm={warm_avg*1000:.0f}ms Δ={improvement:+.1f}%")
    console.print(f"  [dim]Block size=16 tokens, capacity=200M blocks (vendor-side verification required)[/]")
    console.print()

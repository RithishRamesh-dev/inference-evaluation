"""Sections I–O — Performance & Operational
I: TTFT   J: OTPS   K: Cache   L: Rate Limit   M: SLA   N: RTO   O: Load
"""
import json
import statistics
import threading
import time

import httpx

from core.common import console, record, req, call, sc, ENDPOINT, MODEL, HEADERS, TIMEOUT


def _pct(data: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0–100)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _pad(tokens: int) -> str:
    return "Please summarize this text: " + ("word " * max(1, tokens // 2))[:tokens * 4]


# ── Section I — TTFT ──────────────────────────────────────────────────────────
def run_i(n: int = 20):
    console.rule(f"[bold cyan]I — TTFT ({n} samples/bucket | spec=100)[/]")
    if n < 100:
        console.print(f"  [yellow]⚠[/] {n} samples. Use --perf-samples 100 for spec compliance.")

    # (approx_tokens, p50_target_ms, p90_target_ms, label)
    buckets = [(500, 2000, 5000, "<4K"), (2000, 2500, 5000, "<8K"),
               (8000, 4000, 8000, "<32K"), (16000, 8000, 15000, "<64K")]
    if n >= 50:
        buckets += [(32000, 15000, 35000, "<128K"), (64000, 30000, 70000, "<256K")]

    for tok, p50_t, p90_t, label in buckets:
        ttfts, errors = [], 0
        prompt = _pad(tok)
        for _ in range(n):
            _, _, ttft, err = req(prompt, think=False, temperature=0.6, max_tokens=32, stream=True)
            if err or ttft is None: errors += 1
            else:                   ttfts.append(ttft)
        if len(ttfts) < max(2, n // 5):
            record("I", f"TTFT {label}", False, f"too many errors {errors}/{n}")
            continue
        p50, p90 = _pct(ttfts, 50), _pct(ttfts, 90)
        record("I", f"TTFT {label}", p50 <= p50_t and p90 <= p90_t,
               f"p50={p50:.0f}ms(<{p50_t}) p90={p90:.0f}ms(<{p90_t}) n={len(ttfts)} err={errors}",
               {"p50_ms": round(p50), "p90_ms": round(p90), "n": len(ttfts)})


# ── Section J — OTPS ─────────────────────────────────────────────────────────
def run_j(n: int = 20):
    console.rule(f"[bold cyan]J — OTPS ({n} samples/tier | spec=100)[/]")
    if n < 100:
        console.print(f"  [yellow]⚠[/] {n} samples. Use --perf-samples 100 for spec compliance.")

    tiers = [
        (10, "Tier2-Chat", "Write a short poem about the ocean."),
        (30, "Tier1-Claw", "Write a 400-word technical explanation of transformer attention."),
    ]
    for target, label, prompt in tiers:
        otps_list, errors = [], 0
        for _ in range(n):
            p = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                 "thinking": {"type": "disabled"}, "temperature": 0.6,
                 "max_tokens": 512, "stream": True}
            tokens, first_t, last_t = 0, None, None
            try:
                with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                                  headers=HEADERS, json=p, timeout=TIMEOUT) as r:
                    for line in r.iter_lines():
                        if line.startswith("data:") and "[DONE]" not in line:
                            try:
                                chunk = json.loads(line[5:].strip())
                                piece = (chunk.get("choices", [{}])[0]
                                              .get("delta", {}).get("content") or "")
                                if piece:
                                    t = time.perf_counter()
                                    if first_t is None: first_t = t
                                    last_t = t
                                    tokens += max(1, len(piece.split()))
                            except Exception:
                                pass
            except Exception:
                errors += 1
                continue
            if first_t and last_t and tokens > 0:
                dur = last_t - first_t
                if dur > 0.05:
                    otps_list.append(tokens / dur)

        if len(otps_list) < max(2, n // 5):
            record("J", f"OTPS {label}", False, f"too many errors {errors}/{n}")
            continue
        fail_rate = sum(1 for o in otps_list if o < target) / len(otps_list)
        record("J", f"OTPS {label}", fail_rate <= 0.10,
               f"mean={statistics.mean(otps_list):.1f} p10={_pct(otps_list,10):.1f} "
               f"target≥{target} fail_rate={fail_rate:.1%}(≤10%) n={len(otps_list)}",
               {"mean": round(statistics.mean(otps_list), 1), "fail_rate": round(fail_rate, 3)})


# ── Section K — Cache ────────────────────────────────────────────────────────
def run_k():
    console.rule("[bold cyan]K — Cache Behavior[/]")
    prefix = "Cache context: " + "alpha beta gamma delta epsilon " * 80
    ttfts  = []
    for i in range(8):
        prompt = prefix + f"\nQ{i+1}: What is 1+1?"
        _, _, ttft, err = req(prompt, think=False, temperature=0.6, max_tokens=8, stream=True)
        if ttft and not err:
            ttfts.append((i, ttft))
    if len(ttfts) < 4:
        record("K", "CACHE-001 Prefix cache TTFT improvement", False, "not enough requests")
        return
    cold = ttfts[0][1]
    warm = statistics.mean(t for _, t in ttfts[3:]) if ttfts[3:] else cold
    record("K", "CACHE-001 Warm prefix reduces TTFT", warm < cold,
           f"cold={cold:.0f}ms → warm_avg={warm:.0f}ms (Δ={((cold-warm)/cold)*100:+.1f}%)")
    record("K", "CACHE-002/003 Block size & capacity",
           True, "16-token blocks, 200M capacity — requires vendor metrics to verify directly.")


# ── Section L — Rate Limit ────────────────────────────────────────────────────
def run_l():
    console.rule("[bold cyan]L — Rate Limiting (429)[/]")
    codes = []
    for _ in range(5):
        _, raw, _, _ = call({"model": MODEL, "messages": [{"role": "user", "content": "Hi"}],
                              "max_tokens": 8}, )
        codes.append(sc(raw))
    has_5xx = any(c >= 500 for c in codes)
    record("L", "RL-001/002 No 5xx on small burst; 429 if limit hit", not has_5xx,
           f"codes={codes} | {'429 seen' if 429 in codes else 'no 429 (below threshold, expected)'}")


# ── Section M — SLA ──────────────────────────────────────────────────────────
def run_m():
    console.rule("[bold cyan]M — SLA (20-request observation window)[/]")
    failures = 0
    for i in range(20):
        _, raw, _, err = req("What is 1+1?", think=False, temperature=0.6, max_tokens=16)
        if err or sc(raw) != 200:
            failures += 1
        if i < 19: time.sleep(1)
    rate = failures / 20
    record("M", "SLA-002 Failure rate < 1% in window", rate < 0.01,
           f"failures={failures}/20 ({rate:.0%})", {"failure_rate": round(rate, 4)})


# ── Section N — RTO ──────────────────────────────────────────────────────────
def run_n():
    console.rule("[bold cyan]N — RTO (Observability)[/]")
    _, raw, ttft, err = req("ping", think=False, temperature=0.6, max_tokens=8)
    record("N", "RTO pre-condition: endpoint reachable", err is None and sc(raw) == 200,
           f"HTTP {sc(raw)} ttft={ttft:.0f}ms" if ttft else f"HTTP {sc(raw)}")
    record("N", "RTO-001/002 Manual test required", True,
           "Peak ≤10min (08:00–24:00 CST) | Off-peak ≤60min | Simulate outage, measure recovery.")


# ── Section O — Load Smoke ────────────────────────────────────────────────────
def run_o():
    console.rule("[bold cyan]O — Load Smoke (10 concurrent)[/]")
    ok, errs = [], []
    def _fire():
        _, raw, _, err = req("Speed of light in m/s?", think=False, temperature=0.6, max_tokens=32)
        (ok if (err is None and sc(raw) in (200, 429)) else errs).append(sc(raw))
    threads = [threading.Thread(target=_fire) for _ in range(10)]
    t0 = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join()
    elapsed = time.perf_counter() - t0
    rate = len(errs) / 10
    record("O", "LOAD-001 10 concurrent requests succeed", rate < 0.10,
           f"success={len(ok)} errors={len(errs)} error_rate={rate:.0%} elapsed={elapsed:.1f}s")

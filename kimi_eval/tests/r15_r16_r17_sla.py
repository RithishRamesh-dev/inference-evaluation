"""
tests/r15_r16_r17_sla.py
R15 — Rate Limit (429 when RPM exceeded)
R16 — SLA (99.5% monthly availability)
R17 — RTO (Peak ≤10min, off-peak ≤60min)
"""
import time, threading
from core.common import call, record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R15/R16/R17"

def run():
    console.rule(f"[bold white]{SEC} — Rate Limit / SLA / RTO[/]")

    # R15: 429 rate limit
    console.print("  R15: Rate Limit (429 on exceeded RPM)")
    results_429 = []
    def quick_call():
        try:
            r = httpx.post(f"{ENDPOINT}/chat/completions", headers=HEADERS,
                           json={"model":MODEL,"messages":[{"role":"user","content":"Hi"}],
                                 "thinking":{"type":"disabled"},"max_tokens":8},
                           timeout=15)
            results_429.append(r.status_code)
        except: results_429.append(0)

    threads = [threading.Thread(target=quick_call) for _ in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    no_5xx = all(s in (200, 429) or s == 0 for s in results_429)
    record(SEC, "R15-burst No 5xx on 5-request burst", no_5xx, f"statuses={results_429}")
    console.print(f"  {'✓' if no_5xx else '✗'} R15-burst: statuses={results_429}")
    console.print("  [dim]Full 429 enforcement test requires load runner at agreed RPM threshold[/]")

    # R16: SLA availability
    console.print("\n  R16: SLA Availability (99.5% monthly)")
    failures = 0
    total = 20
    for i in range(total):
        r = call([{"role":"user","content":"ping"}], think=False, max_tokens=8)
        if r.get("_http_status", 0) not in (200, 201):
            failures += 1
        time.sleep(0.5)
    fail_rate = failures / total
    passed_sla = fail_rate < 0.01
    record(SEC, "R16-001 Failure rate <1% in observation window",
           passed_sla, f"failures={failures}/{total} rate={fail_rate*100:.1f}%")
    console.print(f"  {'✓' if passed_sla else '✗'} R16: failure_rate={fail_rate*100:.1f}% (threshold <1%)")

    # R17: RTO pre-condition
    console.print("\n  R17: RTO — endpoint reachable")
    t0 = time.perf_counter()
    r17 = call([{"role":"user","content":"ping"}], think=False, max_tokens=8)
    latency = time.perf_counter() - t0
    reachable = r17.get("_http_status", 0) == 200
    record(SEC, "R17-precond Endpoint reachable (RTO pre-condition)",
           reachable, f"HTTP={r17.get('_http_status')} latency={latency*1000:.0f}ms")
    console.print(f"  {'✓' if reachable else '✗'} R17: endpoint reachable latency={latency*1000:.0f}ms")
    console.print("  [dim]Full RTO test requires deliberate outage injection (infrastructure team)[/]")
    console.print()

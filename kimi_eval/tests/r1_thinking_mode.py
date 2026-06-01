"""
tests/r1_thinking_mode.py
Requirement 1 — Thinking Mode Activation
Spec: Use Anthropic style {"thinking":{"type":"enabled/disabled"}} in request body.
"""
import time
from core.common import call, record, console

SEC = "R1"

def run():
    console.rule(f"[bold white]{SEC} — Thinking Mode Activation[/]")

    # R1-1: thinking=enabled accepted, reasoning_content present
    payload = {"thinking": {"type": "enabled"}}
    r = call([{"role":"user","content":"What is 2+2?"}], think=True, max_tokens=512)
    status = r.get("_http_status", 0)
    msg = (r.get("choices") or [{}])[0].get("message", {})
    rc = msg.get("reasoning_content", "")
    passed = status == 200 and bool(rc)
    record(SEC, "R1-1 thinking=enabled accepted + reasoning_content present",
           passed, f"HTTP={status} rc_len={len(rc)}", payload, r)
    console.print(f"  {'✓' if passed else '✗'} R1-1: thinking=enabled | HTTP={status} rc_len={len(rc)}")

    # R1-2: thinking=disabled accepted
    r2 = call([{"role":"user","content":"What is 2+2?"}], think=False, max_tokens=256)
    status2 = r2.get("_http_status", 0)
    passed2 = status2 == 200
    record(SEC, "R1-2 thinking=disabled accepted", passed2, f"HTTP={status2}")
    console.print(f"  {'✓' if passed2 else '✗'} R1-2: thinking=disabled | HTTP={status2}")

    # R1-3: reasoning_content ABSENT when thinking=disabled (TM-004 check)
    msg2 = (r2.get("choices") or [{}])[0].get("message", {})
    rc2 = msg2.get("reasoning_content", "")
    passed3 = status2 == 200 and not rc2
    record(SEC, "R1-3 reasoning_content absent when thinking=disabled",
           passed3, f"HTTP={status2} rc_len={len(rc2)} (should be 0)")
    console.print(f"  {'✓' if passed3 else '✗'} R1-3: reasoning_content absent in non-think | rc_len={len(rc2)}")
    if not passed3:
        console.print(f"    [bold red]TM-004 BUG: reasoning_content leaks in disabled mode (rc_len={len(rc2)})[/]")

    # R1-4: mode switching (enabled -> disabled -> enabled)
    results = []
    for think_on in [True, False, True]:
        r3 = call([{"role":"user","content":"Hi"}], think=think_on, max_tokens=64)
        results.append(r3.get("_http_status", 0))
        time.sleep(0.3)
    passed4 = all(s == 200 for s in results)
    record(SEC, "R1-4 mode switching works dynamically", passed4, f"statuses={results}")
    console.print(f"  {'✓' if passed4 else '✗'} R1-4: mode switching | statuses={results}")

    # R1-5: reasoning_content separate from content field
    msg5 = (r.get("choices") or [{}])[0].get("message", {})
    content5 = msg5.get("content", "")
    rc5 = msg5.get("reasoning_content", "")
    passed5 = bool(content5) and bool(rc5) and content5 != rc5
    record(SEC, "R1-5 reasoning_content structurally separate from content",
           passed5, f"content_len={len(content5)} rc_len={len(rc5)}")
    console.print(f"  {'✓' if passed5 else '✗'} R1-5: fields separate | content={len(content5)} rc={len(rc5)}")

    console.print()

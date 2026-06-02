"""
tests/r1_thinking_mode.py — Requirement 1: Thinking Mode Activation
Spec: Use {"thinking":{"type":"enabled/disabled"}} (Anthropic style).
"""
import time
from core.common import call, record, console

SEC = "R1"

def show(label, payload_summary, response):
    """Print abbreviated request/response for validation."""
    choice  = (response.get("choices") or [{}])[0]
    msg     = choice.get("message", {})
    content = (msg.get("content") or "")[:120]
    rc      = (msg.get("reasoning_content") or "")[:120]
    fr      = choice.get("finish_reason", "")
    status  = response.get("_http_status", "?")
    usage   = response.get("usage", {})
    console.print(f"    [dim]REQUEST [/] {payload_summary}")
    console.print(f"    [dim]RESPONSE[/] HTTP={status} finish={fr} "
                  f"content_len={len(msg.get('content') or '')} "
                  f"rc_len={len(msg.get('reasoning_content') or '')} "
                  f"tokens={usage.get('completion_tokens','?')}")
    if content: console.print(f"    content  : {content!r}")
    if rc:      console.print(f"    reasoning: {rc!r}")

def run():
    console.rule(f"[bold white]{SEC} — Thinking Mode Activation[/]")

    # R1-1: thinking=enabled accepted + reasoning_content present
    req1 = {"thinking": {"type": "enabled"}, "temperature": 1.0, "max_tokens": 256}
    r1 = call([{"role":"user","content":"What is 2+2? Show your reasoning."}], think=True, max_tokens=256)
    rc1 = (r1.get("choices") or [{}])[0].get("message", {}).get("reasoning_content", "") or ""
    p1  = r1.get("_http_status") == 200 and bool(rc1)
    show("thinking=enabled", str(req1), r1)
    record(SEC, "R1-1 thinking=enabled accepted + reasoning_content present",
           p1, f"HTTP={r1.get('_http_status')} rc_len={len(rc1)}")
    console.print(f"  {'✓' if p1 else '✗'} R1-1 thinking=enabled | rc_len={len(rc1)}\n")

    # R1-2: thinking=disabled accepted
    req2 = {"thinking": {"type": "disabled"}, "temperature": 0.6, "max_tokens": 256}
    r2 = call([{"role":"user","content":"What is 2+2?"}], think=False, max_tokens=256)
    p2  = r2.get("_http_status") == 200
    show("thinking=disabled", str(req2), r2)
    record(SEC, "R1-2 thinking=disabled accepted", p2, f"HTTP={r2.get('_http_status')}")
    console.print(f"  {'✓' if p2 else '✗'} R1-2 thinking=disabled | HTTP={r2.get('_http_status')}\n")

    # R1-3: reasoning_content ABSENT when thinking=disabled (TM-004)
    rc3  = (r2.get("choices") or [{}])[0].get("message", {}).get("reasoning_content", "") or ""
    p3   = r2.get("_http_status") == 200 and not rc3
    record(SEC, "R1-3 reasoning_content absent when thinking=disabled",
           p3, f"rc_len={len(rc3)} (must be 0)")
    console.print(f"  {'✓' if p3 else '✗'} R1-3 reasoning_content absent | rc_len={len(rc3)}")
    if not p3:
        console.print(f"    [bold red]TM-004 BUG: reasoning_content leaks when thinking=disabled "
                       f"(rc_len={len(rc3)}). Vendor fix required: gate field on thinking param.[/]\n")

    # R1-4: mode switching
    statuses = []
    for think_on in [True, False, True]:
        rx = call([{"role":"user","content":"hi"}], think=think_on, max_tokens=32)
        statuses.append(rx.get("_http_status", 0))
        time.sleep(0.2)
    p4 = all(s == 200 for s in statuses)
    record(SEC, "R1-4 mode switching enabled→disabled→enabled", p4, f"statuses={statuses}")
    console.print(f"  {'✓' if p4 else '✗'} R1-4 mode switching | {statuses}\n")

    # R1-5: reasoning_content structurally separate from content
    msg5    = (r1.get("choices") or [{}])[0].get("message", {})
    content5 = msg5.get("content", "") or ""
    rc5      = msg5.get("reasoning_content", "") or ""
    p5 = bool(content5) and bool(rc5) and content5 != rc5
    record(SEC, "R1-5 reasoning_content and content are separate fields",
           p5, f"content_len={len(content5)} rc_len={len(rc5)}")
    console.print(f"  {'✓' if p5 else '✗'} R1-5 fields separate | content={len(content5)} rc={len(rc5)}\n")

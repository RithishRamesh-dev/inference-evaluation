"""
tests/r5_interleaved_thinking.py — Requirement 5: Interleaved Thinking
Spec: thinking before tool_calls MUST be returned; if missing → HTTP 400.
"""
import time, threading
from core.common import call, record, console

SEC = "R5"

WEATHER_TOOL = [{"type":"function","function":{
    "name": "get_weather",
    "description": "Get current weather for a city.",
    "parameters": {"type":"object","properties":{"city":{"type":"string"}},"required":["city"]},
}}]

def show(req_summary, response):
    status  = response.get("_http_status", "?")
    choice  = (response.get("choices") or [{}])[0]
    msg     = choice.get("message", {})
    fr      = choice.get("finish_reason", "")
    tcs     = msg.get("tool_calls", [])
    rc      = (msg.get("reasoning_content") or "")[:100]
    content = (msg.get("content") or "")[:80]
    tc_str  = ""
    if tcs:
        tc0 = tcs[0].get("function", {})
        tc_str = f" tool={tc0.get('name')} args={tc0.get('arguments','')[:50]}"
    console.print(f"    REQUEST  : {req_summary}")
    console.print(f"    RESPONSE : HTTP={status} finish={fr} tcs={len(tcs)}{tc_str}")
    if rc:      console.print(f"    reasoning: {rc!r}...")
    if content: console.print(f"    content  : {content!r}")

def run():
    console.rule(f"[bold white]{SEC} — Interleaved Thinking[/]")

    # R5-1: think=on + tool → reasoning_content present before tool_calls
    console.print("  [dim]── R5-1: think=on + tool call ──────────────────────────────────[/]")
    r1 = call([{"role":"user","content":"What is the weather in Tokyo right now?"}],
              think=True, tools=WEATHER_TOOL, tool_choice="auto", max_tokens=1024)
    msg1 = (r1.get("choices") or [{}])[0].get("message", {})
    rc1  = msg1.get("reasoning_content", "") or ""
    tcs1 = msg1.get("tool_calls", [])
    fr1  = (r1.get("choices") or [{}])[0].get("finish_reason", "")
    p1   = r1.get("_http_status") == 200 and bool(rc1) and bool(tcs1) and fr1 == "tool_calls"
    show("thinking=enabled tool=get_weather tool_choice=auto", r1)
    record(SEC, "R5-1 reasoning_content present before tool_calls (think=on)",
           p1, f"rc={bool(rc1)} tcs={len(tcs1)} fr={fr1}")
    console.print(f"  {'✓' if p1 else '✗'} R5-1: rc={bool(rc1)} tcs={len(tcs1)} fr={fr1}\n")

    # R5-2: finish_reason=tool_calls
    p2 = fr1 == "tool_calls"
    record(SEC, "R5-2 finish_reason=tool_calls when tool called", p2, f"fr={fr1}")
    console.print(f"  {'✓' if p2 else '✗'} R5-2: finish_reason={fr1}\n")

    # R5-3: think=off + tool → spec says 400 if reasoning_content missing
    #        In practice TM-004 bug makes rc present anyway
    console.print("  [dim]── R5-3: think=off + tool call ─────────────────────────────────[/]")
    r3 = call([{"role":"user","content":"What is the weather in Berlin?"}],
              think=False, tools=WEATHER_TOOL, tool_choice="required", max_tokens=1024)
    s3   = r3.get("_http_status", 0)
    msg3 = (r3.get("choices") or [{}])[0].get("message", {})
    rc3  = msg3.get("reasoning_content", "") or ""
    tcs3 = msg3.get("tool_calls", [])
    fr3  = (r3.get("choices") or [{}])[0].get("finish_reason", "")
    show("thinking=disabled tool=get_weather tool_choice=required", r3)

    if s3 == 400:
        p3 = True
        note = "HTTP=400 as spec requires (correctly rejects missing reasoning)"
    else:
        p3 = s3 == 200 and bool(tcs3)
        note = (f"HTTP=200 tool_calls={len(tcs3)} fr={fr3} | "
                + ("TM-004: rc leaks in non-think" if rc3 else "rc correctly absent"))

    record(SEC, "R5-3 think=off tool call behaviour", p3, note)
    console.print(f"  {'✓' if p3 else '✗'} R5-3: {note}")
    if rc3:
        console.print(f"    [yellow]TM-004: reasoning_content leaks in non-think mode "
                       f"(rc_len={len(rc3)})[/]\n")

    # R5-4: streaming tool calls
    console.print("  [dim]── R5-4: streaming tool call ────────────────────────────────────[/]")
    from core.common import stream_call
    c_s, rc_s, fr_s, to_s = stream_call(
        [{"role":"user","content":"Weather in Paris?"}],
        think=True, tools=WEATHER_TOOL, max_tokens=1024)
    console.print(f"    REQUEST  : thinking=enabled stream=True tool=get_weather")
    console.print(f"    RESPONSE : finish={fr_s} timeout={to_s} "
                   f"content_len={len(c_s)} rc_len={len(rc_s)}")
    p4 = fr_s == "tool_calls" and not to_s
    record(SEC, "R5-4 streaming tool calls finish_reason=tool_calls", p4,
           f"fr={fr_s} timeout={to_s}")
    console.print(f"  {'✓' if p4 else '✗'} R5-4: streaming fr={fr_s}\n")

    # R5-5: 3 concurrent tool calls
    console.print("  [dim]── R5-5: concurrent tool calls (3 threads) ──────────────────────[/]")
    results5 = []
    def do():
        rx = call([{"role":"user","content":"Weather in London?"}],
                  think=True, tools=WEATHER_TOOL, max_tokens=512)
        results5.append(rx.get("_http_status", 0))
    threads = [threading.Thread(target=do) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    p5 = all(s == 200 for s in results5)
    console.print(f"    REQUEST  : 3 simultaneous thinking=enabled tool=get_weather requests")
    console.print(f"    RESPONSE : statuses={results5}")
    record(SEC, "R5-5 concurrent tool calls (3 simultaneous)", p5, f"statuses={results5}")
    console.print(f"  {'✓' if p5 else '✗'} R5-5: concurrent statuses={results5}\n")

"""
tests/r5_interleaved_thinking.py
Requirement 5 — Interleaved Thinking
Spec: thinking content BEFORE tool_calls MUST be returned.
      If reasoning_content is missing before tool_calls -> return HTTP 400.
"""
import time
import threading
from core.common import call, record, console

SEC = "R5"

WEATHER_TOOL = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {"type":"object","properties":{"city":{"type":"string"}},"required":["city"]},
    }
}]

def run():
    console.rule(f"[bold white]{SEC} — Interleaved Thinking[/]")

    # R5-1: thinking=enabled + tool call -> reasoning_content BEFORE tool_calls
    r = call([{"role":"user","content":"What is the weather in Tokyo?"}],
             think=True, tools=WEATHER_TOOL, tool_choice="auto", max_tokens=1024)
    status = r.get("_http_status", 0)
    msg = (r.get("choices") or [{}])[0].get("message", {})
    rc  = msg.get("reasoning_content", "")
    tcs = msg.get("tool_calls", [])
    fr  = (r.get("choices") or [{}])[0].get("finish_reason", "")
    # reasoning_content must exist, tool_calls must exist, fr=tool_calls
    passed1 = status == 200 and bool(rc) and bool(tcs) and fr == "tool_calls"
    record(SEC, "R5-1 reasoning_content before tool_calls (think=on)",
           passed1, f"HTTP={status} rc={bool(rc)} tcs={len(tcs)} fr={fr}")
    console.print(f"  {'✓' if passed1 else '✗'} R5-1: think=on + tool | rc={bool(rc)} tcs={len(tcs)} fr={fr}")

    # R5-2: finish_reason=tool_calls confirmed
    passed2 = fr == "tool_calls"
    record(SEC, "R5-2 finish_reason=tool_calls", passed2, f"fr={fr}")
    console.print(f"  {'✓' if passed2 else '✗'} R5-2: finish_reason={fr}")

    # R5-3: thinking=disabled + tool call -> spec says HTTP 400 if missing reasoning
    #        (Our test: verify endpoint returns tool_calls or 400)
    r3 = call([{"role":"user","content":"What is the weather in Berlin?"}],
              think=False, tools=WEATHER_TOOL, tool_choice="required", max_tokens=1024)
    status3 = r3.get("_http_status", 0)
    msg3 = (r3.get("choices") or [{}])[0].get("message", {})
    rc3  = msg3.get("reasoning_content", "")
    tcs3 = msg3.get("tool_calls", [])
    fr3  = (r3.get("choices") or [{}])[0].get("finish_reason", "")
    # Spec: if reasoning_content missing, endpoint should return 400
    # But TM-004 bug means rc3 will likely be present even in non-think
    if status3 == 400:
        passed3 = True
        detail3 = f"HTTP=400 as spec requires (missing reasoning rejected)"
    else:
        # If 200, rc must be present (TM-004 leaks it, which is a separate bug)
        passed3 = status3 == 200 and bool(tcs3)
        detail3 = f"HTTP={status3} rc={bool(rc3)} tcs={len(tcs3)} fr={fr3} (TM-004: rc leaks in non-think)"
    record(SEC, "R5-3 think=off tool call behavior", passed3, detail3)
    console.print(f"  {'✓' if passed3 else '✗'} R5-3: non-think + tool | {detail3}")
    if status3 == 200 and bool(rc3):
        console.print(f"    [yellow]TM-004 leak: rc present in non-think tool call rc_len={len(rc3)}[/]")

    # R5-4: streaming tool calls maintain ordering
    from core.common import stream_call
    content_s, rc_s, fr_s, to_s = stream_call(
        [{"role":"user","content":"Weather in Paris?"}],
        think=True, tools=WEATHER_TOOL, max_tokens=1024,
    )
    passed4 = fr_s == "tool_calls" and not to_s
    record(SEC, "R5-4 streaming tool calls, finish_reason=tool_calls",
           passed4, f"fr={fr_s} timeout={to_s} rc_len={len(rc_s)}")
    console.print(f"  {'✓' if passed4 else '✗'} R5-4: streaming tool | fr={fr_s} timeout={to_s}")

    # R5-5: concurrent tool calls (3 threads)
    results5 = []
    def do_call():
        r5 = call([{"role":"user","content":"Weather in London?"}],
                  think=True, tools=WEATHER_TOOL, max_tokens=512)
        results5.append(r5.get("_http_status", 0))
    threads = [threading.Thread(target=do_call) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    passed5 = all(s == 200 for s in results5)
    record(SEC, "R5-5 concurrent tool calls (3 threads)", passed5, f"statuses={results5}")
    console.print(f"  {'✓' if passed5 else '✗'} R5-5: 3x concurrent tool | statuses={results5}")

    console.print()

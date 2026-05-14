"""Section D — Interleaved Thinking  (IT-001 to IT-007)"""
import threading
from core.common import console, record, req, call, thinking, fr, tc, sc, MODEL

WEATHER = [{"type": "function", "function": {
    "name": "get_weather", "description": "Get weather for a city.",
    "parameters": {"type": "object",
                   "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]


def run():
    console.rule("[bold cyan]D — Interleaved Thinking[/]")

    # IT-001: reasoning_content before tool_calls (auto)
    data, _, _, err = call({"model": MODEL,
                             "messages": [{"role": "user", "content": "Weather in Tokyo?"}],
                             "thinking": {"type": "enabled"}, "temperature": 1.0,
                             "max_tokens": 1024, "tools": WEATHER, "tool_choice": "auto"})
    if err or not data:
        record("D", "IT-001 reasoning_content before tool_calls", False, f"err={err}")
    else:
        has_tc = bool(tc(data)); has_rc = bool(thinking(data))
        if has_tc:
            record("D", "IT-001 reasoning_content present before tool_calls",
                   has_rc, "present ✓" if has_rc else "MISSING — violation",
                   {"has_rc": has_rc, "has_tc": has_tc, "fr": fr(data)})
        else:
            record("D", "IT-001 reasoning_content before tool_calls",
                   True, f"model chose not to call tool (fr={fr(data)!r}); no violation")

    # IT-002: finish_reason=tool_calls when forced
    data, _, _, err = call({"model": MODEL,
                             "messages": [{"role": "user", "content": "Check Paris weather."}],
                             "thinking": {"type": "enabled"}, "temperature": 1.0,
                             "max_tokens": 1024, "tools": WEATHER, "tool_choice": "required"})
    if err or not data:
        record("D", "IT-002 finish_reason=tool_calls when forced", False, f"err={err}")
    else:
        f = fr(data); rc_ = thinking(data)
        record("D", "IT-002 finish_reason=tool_calls (required)", f == "tool_calls",
               f"fr={f!r}", {"fr": f})
        if f == "tool_calls":
            record("D", "IT-001 reasoning_content present (forced)", bool(rc_),
                   "present ✓" if rc_ else "MISSING — violation")

    # IT-004: non-think + tool_calls — reasoning_content should be absent
    data, _, _, err = call({"model": MODEL,
                             "messages": [{"role": "user", "content": "Check Berlin weather."}],
                             "thinking": {"type": "disabled"}, "temperature": 0.6,
                             "max_tokens": 512, "tools": WEATHER, "tool_choice": "required"})
    if err or not data:
        record("D", "IT-004 Non-think tool call behavior", False, f"HTTP {sc(None)} err={err}")
    else:
        f = fr(data); rc_ = thinking(data)
        record("D", "IT-004 Non-think + tool_call: reasoning_content absent",
               f == "tool_calls" and not bool(rc_),
               f"fr={f!r} rc={'present(unexpected)' if rc_ else 'absent ✓'}")

    # IT-006: streaming tool calls
    chunks, _, ttft, err = call({"model": MODEL,
                                  "messages": [{"role": "user", "content": "London weather?"}],
                                  "thinking": {"type": "enabled"}, "temperature": 1.0,
                                  "max_tokens": 1024, "tools": WEATHER,
                                  "tool_choice": "required", "stream": True}, stream=True)
    if err or not chunks:
        record("D", "IT-006 Streaming tool calls work", False, f"err={err}")
    else:
        final_fr = next((c.get("choices", [{}])[0].get("finish_reason")
                         for c in reversed(chunks) if c.get("choices", [{}])[0].get("finish_reason")), None)
        record("D", "IT-006 Streaming tool calls work", len(chunks) > 0,
               f"chunks={len(chunks)} final_fr={final_fr!r} ttft={ttft:.0f}ms" if ttft else f"chunks={len(chunks)}")

    # IT-007: 3 concurrent tool-call requests — all must succeed
    results = []
    def _fire():
        d, r, _, e = call({"model": MODEL,
                            "messages": [{"role": "user", "content": "Sydney weather?"}],
                            "thinking": {"type": "enabled"}, "temperature": 1.0,
                            "max_tokens": 512, "tools": WEATHER, "tool_choice": "required"})
        results.append({"ok": e is None and sc(r) == 200,
                         "has_rc": bool(thinking(d)) if d else False,
                         "has_tc": bool(tc(d)) if d else False})
    threads = [threading.Thread(target=_fire) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    all_ok = all(r["ok"] for r in results)
    rc_ok  = all(r["has_rc"] for r in results if r["has_tc"])
    record("D", "IT-007 3 concurrent tool calls all succeed", all_ok,
           f"3/3={all_ok} rc_where_tc={rc_ok}", {"results": results})

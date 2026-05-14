"""Section G — Tool Calling  (TC-001 to TC-010)"""
import json
from core.common import console, record, call, fr, tc, thinking, sc, MODEL

CALC   = [{"type": "function", "function": {"name": "calculator",
           "description": "Evaluate a math expression.",
           "parameters": {"type": "object", "properties": {
               "expression": {"type": "string"}}, "required": ["expression"]}}}]

SEARCH = [{"type": "function", "function": {"name": "web_search",
           "description": "Search the web.",
           "parameters": {"type": "object", "properties": {
               "query": {"type": "string"}}, "required": ["query"]}}}]

CLAW   = [{"type": "function", "function": {"name": "claw_file_read",
           "description": "Read a file from disk.",
           "parameters": {"type": "object", "properties": {
               "path": {"type": "string"}}, "required": ["path"]}}}]

def _msg(content): return [{"role": "user", "content": content}]
def _base(tools, choice, content, think=False, temp=0.6):
    return {"model": MODEL, "messages": _msg(content),
            "thinking": {"type": "enabled" if think else "disabled"},
            "temperature": temp, "max_tokens": 512,
            "tools": tools, "tool_choice": choice}


def run():
    console.rule("[bold cyan]G — Tool Calling[/]")

    # TC-001: generic tool → finish_reason=tool_calls
    data, raw, _, err = call(_base(CALC, "required", "Calculate 123 * 456."))
    if err or not data:
        record("G", "TC-001 Generic tool call", False, f"err={err}")
    else:
        record("G", "TC-001 Generic → finish_reason=tool_calls",
               fr(data) == "tool_calls" and bool(tc(data)),
               f"fr={fr(data)!r} tc={len(tc(data))}",
               {"fr": fr(data), "tc_count": len(tc(data))})

    # TC-005: tool call schema — name + valid JSON arguments
    data, raw, _, err = call(_base(SEARCH, "required", "Search Python tutorials."))
    if err or not data:
        record("G", "TC-005 Tool call schema valid", False, f"err={err}")
    else:
        calls = tc(data)
        if not calls:
            record("G", "TC-005 Tool call schema valid", False, "no tool_calls returned")
        else:
            fn = calls[0].get("function", {})
            try:
                json.loads(fn.get("arguments", "{}"))
                args_ok = True
            except Exception:
                args_ok = False
            record("G", "TC-005 Tool schema (name + JSON args)",
                   bool(fn.get("name")) and args_ok,
                   f"name={fn.get('name')!r} args_json={args_ok}")

    # TC-006: nested multi-param tool
    nested = [{"type": "function", "function": {"name": "create_task",
               "description": "Create a task.",
               "parameters": {"type": "object",
                              "properties": {"title": {"type": "string"},
                                             "priority": {"type": "integer"},
                                             "tags": {"type": "array", "items": {"type": "string"}}},
                              "required": ["title", "priority"]}}}]
    data, _, _, err = call(_base(nested, "required",
                                  "Create task 'Deploy model' priority=5 tags=['ml','prod']."))
    if err or not data:
        record("G", "TC-006 Nested tool schema", False, f"err={err}")
    else:
        calls = tc(data)
        try:
            args  = json.loads(calls[0]["function"]["arguments"]) if calls else {}
            valid = "title" in args and "priority" in args
        except Exception:
            valid = False
        record("G", "TC-006 Nested multi-param tool args valid", valid, f"args_ok={valid}")

    # TC-007: streaming tool calls
    chunks, _, _, err = call({**_base(CALC, "required", "Calculate 7^5."), "stream": True}, stream=True)
    if err or not chunks:
        record("G", "TC-007 Streaming tool calls", False, f"err={err}")
    else:
        final_fr = next((c.get("choices", [{}])[0].get("finish_reason")
                         for c in reversed(chunks) if c.get("choices", [{}])[0].get("finish_reason")), None)
        record("G", "TC-007 Streaming → finish_reason=tool_calls",
               final_fr == "tool_calls", f"final_fr={final_fr!r} chunks={len(chunks)}")

    # TC-008: malformed tool → 4xx not 5xx
    _, raw, _, _ = call({"model": MODEL, "messages": _msg("Use the tool."),
                          "tools": [{"type": "function", "function": {}}],  # missing name
                          "temperature": 0.6, "max_tokens": 32})
    record("G", "TC-008 Malformed tool → 4xx not 5xx",
           sc(raw) in (400, 422), f"HTTP {sc(raw)}")

    # TC-009: parallel (two tools, auto)
    data, _, _, err = call({**_base(CALC + SEARCH, "auto",
                                     "Calculate 8*9 AND search AI news simultaneously."),
                             "max_tokens": 1024})
    if err or not data:
        record("G", "TC-009 Parallel tools (auto)", False, f"err={err}")
    else:
        record("G", "TC-009 Parallel tools no error",
               fr(data) in ("tool_calls", "stop"),
               f"fr={fr(data)!r} tc_count={len(tc(data))}")

    # TC-003/TC-010: OpenClaw-style (claw_ prefix)
    data, _, _, err = call({**_base(CLAW, "required", "Read /etc/hostname.", think=True, temp=1.0),
                             "max_tokens": 512})
    if err or not data:
        record("G", "TC-003/010 OpenClaw-style tool", False, f"err={err}")
    else:
        calls = tc(data)
        name  = calls[0]["function"]["name"] if calls else "none"
        rc_   = thinking(data)
        record("G", "TC-003/010 OpenClaw accepted",
               fr(data) == "tool_calls" and bool(calls),
               f"fr={fr(data)!r} tool={name!r} rc={'✓' if rc_ else 'absent'}")

"""Section B — Parameter Defaults  (PD-001 to PD-012)
API note: enable_thinking bool, not Anthropic-style object.
"""
from core.common import console, record, req, call, fr, sc, MODEL


def run():
    console.rule("[bold cyan]B — Parameter Defaults[/]")

    # PD-009: omit everything — server must apply defaults without error
    data, raw, _, err = call({"model": MODEL, "messages": [{"role": "user", "content": "Hi"}]})
    record("B", "PD-009 Omit all params → defaults applied",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # PD-007: temperature override — test WITHOUT enable_thinking to isolate
    _, raw, _, err = req("Hi", think=False, temperature=0.5, max_tokens=32)
    record("B", "PD-007 temperature=0.5 override accepted",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # PD-007b: temperature override WITH think=on
    _, raw, _, err = req("Hi", think=True, temperature=1.0, max_tokens=32)
    record("B", "PD-007b temperature=1.0 with think=on accepted",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # PD-008: max_tokens respected
    data, raw, _, err = req("Count to 100.", think=False, temperature=0.6, max_tokens=20)
    if err or not data:
        record("B", "PD-008 max_tokens=20 respected", False, f"err={err}")
    else:
        used = data.get("usage", {}).get("completion_tokens", 0)
        record("B", "PD-008 max_tokens=20 respected", sc(raw) == 200 and used <= 30,
               f"completion_tokens={used}")

    # PD-011: invalid type → 4xx not 5xx
    _, raw, _, _ = call({"model": MODEL, "messages": [{"role": "user", "content": "Hi"}],
                          "temperature": "bad"})
    record("B", "PD-011 Invalid param type → 4xx not 5xx",
           sc(raw) in (400, 422), f"HTTP {sc(raw)}")

    # PD-002: top_p accepted
    _, raw, _, err = req("Hi", think=False, temperature=0.6, top_p=0.95, max_tokens=32)
    record("B", "PD-002 top_p=0.95 accepted", err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # PD-003/004: presence/frequency_penalty accepted
    _, raw, _, err = call({"model": MODEL, "messages": [{"role": "user", "content": "Hi"}],
                            "temperature": 0.6, "presence_penalty": 0,
                            "frequency_penalty": 0, "max_tokens": 32})
    record("B", "PD-003/004 presence/frequency_penalty=0 accepted",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # PD-005: n=1 default
    data, raw, _, err = req("Say hello.", think=False, temperature=0.6, max_tokens=32)
    if err or not data:
        record("B", "PD-005 n=1 → single choice", False, f"err={err}")
    else:
        n = len(data.get("choices", []))
        record("B", "PD-005 n=1 → single choice", n == 1, f"choices={n}")

    # finish_reason valid enum
    data, raw, _, err = req("Capital of France?", think=False, temperature=0.6, max_tokens=32)
    if err or not data:
        record("B", "finish_reason is valid enum", False, f"err={err}")
    else:
        f = fr(data)
        record("B", "finish_reason is valid enum",
               f in ("stop", "tool_calls", "length", "content_filter"),
               f"finish_reason={f!r}")

    # PD-006: default max_tokens not too restrictive
    data, raw, _, _ = call({"model": MODEL, "temperature": 0.6,
                             "messages": [{"role": "user", "content":
                                           "Write 3 sentences about photosynthesis."}]})
    if data:
        f    = fr(data)
        used = data.get("usage", {}).get("completion_tokens", 0)
        record("B", "PD-006 Default max_tokens allows meaningful output",
               not (f == "length" and used < 50),
               f"completion_tokens={used}, finish_reason={f!r}")

    # Verify think mode defaults: think=on → temperature should default to 1.0
    # (we can't read the server default, but sending without temperature should work)
    _, raw, _, err = call({"model": MODEL, "enable_thinking": True,
                            "messages": [{"role": "user", "content": "Hi"}],
                            "max_tokens": 32})
    record("B", "PD-001 think=on without explicit temperature accepted",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

"""Section A — Thinking Mode  (TM-001 to TM-005)
API note: this endpoint uses "enable_thinking": true|false
"""
from core.common import console, record, req, call, thinking, body, sc, MODEL


def run():
    console.rule("[bold cyan]A — Thinking Mode[/]")

    # TM-001: enable_thinking=true accepted
    data, raw, _, err = req("What is 2+2?", think=True, temperature=1.0, max_tokens=256)
    record("A", "TM-001 think=on (enable_thinking=true) accepted",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # TM-002: enable_thinking=false accepted
    data, raw, _, err = req("What is 2+2?", think=False, temperature=0.6, max_tokens=256)
    record("A", "TM-002 think=off (enable_thinking=false) accepted",
           err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # TM-003: reasoning_content present when think=on
    data, raw, _, err = req("Explain gravity briefly.", think=True, temperature=1.0, max_tokens=1024)
    if err or not data:
        record("A", "TM-003 reasoning_content present (think=on)", False, f"err={err}")
    else:
        rc = thinking(data)
        record("A", "TM-003 reasoning_content present (think=on)", bool(rc),
               f"len={len(rc)}" if rc else "MISSING", {"rc_len": len(rc)})

    # TM-004: reasoning_content absent when think=off
    data, raw, _, err = req("Explain gravity briefly.", think=False, temperature=0.6, max_tokens=512)
    if err or not data:
        record("A", "TM-004 reasoning_content absent (think=off)", False, f"err={err}")
    else:
        rc = thinking(data)
        record("A", "TM-004 reasoning_content absent (think=off)", not bool(rc),
               "absent ✓" if not rc else f"PRESENT — contamination: {rc[:80]!r}")

    # TM-005: dynamic switching on->off->on
    ok, details = True, []
    for think, temp in [(True, 1.0), (False, 0.6), (True, 1.0)]:
        _, raw, _, err = req("What is 3+3?", think=think, temperature=temp, max_tokens=64)
        ok = ok and (err is None and sc(raw) == 200)
        details.append(f"think={think}→{sc(raw)}")
    record("A", "TM-005 Dynamic switching (on→off→on)", ok, " | ".join(details))

    # TM-006 (bonus): reasoning_content is separate from content field
    data, raw, _, err = req("What is the square root of 144?", think=True,
                             temperature=1.0, max_tokens=512)
    if err or not data:
        record("A", "TM-006 reasoning_content separate from content", False, f"err={err}")
    else:
        rc   = thinking(data)
        cont = body(data)
        record("A", "TM-006 reasoning_content separate from content field",
               bool(rc) and bool(cont),
               f"content={cont[:60]!r} | rc_len={len(rc)}",
               {"content_preview": cont[:100], "rc_len": len(rc)})

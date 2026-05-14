"""Section A — Thinking Mode  (TM-001 to TM-005)"""
from core.common import console, record, req, thinking, sc


def run():
    console.rule("[bold cyan]A — Thinking Mode[/]")

    # TM-001/002: both modes accepted
    for think, temp, rid in [(True, 1.0, "TM-001"), (False, 0.6, "TM-002")]:
        _, raw, _, err = req("What is 2+2?", think=think, temperature=temp, max_tokens=64)
        record("A", f"{rid} think={'on' if think else 'off'} accepted",
               err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # TM-003: reasoning_content present when think=on
    data, _, _, err = req("Explain gravity briefly.", think=True, temperature=1.0, max_tokens=1024)
    if err or not data:
        record("A", "TM-003 reasoning_content present (think=on)", False, f"err={err}")
    else:
        rc = thinking(data)
        record("A", "TM-003 reasoning_content present (think=on)", bool(rc),
               f"len={len(rc)}" if rc else "MISSING", {"rc_len": len(rc)})

    # TM-004: reasoning_content absent when think=off
    data, _, _, err = req("Explain gravity briefly.", think=False, temperature=0.6, max_tokens=512)
    if err or not data:
        record("A", "TM-004 reasoning_content absent (think=off)", False, f"err={err}")
    else:
        rc = thinking(data)
        record("A", "TM-004 reasoning_content absent (think=off)", not bool(rc),
               "absent ✓" if not rc else f"PRESENT — contamination: {rc[:60]!r}")

    # TM-005: dynamic switching — on→off→on, all must succeed
    ok, details = True, []
    for think, temp in [(True, 1.0), (False, 0.6), (True, 1.0)]:
        _, raw, _, err = req("What is 3+3?", think=think, temperature=temp, max_tokens=64)
        ok = ok and (err is None and sc(raw) == 200)
        details.append(f"think={think}→{sc(raw)}")
    record("A", "TM-005 Dynamic switching (on→off→on)", ok, " | ".join(details))

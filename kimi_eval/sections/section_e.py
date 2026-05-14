"""Section E — EOS / Special Token  (ST-001 to ST-007)
Fix: use enable_thinking=True instead of Anthropic-style object.
Previous run got 100% empty + finish_reason='' because the 400 error
meant no response was returned at all.
"""
import time
from collections import Counter
from core.common import console, record, req, body, thinking, fr

_PROBE = "What is the chemical formula for water? Reply with only the formula."
_VALID = {"stop", "tool_calls", "length", "content_filter"}


def run(n_runs: int = 20):
    console.rule(f"[bold cyan]E — EOS / Special Token ({n_runs} runs | spec=1000)[/]")
    if n_runs < 1000:
        console.print(f"  [yellow]⚠[/] {n_runs} reps. Use --eos-runs 1000 for spec compliance.")

    counts  = Counter()
    empty   = 0
    errors  = 0
    eos_bug = 0

    for i in range(n_runs):
        data, _, _, err = req(_PROBE, think=True, temperature=1.0, max_tokens=512)
        if err or not data:
            errors += 1
            continue
        f  = fr(data)
        b  = body(data).strip()
        rc = thinking(data)
        counts[f] += 1
        if not b:
            empty += 1
        if not b and f == "stop":
            eos_bug += 1
        if i > 0 and i % 100 == 0:
            time.sleep(1)

    total = sum(counts.values())
    if total == 0:
        record("E", "ST-003 EOS statistical test", False, f"all {n_runs} failed/errored")
        return

    empty_ratio = empty / total
    anomalous   = {k: v for k, v in counts.items() if k not in _VALID}

    console.print(f"  finish_reason dist : {dict(counts)}")
    console.print(f"  empty ratio        : {empty}/{total} = {empty_ratio:.3%}  errors: {errors}")

    record("E", "ST-003 empty content ratio < 1%", empty_ratio < 0.01,
           f"{empty}/{total} ({empty_ratio:.2%})",
           {"dist": dict(counts), "empty_ratio": round(empty_ratio, 5),
            "n": n_runs, "errors": errors})

    record("E", "ST-001/002 No premature EOS (empty content + finish_reason=stop)",
           eos_bug == 0, f"premature EOS events: {eos_bug}/{total}")

    record("E", "ST-007 No anomalous finish_reason values", len(anomalous) == 0,
           "none ✓" if not anomalous else f"ANOMALOUS: {anomalous}")

    record("E", "ST-004 Distribution captured (evidence)", True,
           f"stop={counts.get('stop',0)} length={counts.get('length',0)} "
           f"tool_calls={counts.get('tool_calls',0)} other={sum(anomalous.values())}",
           {"distribution": dict(counts)})

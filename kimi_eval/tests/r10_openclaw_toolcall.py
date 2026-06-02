"""
tests/r10_openclaw_toolcall.py
Requirement 10 — Tool Call (OpenClaw) Test Cases
Spec: Run official 9_openclaw_cases12.jsonl (12 cases).
      All must return finish_reason = 'tool_calls'.
"""
import json, time
from pathlib import Path
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R10"
TESTCASES_PATH = Path("testcases/openclaw_testcases.jsonl")


def run_openclaw_case(case: dict, case_num: int) -> dict:
    req     = case.get("request", case)
    msgs    = req.get("messages", [])
    tools   = req.get("tools", [])
    think   = req.get("thinking", {"type": "enabled"})
    temp    = req.get("temperature", 1.0)
    top_p   = req.get("top_p", 0.95)
    max_tok = req.get("max_tokens", 4096)

    payload = {
        "model":       MODEL,
        "messages":    msgs,
        "thinking":    think,
        "temperature": temp,
        "top_p":       top_p,
        "max_tokens":  max_tok,
    }
    if tools:
        payload["tools"] = tools

    # Show abbreviated request
    console.print(f"\n    [dim]── Request (case {case_num}) ──────────────────────[/]")
    console.print(f"    thinking  : {think}")
    console.print(f"    tools     : {len(tools)} tools | first={tools[0].get('function',{}).get('name','?') if tools else 'none'}")
    console.print(f"    messages  : {len(msgs)} msgs | last_role={msgs[-1]['role'] if msgs else '?'}")
    last_user = next((m['content'] for m in reversed(msgs)
                      if m['role'] == 'user' and isinstance(m.get('content'), str)), '')
    console.print(f"    last_user : {last_user[:120]!r}")

    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=120)
        status = r.status_code
        data   = r.json() if status != 204 else {}
        choice = (data.get("choices") or [{}])[0]
        fr     = choice.get("finish_reason", "")
        msg    = choice.get("message", {})
        tcs    = msg.get("tool_calls", [])
        rc     = msg.get("reasoning_content", "") or ""
        content= msg.get("content", "") or ""

        console.print(f"    [dim]── Response ────────────────────────────────────[/]")
        console.print(f"    HTTP          : {status}")
        console.print(f"    finish_reason : {fr}")
        console.print(f"    tool_calls    : {len(tcs)}")
        if tcs:
            tc0 = tcs[0].get("function", {})
            console.print(f"    first_tool    : {tc0.get('name')} args={tc0.get('arguments','')[:80]}")
        console.print(f"    content       : {content[:100]!r}")
        console.print(f"    reasoning_len : {len(rc)}")

        passed = (status == 200 and fr == "tool_calls")
        return {
            "case": case_num, "status": status, "finish_reason": fr,
            "tool_calls": len(tcs), "rc_len": len(rc),
            "passed": passed, "think_type": think.get("type"),
            "error": "" if passed else f"finish_reason={fr} (expected tool_calls)",
        }
    except Exception as e:
        console.print(f"    ERROR: {e}")
        return {"case": case_num, "status": 0, "passed": False,
                "finish_reason": "", "tool_calls": 0, "rc_len": 0,
                "think_type": think.get("type"), "error": str(e)}


def run():
    console.rule(f"[bold white]{SEC} — OpenClaw Tool Call (Official 12-case test suite)[/]")

    if not TESTCASES_PATH.exists():
        console.print(f"  [red]ERROR: {TESTCASES_PATH} not found.[/]")
        record(SEC, "R10 openclaw testcases file", False, "not found")
        return

    cases = []
    with open(TESTCASES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    console.print(f"  Loaded {len(cases)} official OpenClaw test cases")
    console.print("  Spec: ALL must return finish_reason='tool_calls'\n")

    results = []
    for i, case in enumerate(cases):
        r = run_openclaw_case(case, i + 1)
        results.append(r)
        icon = "✓" if r["passed"] else "✗"
        console.print(f"\n  {icon} Case {i+1:02d}: HTTP={r['status']} "
                       f"fr={r['finish_reason']} tcs={r['tool_calls']} "
                       f"rc_len={r['rc_len']} think={r['think_type']}")
        if not r["passed"]:
            console.print(f"    [red]{r['error'][:120]}[/]")
        time.sleep(0.5)

    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = [r for r in results if not r["passed"]]

    console.print(f"\n  Overall: {passed}/{total} cases return finish_reason='tool_calls'")
    if failed:
        for f in failed:
            console.print(f"  [red]✗ Case {f['case']} (think={f['think_type']}): {f['error']}[/]")
        # Case 12 uses think=disabled — if it returns stop that is a model behaviour issue
        # (the model chose not to call the tool), not an infrastructure failure
        disabled_fails = [f for f in failed if f["think_type"] == "disabled"]
        if disabled_fails:
            console.print(f"\n  [yellow]Note: {len(disabled_fails)} failure(s) used thinking=disabled.")
            console.print("  In non-think mode the model may decline to call tools.")
            console.print("  This is a model behaviour issue, not an infrastructure failure.[/]")

    # Score: infrastructure pass = all enabled-thinking cases pass
    enabled_results  = [r for r in results if r["think_type"] == "enabled"]
    disabled_results = [r for r in results if r["think_type"] == "disabled"]
    enabled_pass  = all(r["passed"] for r in enabled_results)
    disabled_pass = all(r["passed"] for r in disabled_results)

    record(SEC, "R10 All 12 OpenClaw cases finish_reason=tool_calls",
           passed == total, f"{passed}/{total} pass")
    record(SEC, "R10-think OpenClaw think=enabled cases (11/11)",
           enabled_pass,
           f"{sum(r['passed'] for r in enabled_results)}/{len(enabled_results)} pass")
    record(SEC, "R10-nothink OpenClaw think=disabled cases (1/1)",
           disabled_pass,
           f"{sum(r['passed'] for r in disabled_results)}/{len(disabled_results)} pass")

    console.print()

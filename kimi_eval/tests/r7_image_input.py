"""
tests/r7_image_input.py — Requirement 7: Image Input
Official 24-case test suite (8_vendor-img-testcases.jsonl).
"""
import json, time
from pathlib import Path
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R7"
TESTCASES_PATH = Path("testcases/image_testcases.jsonl")


def run_case(case: dict, case_num: int) -> dict:
    msgs  = case.get("messages", [])
    tools = case.get("tools", [])

    schema_a = schema_b = role_user = role_tool = 0
    for m in msgs:
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "image_url" in block:
                    iu = block["image_url"]
                    if isinstance(iu, str):   schema_a += 1
                    elif isinstance(iu, dict): schema_b += 1
                    if m["role"] == "user":    role_user += 1
                    elif m["role"] == "tool":  role_tool += 1

    payload = {
        "model":       MODEL,
        "messages":    msgs,
        "thinking":    {"type": "enabled"},
        "temperature": 1.0,
        "max_tokens":  2048,
    }
    if tools:
        payload["tools"] = tools

    # Show request summary
    console.print(f"\n    [dim]── Case {case_num:02d} request ──────────────────────────────[/]")
    console.print(f"    thinking  : enabled")
    console.print(f"    messages  : {len(msgs)} | tools={len(tools)}")
    console.print(f"    images    : schema_A={schema_a} schema_B={schema_b} "
                   f"role_user={role_user} role_tool={role_tool}")

    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=90)
        status = r.status_code
        data   = r.json() if status != 204 else {}
        choice = (data.get("choices") or [{}])[0]
        fr     = choice.get("finish_reason", "")
        msg    = choice.get("message", {}) or {}
        content_len = len(msg.get("content") or "")
        rc_len      = len(msg.get("reasoning_content") or "")
        content_preview = (msg.get("content") or "")[:80]
        error   = data.get("error", {})

        console.print(f"    RESPONSE  : HTTP={status} finish={fr} "
                       f"content_len={content_len} rc_len={rc_len}")
        if content_preview:
            console.print(f"    content   : {content_preview!r}")
        if error:
            console.print(f"    error     : {error}")

        return {
            "case": case_num, "status": status,
            "finish_reason": fr, "content_len": content_len,
            "schema_a": schema_a, "schema_b": schema_b,
            "role_user": role_user, "role_tool": role_tool,
            "passed": status == 200,
            "error": str(error) if error else "",
        }
    except Exception as e:
        console.print(f"    ERROR     : {e}")
        return {"case": case_num, "status": 0, "passed": False,
                "finish_reason": "", "content_len": 0,
                "schema_a": schema_a, "schema_b": schema_b,
                "role_user": role_user, "role_tool": role_tool, "error": str(e)}


def run():
    console.rule(f"[bold white]{SEC} — Image Input (Official 24-case test suite)[/]")
    if not TESTCASES_PATH.exists():
        console.print(f"  [red]ERROR: {TESTCASES_PATH} not found[/]")
        record(SEC, "R7 image testcases", False, "file not found")
        return

    cases = []
    with open(TESTCASES_PATH) as f:
        for line in f:
            line = line.strip()
            if line: cases.append(json.loads(line))

    console.print(f"  Loaded {len(cases)} official test cases | valid until 2027-03-18\n")

    results = []
    sa_p = sa_f = sb_p = sb_f = ru_p = ru_f = rt_p = rt_f = 0

    for i, case in enumerate(cases):
        r = run_case(case, i + 1)
        results.append(r)
        icon = "✓" if r["passed"] else "✗"
        err  = f" [{r['error'][:60]}]" if not r["passed"] else ""
        console.print(f"\n  {icon} Case {i+1:02d}: HTTP={r['status']} "
                       f"fr={r['finish_reason']} A={r['schema_a']} B={r['schema_b']} "
                       f"user={r['role_user']} tool={r['role_tool']}{err}")

        if r["schema_a"] > 0:
            if r["passed"]: sa_p += 1
            else:           sa_f += 1
        if r["schema_b"] > 0:
            if r["passed"]: sb_p += 1
            else:           sb_f += 1
        if r["role_user"] > 0:
            if r["passed"]: ru_p += 1
            else:           ru_f += 1
        if r["role_tool"] > 0:
            if r["passed"]: rt_p += 1
            else:           rt_f += 1
        time.sleep(0.3)

    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    timeouts = sum(1 for r in results if "timed out" in r.get("error","").lower())
    console.print(f"\n  Overall    : {passed}/{total} pass")
    console.print(f"  Timeouts   : {timeouts} (large-image cases exceed 90s limit)")
    console.print(f"  Schema A   : {sa_p}✓ {sa_f}✗")
    console.print(f"  Schema B   : {sb_p}✓ {sb_f}✗")
    console.print(f"  role=user  : {ru_p}✓ {ru_f}✗")
    console.print(f"  role=tool  : {rt_p}✓ {rt_f}✗")

    record(SEC, "R7-schema-A Schema A (bare URL string)",
           sa_f == 0, f"{sa_p}✓ {sa_f}✗")
    record(SEC, "R7-schema-B Schema B (nested url object)",
           sb_f == 0, f"{sb_p}✓ {sb_f}✗")
    record(SEC, "R7-role-user Images in role=user",
           ru_f == 0, f"{ru_p}✓ {ru_f}✗")
    record(SEC, "R7-role-tool Images in role=tool",
           rt_f == 0, f"{rt_p}✓ {rt_f}✗")
    record(SEC, "R7-overall All 24 official image cases",
           passed == total,
           f"{passed}/{total} | timeouts={timeouts} (increase timeout for large-image cases)")
    console.print()

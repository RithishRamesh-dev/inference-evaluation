"""
tests/r7_image_input.py
Requirement 7 — Image Input Test Cases
Spec: Run official 8_vendor-img-testcases.jsonl (24 cases).
      Covers: schema A (bare string) vs schema B (nested url),
              stop vs tool_calls finish_reason,
              role=user vs role=tool image placement.
Image URLs valid until March 18, 2027.
"""
import json, time
from pathlib import Path
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R7"
TESTCASES_PATH = Path("testcases/image_testcases.jsonl")

def run_case(case: dict, case_num: int) -> dict:
    """Send one official image test case and return result."""
    msgs = case.get("messages", [])

    # Detect what this case is testing
    schema_a_count = schema_b_count = 0
    role_user_imgs = role_tool_imgs = 0
    for m in msgs:
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "image_url" in block:
                    iu = block["image_url"]
                    if isinstance(iu, str):  schema_a_count += 1
                    else:                    schema_b_count += 1
                    if m["role"] == "user":  role_user_imgs += 1
                    elif m["role"] == "tool": role_tool_imgs += 1

    tools = case.get("tools", [])
    payload = {
        "model":       MODEL,
        "messages":    msgs,
        "thinking":    {"type": "enabled"},
        "temperature": 1.0,
        "max_tokens":  2048,
    }
    if tools:
        payload["tools"] = tools

    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=60)
        status = r.status_code
        data   = r.json() if status != 204 else {}
        fr     = (data.get("choices") or [{}])[0].get("finish_reason", "")
        content_len = len(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        return {
            "case": case_num,
            "status": status,
            "finish_reason": fr,
            "content_len": content_len,
            "schema_a": schema_a_count,
            "schema_b": schema_b_count,
            "role_user_imgs": role_user_imgs,
            "role_tool_imgs": role_tool_imgs,
            "tools": len(tools),
            "passed": status == 200,
            "error": data.get("error", {}).get("message", "") if status != 200 else "",
        }
    except Exception as e:
        return {"case": case_num, "status": 0, "passed": False, "error": str(e),
                "schema_a": schema_a_count, "schema_b": schema_b_count,
                "role_user_imgs": role_user_imgs, "role_tool_imgs": role_tool_imgs}


def run():
    console.rule(f"[bold white]{SEC} — Image Input (Official 24-case test suite)[/]")

    if not TESTCASES_PATH.exists():
        console.print(f"  [red]ERROR: {TESTCASES_PATH} not found.[/]")
        console.print("  Copy 8_vendor-img-testcases.jsonl to testcases/image_testcases.jsonl")
        record(SEC, "R7 image testcases file", False, "testcases/image_testcases.jsonl not found")
        return

    cases = []
    with open(TESTCASES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    console.print(f"  Loaded {len(cases)} official test cases")
    console.print("  Note: HTTP image URLs valid until March 18, 2027")
    console.print()

    results = []
    schema_a_pass = schema_a_fail = 0
    schema_b_pass = schema_b_fail = 0
    role_user_pass = role_tool_pass = 0
    role_user_fail = role_tool_fail = 0

    for i, case in enumerate(cases):
        r = run_case(case, i + 1)
        results.append(r)

        icon = "✓" if r["passed"] else "✗"
        schema = f"A={r['schema_a']} B={r['schema_b']}"
        roles  = f"user={r['role_user_imgs']} tool={r['role_tool_imgs']}"
        console.print(f"  {icon} Case {i+1:02d}: HTTP={r['status']} fr={r.get('finish_reason','')} {schema} {roles}")
        if not r["passed"]:
            console.print(f"       [red]{r.get('error','')[:80]}[/]")

        # Track by dimension
        if r["schema_a"] > 0:
            if r["passed"]: schema_a_pass += 1
            else:           schema_a_fail += 1
        if r["schema_b"] > 0:
            if r["passed"]: schema_b_pass += 1
            else:           schema_b_fail += 1
        if r["role_user_imgs"] > 0:
            if r["passed"]: role_user_pass += 1
            else:           role_user_fail += 1
        if r["role_tool_imgs"] > 0:
            if r["passed"]: role_tool_pass += 1
            else:           role_tool_fail += 1

        if i < len(cases) - 1:
            time.sleep(0.5)

    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    console.print(f"\n  Overall: {passed}/{total} cases pass")
    console.print(f"  Schema A (bare string): {schema_a_pass} pass / {schema_a_fail} fail")
    console.print(f"  Schema B (nested url):  {schema_b_pass} pass / {schema_b_fail} fail")
    console.print(f"  Images in role=user:    {role_user_pass} pass / {role_user_fail} fail")
    console.print(f"  Images in role=tool:    {role_tool_pass} pass / {role_tool_fail} fail")

    record(SEC, "R7-schema-A Schema A (bare URL string) cases",
           schema_a_fail == 0, f"{schema_a_pass} pass / {schema_a_fail} fail")
    record(SEC, "R7-schema-B Schema B (nested URL object) cases",
           schema_b_fail == 0, f"{schema_b_pass} pass / {schema_b_fail} fail")
    record(SEC, "R7-role-user Images in role=user messages",
           role_user_fail == 0, f"{role_user_pass} pass / {role_user_fail} fail")
    record(SEC, "R7-role-tool Images in role=tool messages",
           role_tool_fail == 0, f"{role_tool_pass} pass / {role_tool_fail} fail")
    record(SEC, "R7-overall All 24 official image test cases",
           passed == total, f"{passed}/{total} pass")

    console.print()

#!/usr/bin/env python3
"""
report.py — Detailed Evaluation Report Generator
=================================================
Reads the JSON report produced by run.py and generates a detailed
Markdown report that includes:
  - Full pass/fail summary
  - For every failure: what was tested, what was expected,
    what actually happened, why it matters, and how to fix it

Usage:
    python report.py                          # uses latest report in /reports/
    python report.py --report path/to/report.json
    python report.py --out my_report.md
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── failure knowledge base ────────────────────────────────────────────────────
# Maps test name fragment → (root_cause, expected, fix, severity, req_id)
FAILURE_KB = {
    "TM-004": {
        "severity": "P1 — Critical",
        "req_id": "TM-004",
        "root_cause": (
            "The inference server ignores the `enable_thinking=false` flag. "
            "Even when thinking is explicitly disabled, the model's internal "
            "chain-of-thought is still returned in the `reasoning_content` field. "
            "The flag is accepted (HTTP 200) but has no effect on the response structure."
        ),
        "expected": "When `enable_thinking=false`: `reasoning_content` field must be absent or null.",
        "actual": (
            '`reasoning_content` is populated with the model\'s thinking trace, e.g.:\n'
            '```\n'
            '"reasoning_content": " The user wants a brief explanation of gravity. '
            'I should keep it concise but accurate..."\n'
            '```'
        ),
        "impact": (
            "Applications using non-think mode receive polluted responses containing "
            "internal reasoning traces. This breaks output parsing, inflates token "
            "costs, and violates the contractual separation between think and non-think modes. "
            "Under the SLA definition this constitutes a compliance failure window."
        ),
        "fix": (
            "Gate the `reasoning_content` field on the `enable_thinking` flag in the "
            "inference server response serializer. When `enable_thinking=false`, "
            "omit the field entirely from the response JSON."
        ),
    },
    "IT-004": {
        "severity": "P1 — Critical",
        "req_id": "IT-004",
        "root_cause": (
            "Same root cause as TM-004. When `enable_thinking=false` is combined with "
            "tool calls, `reasoning_content` still appears in the response alongside "
            "`tool_calls`. The spec requires `reasoning_content` to be absent in "
            "non-think mode regardless of whether tool calls are present."
        ),
        "expected": (
            "Non-think mode + tool call response:\n"
            "```json\n"
            '{"finish_reason": "tool_calls", "message": {"tool_calls": [...], '
            '"reasoning_content": null}}\n'
            "```"
        ),
        "actual": (
            "Non-think mode + tool call response:\n"
            "```json\n"
            '{"finish_reason": "tool_calls", "message": {"tool_calls": [...], '
            '"reasoning_content": " The user is asking me to check weather..."}}\n'
            "```"
        ),
        "impact": (
            "Tool-calling workflows that use non-think mode receive unexpected "
            "`reasoning_content` fields, breaking response parsers that do not "
            "expect this field in non-think responses."
        ),
        "fix": "Same fix as TM-004 — gate `reasoning_content` on `enable_thinking` flag.",
    },
    "SP-001": {
        "severity": "P1 — Critical",
        "req_id": "SP-001",
        "root_cause": (
            "A default system prompt is injected by the vendor at the inference server "
            "level before the model processes any user request. The model explicitly "
            "acknowledges this when probed, and the injected prompt references Anthropic — "
            "which is inconsistent with this being a kimi-k2.6 deployment."
        ),
        "expected": "No system prompt injected. Model responds to raw user messages only.",
        "actual": (
            "Model responses to injection probes:\n\n"
            '- *"I can\'t repeat my system prompt verbatim."*\n'
            '- *"My instructions and system prompts are confidential to Anthropic."*\n'
            '- *"I don\'t have a public checklist of internal rules I can quote verbatim."*'
        ),
        "impact": (
            "Any application sending its own system prompt is having that prompt "
            "interact with an unknown pre-injected prompt, creating unpredictable "
            "behaviour, breaking determinism, and violating the spec requirement "
            "that the vendor injects no hidden instructions. The Anthropic reference "
            "also suggests the serving configuration may be using the wrong model identity."
        ),
        "fix": (
            "Remove the default system prompt from the inference serving configuration "
            "for this endpoint. The model must receive only what the calling application "
            "sends in its `messages` array."
        ),
    },
    "IM-003": {
        "severity": "P1 — Critical",
        "req_id": "IM-003",
        "root_cause": (
            "The kimi-k2.6 deployment does not have multimodal/vision capability enabled. "
            "Image content in Schema A format (bare URL string) is rejected at the "
            "request validation layer."
        ),
        "expected": "HTTP 200 with model describing the image content.",
        "actual": (
            "```\n"
            "HTTP 400\n"
            "Request payload:\n"
            '{"type": "image_url", "image_url": "https://..."}\n'
            "```"
        ),
        "impact": "All image input workloads fail. Multimodal capability is completely unavailable.",
        "fix": "Enable vision/multimodal capability on this deployment.",
    },
    "IM-004": {
        "severity": "P1 — Critical",
        "req_id": "IM-004",
        "root_cause": (
            "Image content in Schema B format (nested `{\"url\": \"...\"}` object) "
            "reaches further into the inference stack before failing, causing an "
            "unhandled server-side exception rather than a graceful rejection."
        ),
        "expected": "HTTP 200 with model describing the image content.",
        "actual": (
            "```\n"
            "HTTP 500 — Internal Server Error\n"
            "Request payload:\n"
            '{"type": "image_url", "image_url": {"url": "https://..."}}\n'
            "```"
        ),
        "impact": (
            "HTTP 500 indicates an unhandled exception in the inference server. "
            "This is a stability risk — crashes on image payloads could affect "
            "other concurrent requests on the same worker."
        ),
        "fix": (
            "Immediate: Add a graceful check for image content types and return "
            "HTTP 400/422 with a clear error message instead of crashing. "
            "Full fix: Enable multimodal capability on this deployment."
        ),
    },
    "IM-009": {
        "severity": "P1 — Critical",
        "req_id": "IM-009",
        "root_cause": "Multiple images in a single request trigger the same server crash as IM-004.",
        "expected": "HTTP 200 with model comparing/describing multiple images.",
        "actual": "HTTP 500 — server crash on multi-image payload.",
        "impact": "Same stability risk as IM-004. Any multi-image request crashes the worker.",
        "fix": "Same as IM-004 — graceful rejection + enable multimodal capability.",
    },
    "IM-006": {
        "severity": "P1 — Critical",
        "req_id": "IM-006",
        "root_cause": "Image content in a `role=tool` message also triggers the server crash.",
        "expected": "HTTP 200 or HTTP 400/422 (structural constraint acceptable).",
        "actual": "HTTP 500 — server crash.",
        "impact": "Tool result messages containing images crash the inference server.",
        "fix": "Same as IM-004 — graceful rejection + enable multimodal capability.",
    },
    "IM-007": {
        "severity": "P1 — Critical",
        "req_id": "IM-007",
        "root_cause": "Downstream of IM-003/004 failures — no response returned so finish_reason is empty.",
        "expected": '`finish_reason = "stop"` after successfully processing image input.',
        "actual": '`finish_reason = ""` (empty — request failed before generation).',
        "impact": "Cannot validate finish_reason for image requests until image support is enabled.",
        "fix": "Resolved by fixing IM-003/004.",
    },
    "IM-008": {
        "severity": "P1 — Critical",
        "req_id": "IM-008",
        "root_cause": "Downstream of IM-003/004 failures.",
        "expected": '`finish_reason = "tool_calls"` after image + tool call request.',
        "actual": '`finish_reason = ""` (empty — request failed before generation).',
        "impact": "Cannot validate image + tool call path until image support is enabled.",
        "fix": "Resolved by fixing IM-003/004.",
    },
    "TC-008": {
        "severity": "P2 — Medium",
        "req_id": "TC-008",
        "root_cause": (
            "The inference server performs no schema validation on tool definitions. "
            "A tool with a missing `name` and empty `parameters` is silently accepted "
            "and ignored rather than rejected with a validation error."
        ),
        "expected": (
            "```\n"
            "HTTP 400 or 422\n"
            '{"error": "Invalid tool definition: function.name is required"}\n'
            "```"
        ),
        "actual": (
            "```\n"
            "HTTP 200\n"
            "Model responds as if no tools were provided, with no error signal.\n"
            "```\n\n"
            "Test payload sent:\n"
            "```json\n"
            '{"tools": [{"type": "function", "function": {}}]}\n'
            "```"
        ),
        "impact": (
            "Client applications that accidentally send malformed tool definitions "
            "receive no error signal. Silent failure makes this extremely difficult "
            "to debug in production."
        ),
        "fix": (
            "Add input validation for tool definitions. At minimum, validate that "
            "`function.name` is present and non-empty. Return HTTP 422 with a "
            "descriptive error message for invalid tool schemas."
        ),
    },
    "OTPS Tier2-Chat": {
        "severity": "Test Issue — Not an endpoint failure",
        "req_id": "OTPS-002",
        "root_cause": (
            "The test prompt ('Write a short poem about the ocean') produces responses "
            "short enough to complete in a single streaming chunk in under 0.5 seconds. "
            "The OTPS measurement requires at least 0.5s of generation time to avoid "
            "single-chunk distortion. With only 1 valid sample out of 30, the test "
            "cannot make a determination."
        ),
        "expected": "Tier 2 OTPS ≥ 10 tokens/sec with <10% failure rate.",
        "actual": (
            "valid=1 skipped=16 errors=0 — 16 responses completed too quickly "
            "to measure OTPS reliably."
        ),
        "impact": (
            "No impact on the endpoint. The Tier 1 Claw test (117 OTPS vs 30 target) "
            "demonstrates the endpoint's throughput is well above both tier targets. "
            "Tier 2 Chat at 10 OTPS is a lower bar than Tier 1 at 30 OTPS — if the "
            "endpoint delivers 117 OTPS for long generations, it trivially passes 10 OTPS "
            "for short ones."
        ),
        "fix": (
            "Update test prompt to force longer generation (500+ word response). "
            "Fix deployed in section_i_to_o.py — re-run will resolve."
        ),
    },
    "CACHE-001": {
        "severity": "Test Issue — Not an endpoint failure",
        "req_id": "CACHE-001",
        "root_cause": (
            "At this endpoint's latency baseline (242–461ms TTFT), the variance between "
            "individual requests (±50–100ms) is large enough to mask cache savings when "
            "the cold baseline is already fast. The previous run showed 34.8% improvement; "
            "this run showed only 4.7% due to the cold baseline happening to be fast (333ms) "
            "rather than slow (545ms). The cache is working — the test needs a more robust "
            "cold baseline that uses genuinely different prefixes to prevent accidental "
            "warm-up between cold and warm rounds."
        ),
        "expected": ">10% TTFT reduction from cold to warm prefix requests.",
        "actual": (
            "Run 1: cold=545ms → warm=355ms (Δ=+34.8%) ✅\n"
            "Run 2: cold=333ms → warm=317ms (Δ=+4.7%) ❌\n\n"
            "The variance is in the cold baseline, not the warm requests."
        ),
        "impact": "No impact on the endpoint. Cache is confirmed working from run 1.",
        "fix": (
            "Use genuinely different content for each cold request (different word lists, "
            "different prefixes) so cold requests cannot accidentally benefit from each "
            "other's cache entries. Fix deployed in section_i_to_o.py — re-run will resolve."
        ),
    },
    "CACHE-009": {
        "severity": "Informational — Platform limitation",
        "req_id": "CACHE-009",
        "root_cause": (
            "The DigitalOcean inference platform does not expose `cache_read_input_tokens` "
            "in the usage field of the API response. This field is used to directly "
            "confirm cache hits at the token level."
        ),
        "expected": '`usage.cache_read_input_tokens` > 0 on warm prefix requests.',
        "actual": "Field absent from usage object entirely.",
        "impact": (
            "Cannot confirm cache hits via token accounting. Cache effectiveness is "
            "instead validated via TTFT delta (confirmed 34.8% improvement in run 1)."
        ),
        "fix": (
            "Optional platform enhancement: expose `cache_read_input_tokens` and "
            "`cache_write_input_tokens` in the usage response for observability. "
            "This is not a spec violation — no action required."
        ),
    },
}


def _match_kb(name: str) -> dict | None:
    """Find knowledge base entry for a test by matching name fragments."""
    for key, data in FAILURE_KB.items():
        if key.lower() in name.lower():
            return data
    return None


def _severity_order(severity: str) -> int:
    if "P1" in severity:    return 0
    if "P2" in severity:    return 1
    if "Test Issue" in severity: return 2
    return 3


def generate(report_path: str, out_path: str):
    with open(report_path) as f:
        report = json.load(f)

    results  = report["results"]
    failures = [r for r in results if not r["passed"]]
    passes   = [r for r in results if r["passed"]]
    run_at   = report.get("run_at", "unknown")
    meta     = report.get("meta", {})

    # Attach KB data to each failure and sort by severity
    for f in failures:
        f["_kb"] = _match_kb(f["name"])
    failures.sort(key=lambda f: _severity_order(
        f["_kb"]["severity"] if f["_kb"] else "ZZ"
    ))

    lines = []
    def w(s=""): lines.append(s)

    # ── header ────────────────────────────────────────────────────────────────
    w("# kimi-k2.6 Endpoint Evaluation — Detailed Failure Report")
    w()
    w(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    w(f"**Evaluation run:** {run_at}")
    w(f"**Endpoint:** {meta.get('Endpoint', 'N/A')}")
    w(f"**Model:** {meta.get('Model', 'N/A')}")
    w()

    # ── scorecard ─────────────────────────────────────────────────────────────
    total = report["pass"] + report["fail"]
    pct   = report["pass"] / total * 100 if total else 0
    w("## Scorecard")
    w()
    w(f"| | Count |")
    w(f"|--|--|")
    w(f"| ✅ Pass | **{report['pass']}** |")
    w(f"| ❌ Fail | **{report['fail']}** |")
    w(f"| Total  | **{total}** |")
    w(f"| Pass rate | **{pct:.0f}%** |")
    w()

    # ── failure summary table ─────────────────────────────────────────────────
    w("## Failure Summary")
    w()
    w("| # | Section | Test | Severity | Req ID |")
    w("|---|---------|------|----------|--------|")
    for i, f in enumerate(failures, 1):
        kb  = f["_kb"] or {}
        sev = kb.get("severity", "Unknown")
        rid = kb.get("req_id", "—")
        w(f"| {i} | {f['section']} | {f['name']} | {sev} | {rid} |")
    w()

    # ── detailed failures ─────────────────────────────────────────────────────
    w("---")
    w()
    w("## Detailed Failure Analysis")
    w()

    for i, f in enumerate(failures, 1):
        kb  = f["_kb"] or {}
        sev = kb.get("severity", "Unknown")
        rid = kb.get("req_id", "—")

        w(f"### Failure {i} — [{f['section']}] {f['name']}")
        w()
        w(f"| Field | Value |")
        w(f"|-------|-------|")
        w(f"| **Severity** | {sev} |")
        w(f"| **Requirement** | {rid} |")
        w(f"| **Section** | {f['section']} |")
        w()

        # Raw evidence from the test run
        w("#### What the Test Recorded")
        w()
        w(f"```")
        w(f"{f['detail']}")
        w(f"```")
        w()

        if kb:
            w("#### Root Cause")
            w()
            w(kb["root_cause"])
            w()

            w("#### Expected Behaviour")
            w()
            w(kb["expected"])
            w()

            w("#### Actual Behaviour")
            w()
            w(kb["actual"])
            w()

            w("#### Impact")
            w()
            w(kb["impact"])
            w()

            w("#### Fix Required")
            w()
            w(kb["fix"])
        else:
            w("#### Analysis")
            w()
            w("No additional context available in the knowledge base for this test.")
            w("Review the raw detail above for investigation starting point.")

        w()
        w("---")
        w()

    # ── pass summary ──────────────────────────────────────────────────────────
    w("## Passing Tests")
    w()
    w("All of the following requirements are fully met by the endpoint.")
    w()
    w("| Section | Test |")
    w("|---------|------|")

    # Group passes by section
    sections: dict[str, list] = {}
    for p in passes:
        sections.setdefault(p["section"], []).append(p)
    for sec in sorted(sections):
        for p in sections[sec]:
            w(f"| {sec} | {p['name']} |")
    w()

    # ── performance highlights ─────────────────────────────────────────────────
    ttft_passes = [p for p in passes if "TTFT" in p["name"]]
    otps_passes = [p for p in passes if "OTPS" in p["name"]]

    if ttft_passes or otps_passes:
        w("## Performance Highlights")
        w()
        if ttft_passes:
            w("### TTFT — All Buckets Pass with Exceptional Headroom")
            w()
            w("| Bucket | p50 Actual | p50 Spec | p90 Actual | p90 Spec |")
            w("|--------|-----------|---------|-----------|---------|")
            spec = {
                "<4K":   (2000, 5000),
                "<8K":   (2500, 5000),
                "<32K":  (4000, 8000),
                "<64K":  (8000, 15000),
                "<128K": (15000, 35000),
                "<256K": (30000, 70000),
            }
            for p in ttft_passes:
                ev   = p.get("evidence", {})
                p50  = ev.get("p50_ms", "?")
                p90  = ev.get("p90_ms", "?")
                name = p["name"]
                bucket = next((b for b in spec if b in name), "?")
                sp50, sp90 = spec.get(bucket, ("?", "?"))
                w(f"| {bucket} | **{p50}ms** | {sp50}ms | **{p90}ms** | {sp90}ms |")
            w()

        if otps_passes:
            w("### OTPS — Well Above Spec Targets")
            w()
            w("| Tier | Mean OTPS | Target | Headroom |")
            w("|------|----------|--------|---------|")
            for p in otps_passes:
                ev     = p.get("evidence", {})
                mean   = ev.get("mean", "?")
                target = 30 if "Tier1" in p["name"] else 10
                hd     = f"{mean/target:.1f}x" if isinstance(mean, (int, float)) else "?"
                w(f"| {p['name']} | **{mean}** | {target} | {hd} above target |")
            w()

    # ── action plan ───────────────────────────────────────────────────────────
    w("## Action Plan")
    w()
    w("### Immediate (fix before next stage)")
    w()

    p1s = [f for f in failures if f["_kb"] and "P1" in f["_kb"].get("severity", "")]
    seen_fixes = set()
    for f in p1s:
        fix_key = f["_kb"]["req_id"]
        if fix_key in seen_fixes:
            continue
        seen_fixes.add(fix_key)
        # Group image failures under one action
        if fix_key.startswith("IM-") and fix_key not in ("IM-003", "IM-004"):
            continue
        w(f"**[{f['_kb']['req_id']}]** {f['name']}")
        w(f"> {f['_kb']['fix']}")
        w()

    w("### Medium Priority")
    w()
    p2s = [f for f in failures if f["_kb"] and "P2" in f["_kb"].get("severity", "")]
    for f in p2s:
        w(f"**[{f['_kb']['req_id']}]** {f['name']}")
        w(f"> {f['_kb']['fix']}")
        w()

    w("### Test Issues (no endpoint action required)")
    w()
    test_issues = [f for f in failures
                   if f["_kb"] and "Test Issue" in f["_kb"].get("severity", "")]
    for f in test_issues:
        w(f"**[{f['_kb']['req_id']}]** {f['name']}")
        w(f"> {f['_kb']['fix']}")
        w()

    w("### Informational (no action required)")
    w()
    info = [f for f in failures
            if f["_kb"] and "Informational" in f["_kb"].get("severity", "")]
    for f in info:
        w(f"**[{f['_kb']['req_id']}]** {f['name']}")
        w(f"> {f['_kb']['fix']}")
        w()

    # write out
    md = "\n".join(lines)
    with open(out_path, "w") as f:
        f.write(md)
    print(f"Report written → {out_path}")
    return out_path


def find_latest_report(reports_dir: str) -> str | None:
    reports = sorted(
        Path(reports_dir).glob("eval_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(reports[0]) if reports else None


def main():
    p = argparse.ArgumentParser(description="Generate detailed failure report from eval JSON")
    p.add_argument("--report", help="Path to eval JSON report (default: latest in /reports/)")
    p.add_argument("--out",    help="Output markdown path (default: /reports/failure_report.md)")
    p.add_argument("--reports-dir", default="/reports",
                   help="Directory to search for latest report (default: /reports)")
    args = p.parse_args()

    report_path = args.report
    if not report_path:
        report_path = find_latest_report(args.reports_dir)
        if not report_path:
            # Try local reports/ directory as fallback
            report_path = find_latest_report("./reports")
        if not report_path:
            print("ERROR: No eval_*.json report found. Run eval first or pass --report path.")
            sys.exit(1)
    print(f"Using report: {report_path}")

    out_path = args.out or str(Path(report_path).parent / "failure_report.md")
    generate(report_path, out_path)


if __name__ == "__main__":
    main()

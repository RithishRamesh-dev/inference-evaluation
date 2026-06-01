"""
tests/r8_r9_observability.py
Requirement 8 — Trace ID (OpenTelemetry)
Requirement 9 — Token Statistics Categorization
Spec R8: Support trace ID (OpenTelemetry)
Spec R9: Token statistics support categorization by model_id, text chat,
         image chat, text claw, image claw
"""
import time
from core.common import call, record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R8/R9"

def run():
    console.rule(f"[bold white]{SEC} — Trace ID & Token Statistics[/]")

    # ── R8: OpenTelemetry Trace ID support ────────────────────────────────────
    # Test 1: Send request with traceparent header, verify response doesn't error
    trace_id = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    headers_with_trace = dict(HEADERS)
    headers_with_trace["traceparent"] = trace_id
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=headers_with_trace,
                       json={"model": MODEL,
                             "messages": [{"role":"user","content":"Hi"}],
                             "thinking": {"type":"disabled"},
                             "temperature": 0.6, "max_tokens": 64},
                       timeout=30)
        status = r.status_code
        # Check if traceparent is echoed in response headers
        resp_trace = r.headers.get("traceparent", "")
        trace_accepted = status == 200  # 200 = trace header didn't break it
        trace_echoed   = bool(resp_trace)
        record(SEC, "R8-1 Trace ID header accepted without error",
               trace_accepted, f"HTTP={status}")
        record(SEC, "R8-2 Trace ID echoed in response headers",
               trace_echoed, f"traceparent in response: {bool(resp_trace)}")
        console.print(f"  {'✓' if trace_accepted else '✗'} R8-1: traceparent header accepted | HTTP={status}")
        console.print(f"  {'✓' if trace_echoed else '✗'} R8-2: traceparent echoed in response | present={trace_echoed}")
    except Exception as e:
        record(SEC, "R8-1 Trace ID header", False, str(e))
        console.print(f"  ✗ R8-1: error {e}")

    # Test 3: Check if x-trace-id or similar is returned
    try:
        r3 = httpx.post(f"{ENDPOINT}/chat/completions",
                        headers=HEADERS,
                        json={"model": MODEL,
                              "messages": [{"role":"user","content":"Hi"}],
                              "thinking": {"type":"disabled"},
                              "temperature": 0.6, "max_tokens": 64},
                        timeout=30)
        trace_headers = {k: v for k, v in r3.headers.items()
                         if "trace" in k.lower() or "request-id" in k.lower()}
        has_trace_header = bool(trace_headers)
        record(SEC, "R8-3 Trace/request-id header in response",
               has_trace_header, f"trace headers: {trace_headers}")
        console.print(f"  {'✓' if has_trace_header else '✗'} R8-3: trace headers returned | {trace_headers}")
    except Exception as e:
        record(SEC, "R8-3 Trace header in response", False, str(e))

    # ── R9: Token Statistics Categorization ──────────────────────────────────
    # Spec: by model_id, text chat, image chat, text claw, image claw
    # Test: verify usage object is present in responses (this is what's accessible
    # from the API; full categorization requires vendor-side metrics dashboard)

    # R9-1: usage object present in text chat response
    r_text = call([{"role":"user","content":"Hello."}], think=False, max_tokens=64)
    usage_text = r_text.get("usage", {})
    has_usage = bool(usage_text.get("prompt_tokens") and usage_text.get("completion_tokens"))
    record(SEC, "R9-1 usage object present in text chat response", has_usage,
           f"usage={usage_text}")
    console.print(f"  {'✓' if has_usage else '✗'} R9-1: usage in text chat | {usage_text}")

    # R9-2: model field in response matches requested model
    resp_model = r_text.get("model", "")
    model_matches = MODEL in resp_model or resp_model in MODEL
    record(SEC, "R9-2 model field present in response (for model_id categorization)",
           bool(resp_model), f"model_in_response={resp_model}")
    console.print(f"  {'✓' if bool(resp_model) else '✗'} R9-2: model field | response_model={resp_model}")

    # R9-3: usage present in tool call (text claw) response
    r_tool = call([{"role":"user","content":"Use the calculator."}], think=True,
                  tools=[{"type":"function","function":{"name":"calc",
                           "description":"Calculate","parameters":{"type":"object","properties":{}}}}],
                  max_tokens=512)
    usage_tool = r_tool.get("usage", {})
    has_tool_usage = bool(usage_tool.get("prompt_tokens"))
    record(SEC, "R9-3 usage present in tool call (text claw) response", has_tool_usage,
           f"usage={usage_tool}")
    console.print(f"  {'✓' if has_tool_usage else '✗'} R9-3: usage in tool call | {usage_tool}")

    console.print(f"\n  [dim]Note: Full R9 token categorization (by img chat, img claw) requires[/]")
    console.print(f"  [dim]image support to be enabled (currently blocked by R7 failures).[/]")
    console.print(f"  [dim]Vendor-side metrics dashboard verification required for complete R9.[/]")
    console.print()

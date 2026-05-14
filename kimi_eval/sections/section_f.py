"""Section F — Image Input  (IM-001 to IM-011)"""
from core.common import console, record, call, body, fr, sc, MODEL

# Stable Wikimedia Commons images — no expiry, valid past March 2027
IMG_A = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png"
IMG_B = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Camponotus_flavomarginatus_ant.jpg/320px-Camponotus_flavomarginatus_ant.jpg"


def run():
    console.rule("[bold cyan]F — Image Input[/]")

    # IM-003: Schema A — bare URL string
    data, raw, _, err = call({"model": MODEL, "enable_thinking": True,
                               "temperature": 1.0, "max_tokens": 128,
                               "messages": [{"role": "user", "content": [
                                   {"type": "image_url", "image_url": IMG_A},
                                   {"type": "text", "text": "Describe this image in one sentence."}]}]})
    record("F", "IM-003 Schema A (bare URL string)", err is None and sc(raw) == 200 and bool(body(data) if data else ""),
           f"HTTP {sc(raw)}" + (f" resp={body(data)[:60]!r}" if data else ""))

    # IM-004: Schema B — nested {"url": "..."}
    data, raw, _, err = call({"model": MODEL, "enable_thinking": False,
                               "temperature": 0.6, "max_tokens": 128,
                               "messages": [{"role": "user", "content": [
                                   {"type": "image_url", "image_url": {"url": IMG_A}},
                                   {"type": "text", "text": "What colors appear in this image?"}]}]})
    record("F", "IM-004 Schema B (nested URL object)", err is None and sc(raw) == 200 and bool(body(data) if data else ""),
           f"HTTP {sc(raw)}" + (f" resp={body(data)[:60]!r}" if data else ""))

    # IM-007: finish_reason=stop for image request
    if data:
        record("F", "IM-007 finish_reason=stop for image request", fr(data) == "stop",
               f"fr={fr(data)!r}")

    # IM-009: Multiple images
    data, raw, _, err = call({"model": MODEL, "enable_thinking": False,
                               "temperature": 0.6, "max_tokens": 64,
                               "messages": [{"role": "user", "content": [
                                   {"type": "image_url", "image_url": {"url": IMG_A}},
                                   {"type": "image_url", "image_url": {"url": IMG_B}},
                                   {"type": "text", "text": "Are these images similar?"}]}]})
    record("F", "IM-009 Multiple images in one request", err is None and sc(raw) == 200, f"HTTP {sc(raw)}")

    # IM-006: Image in role=tool (200=full support, 400/422=structural constraint, 500=fail)
    _, raw, _, err = call({"model": MODEL, "enable_thinking": False,
                            "temperature": 0.6, "max_tokens": 64,
                            "messages": [
                                {"role": "user", "content": "Describe the image from the tool."},
                                {"role": "tool", "tool_call_id": "call_001",
                                 "content": [{"type": "image_url", "image_url": {"url": IMG_A}}]}]})
    record("F", "IM-006 Image in role=tool (no 5xx)", sc(raw) in (200, 400, 422),
           f"HTTP {sc(raw)} ({'ok' if sc(raw)==200 else 'structural constraint'})")

    # IM-008: finish_reason=tool_calls with image + forced tool
    TOOL = [{"type": "function", "function": {"name": "describe_image",
             "description": "Describe the image.",
             "parameters": {"type": "object", "properties": {
                 "description": {"type": "string"}}, "required": ["description"]}}}]
    data, raw, _, err = call({"model": MODEL, "enable_thinking": True,
                               "temperature": 1.0, "max_tokens": 512,
                               "tools": TOOL, "tool_choice": "required",
                               "messages": [{"role": "user", "content": [
                                   {"type": "image_url", "image_url": {"url": IMG_A}},
                                   {"type": "text", "text": "Use describe_image on this."}]}]})
    if err or not data:
        record("F", "IM-008 finish_reason=tool_calls + image", False, f"HTTP {sc(raw)} err={err}")
    else:
        record("F", "IM-008 finish_reason=tool_calls + image", fr(data) == "tool_calls",
               f"fr={fr(data)!r}")

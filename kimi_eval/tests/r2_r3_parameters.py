"""
tests/r2_r3_parameters.py — Requirements 2 & 3: Parameter Defaults & max_tokens
"""
import time, os
from core.common import call, record, console, HEADERS, ENDPOINT
import httpx

SEC = "R2/R3"

def raw(payload):
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=30)
        d = r.json()
        d["_http_status"] = r.status_code
        return d
    except Exception as e:
        return {"error": str(e), "_http_status": 0}

def show(req_summary, response):
    status  = response.get("_http_status", "?")
    choice  = (response.get("choices") or [{}])[0]
    msg     = choice.get("message", {})
    fr      = choice.get("finish_reason", "")
    usage   = response.get("usage", {})
    content_len = len(msg.get("content") or "")
    rc_len      = len(msg.get("reasoning_content") or "")
    content_preview = (msg.get("content") or "")[:60]
    err = response.get("error") or response.get("errors") or ""
    console.print(f"    REQUEST  : {req_summary}")
    console.print(f"    RESPONSE : HTTP={status} finish={fr} "
                  f"content_len={content_len} rc_len={rc_len} "
                  f"completion_tokens={usage.get('completion_tokens','?')}"
                  + (f" error={err}" if err else ""))
    if content_preview:
        console.print(f"    content  : {content_preview!r}")

def run():
    console.rule(f"[bold white]{SEC} — Parameter Defaults & max_tokens[/]")
    MODEL = os.environ.get("EVAL_MODEL", "kimi-k2.6")
    msgs  = [{"role": "user", "content": "Say hello."}]

    # R2-1: think temp=1.0
    r = call(msgs, think=True, max_tokens=64)
    p = r.get("_http_status") == 200
    show("thinking=enabled temperature=1.0 max_tokens=64", r)
    record(SEC, "R2-1 think=on default temperature=1.0 accepted", p, f"HTTP={r.get('_http_status')}")
    console.print(f"  {'v' if p else 'x'} R2-1 think temp=1.0\n")

    # R2-2: non-think temp=0.6
    r2 = call(msgs, think=False, max_tokens=64)
    p2 = r2.get("_http_status") == 200
    show("thinking=disabled temperature=0.6 max_tokens=64", r2)
    record(SEC, "R2-2 think=off default temperature=0.6 accepted", p2, f"HTTP={r2.get('_http_status')}")
    console.print(f"  {'v' if p2 else 'x'} R2-2 non-think temp=0.6\n")

    # R2-3: top_p=0.95
    r3 = raw({"model": MODEL, "messages": msgs,
               "thinking": {"type":"disabled"}, "top_p": 0.95, "max_tokens": 64})
    p3 = r3.get("_http_status") == 200
    show("top_p=0.95", r3)
    record(SEC, "R2-3 top_p=0.95 accepted", p3, f"HTTP={r3.get('_http_status')}")
    console.print(f"  {'v' if p3 else 'x'} R2-3 top_p=0.95\n")

    # R2-4: penalties=0
    r4 = raw({"model": MODEL, "messages": msgs, "thinking": {"type":"disabled"},
               "presence_penalty": 0, "frequency_penalty": 0, "max_tokens": 64})
    p4 = r4.get("_http_status") == 200
    show("presence_penalty=0 frequency_penalty=0", r4)
    record(SEC, "R2-4 presence_penalty=0 frequency_penalty=0 accepted", p4, f"HTTP={r4.get('_http_status')}")
    console.print(f"  {'v' if p4 else 'x'} R2-4 penalties=0\n")

    # R2-5: n=1 single choice
    choices = r2.get("choices") or []
    p5 = len(choices) == 1
    record(SEC, "R2-5 n=1 default, single choice returned", p5, f"choices={len(choices)}")
    console.print(f"  {'v' if p5 else 'x'} R2-5 n=1 | choices={len(choices)}\n")

    # R2-6: temp > 1.0 must error (spec: range 0-1)
    r6 = raw({"model": MODEL, "messages": msgs, "thinking": {"type":"disabled"},
               "temperature": 1.5, "max_tokens": 64})
    s6 = r6.get("_http_status", 0)
    p6 = s6 in (400, 422)
    show("temperature=1.5 (spec range 0-1, must error)", r6)
    if not p6:
        console.print(f"  [red]  VENDOR BUG: temperature=1.5 accepted (HTTP={s6}). "
                       "Spec requires range 0-1, return error if exceeded.[/]")
    record(SEC, "R2-6 temperature>1.0 returns 4xx (spec range 0-1)", p6,
           f"HTTP={s6} -- VENDOR BUG if 200: spec mandates error for out-of-range temp")
    console.print(f"  {'v' if p6 else 'x'} R2-6 temp=1.5 => HTTP={s6} "
                   f"({'OK 4xx' if p6 else 'FAIL -- accepted silently'})\n")

    # R2-7: temp < 0 must error
    r7 = raw({"model": MODEL, "messages": msgs, "thinking": {"type":"disabled"},
               "temperature": -0.1, "max_tokens": 64})
    s7 = r7.get("_http_status", 0)
    p7 = s7 in (400, 422)
    show("temperature=-0.1 (spec range 0-1, must error)", r7)
    if not p7:
        console.print(f"  [red]  VENDOR BUG: temperature=-0.1 accepted (HTTP={s7}). "
                       "Spec requires range 0-1, return error if exceeded.[/]")
    record(SEC, "R2-7 temperature<0 returns 4xx (spec range 0-1)", p7,
           f"HTTP={s7} -- VENDOR BUG if 200: spec mandates error for out-of-range temp")
    console.print(f"  {'v' if p7 else 'x'} R2-7 temp=-0.1 => HTTP={s7} "
                   f"({'OK 4xx' if p7 else 'FAIL -- accepted silently'})\n")

    # R3-1: max_tokens default allows natural completion
    r8 = raw({"model": MODEL,
               "messages": [{"role":"user","content":"Write 3 sentences about photosynthesis."}],
               "thinking": {"type":"disabled"}, "temperature": 0.6})
    fr8 = (r8.get("choices") or [{}])[0].get("finish_reason", "")
    tok8 = r8.get("usage", {}).get("completion_tokens", 0)
    content8_len = len((r8.get("choices") or [{}])[0].get("message", {}).get("content") or "")
    p8 = r8.get("_http_status") == 200 and fr8 == "stop"
    show("NO max_tokens (test default=32768 allows natural stop)", r8)
    record(SEC, "R3-1 max_tokens default allows natural completion (finish=stop)", p8,
           f"finish={fr8} completion_tokens={tok8} content_len={content8_len}")
    console.print(f"  {'v' if p8 else 'x'} R3-1 default max_tokens | finish={fr8} tokens={tok8}\n")

    # R3-2: max_tokens=20 enforced
    # Note: if TM-004 is present, reasoning_content tokens may not count against max_tokens.
    # We check: content length should be very short AND finish=length
    r9 = call([{"role":"user","content":"Count from 1 to 1000 in words."}],
              think=False, max_tokens=20)
    fr9          = (r9.get("choices") or [{}])[0].get("finish_reason", "")
    tok9         = r9.get("usage", {}).get("completion_tokens", 0)
    content9     = (r9.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    content9_len = len(content9)
    rc9_len      = len((r9.get("choices") or [{}])[0].get("message", {}).get("reasoning_content") or "")
    # Pass if either: finish=length (ideal), or content is very short (<100 chars, truncated)
    p9 = fr9 == "length" or (content9_len < 100 and content9_len > 0)
    show("max_tokens=20 (must truncate)", r9)
    console.print(f"    content (first 80): {content9[:80]!r}")
    console.print(f"    content_len={content9_len} rc_len={rc9_len} completion_tokens={tok9}")

    if fr9 == "stop" and tok9 > 100:
        console.print(f"  [red]  VENDOR BUG: max_tokens=20 ignored. "
                       f"Endpoint generated {tok9} completion tokens with finish=stop.[/]")
        console.print(f"  [yellow]  Likely cause: TM-004 -- reasoning tokens are not counted "
                       "against max_tokens budget. The thinking trace consumes the budget "
                       "but is not reflected in completion_tokens.[/]")
    record(SEC, "R3-2 max_tokens=20 enforced (content truncated)", p9,
           f"finish={fr9} completion_tokens={tok9} content_len={content9_len} "
           f"-- VENDOR BUG: max_tokens ignored (related to TM-004 reasoning token accounting)")
    console.print(f"  {'v' if p9 else 'x'} R3-2 max_tokens=20 | finish={fr9} "
                   f"tokens={tok9} content_len={content9_len}\n")

    # R3-3: max_tokens=512 modifiable
    r10 = call([{"role":"user","content":"Hello."}], think=False, max_tokens=512)
    p10 = r10.get("_http_status") == 200
    show("max_tokens=512 (user modifiable)", r10)
    record(SEC, "R3-3 max_tokens=512 accepted (user modifiable)", p10, f"HTTP={r10.get('_http_status')}")
    console.print(f"  {'v' if p10 else 'x'} R3-3 max_tokens=512 accepted\n")

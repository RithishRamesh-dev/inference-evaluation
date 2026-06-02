"""
tests/r2_r3_parameters.py — Requirements 2 & 3: Parameter Defaults & max_tokens
"""
import time
from core.common import call, record, console, HEADERS, ENDPOINT
import httpx, os

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

def show_exchange(request_summary, response):
    status  = response.get("_http_status", "?")
    choice  = (response.get("choices") or [{}])[0]
    msg     = choice.get("message", {})
    fr      = choice.get("finish_reason", "")
    usage   = response.get("usage", {})
    err     = response.get("error", {})
    console.print(f"    REQUEST  : {request_summary}")
    console.print(f"    RESPONSE : HTTP={status} finish={fr} "
                  f"tokens={usage.get('completion_tokens','?')}"
                  + (f" error={err}" if err else ""))

def run():
    console.rule(f"[bold white]{SEC} — Parameter Defaults & max_tokens[/]")
    MODEL = os.environ.get("EVAL_MODEL", "kimi-k2.6")
    msgs  = [{"role": "user", "content": "Say hello."}]

    # R2-1: think temp=1.0
    r = call(msgs, think=True, max_tokens=64)
    p = r.get("_http_status") == 200
    show_exchange('thinking=enabled temperature=1.0 max_tokens=64', r)
    record(SEC, "R2-1 think=on default temperature=1.0 accepted", p, f"HTTP={r.get('_http_status')}")
    console.print(f"  {'✓' if p else '✗'} R2-1 think temp=1.0\n")

    # R2-2: non-think temp=0.6
    r2 = call(msgs, think=False, max_tokens=64)
    p2 = r2.get("_http_status") == 200
    show_exchange('thinking=disabled temperature=0.6 max_tokens=64', r2)
    record(SEC, "R2-2 think=off default temperature=0.6 accepted", p2, f"HTTP={r2.get('_http_status')}")
    console.print(f"  {'✓' if p2 else '✗'} R2-2 non-think temp=0.6\n")

    # R2-3: top_p=0.95
    r3 = raw({"model": MODEL, "messages": msgs,
               "thinking": {"type":"disabled"}, "top_p": 0.95, "max_tokens": 64})
    p3 = r3.get("_http_status") == 200
    show_exchange('top_p=0.95', r3)
    record(SEC, "R2-3 top_p=0.95 accepted", p3, f"HTTP={r3.get('_http_status')}")
    console.print(f"  {'✓' if p3 else '✗'} R2-3 top_p=0.95\n")

    # R2-4: penalties=0
    r4 = raw({"model": MODEL, "messages": msgs, "thinking": {"type":"disabled"},
               "presence_penalty": 0, "frequency_penalty": 0, "max_tokens": 64})
    p4 = r4.get("_http_status") == 200
    show_exchange('presence_penalty=0 frequency_penalty=0', r4)
    record(SEC, "R2-4 presence_penalty=0 frequency_penalty=0 accepted", p4, f"HTTP={r4.get('_http_status')}")
    console.print(f"  {'✓' if p4 else '✗'} R2-4 penalties=0\n")

    # R2-5: n=1 single choice
    choices = r2.get("choices") or []
    p5 = len(choices) == 1
    record(SEC, "R2-5 n=1 default, single choice returned", p5, f"choices={len(choices)}")
    console.print(f"  {'✓' if p5 else '✗'} R2-5 n=1 | choices={len(choices)}\n")

    # R2-6: temp > 1.0 MUST error (spec: range 0-1, error if out of range)
    r6 = raw({"model": MODEL, "messages": msgs, "thinking": {"type":"disabled"},
               "temperature": 1.5, "max_tokens": 64})
    s6 = r6.get("_http_status", 0)
    p6 = s6 in (400, 422)
    show_exchange('temperature=1.5 (out of range, must error)', r6)
    console.print(f"  {'✓' if p6 else '✗'} R2-6 temp=1.5 → HTTP={s6} "
                   f"({'✓ correct 4xx' if p6 else '✗ should be 400/422 per spec'})\n")
    record(SEC, "R2-6 temperature>1.0 returns 4xx (range 0-1 enforced)", p6,
           f"HTTP={s6} — spec says range 0-1, error if exceeded")

    # R2-7: temp < 0 MUST error
    r7 = raw({"model": MODEL, "messages": msgs, "thinking": {"type":"disabled"},
               "temperature": -0.1, "max_tokens": 64})
    s7 = r7.get("_http_status", 0)
    p7 = s7 in (400, 422)
    show_exchange('temperature=-0.1 (out of range, must error)', r7)
    console.print(f"  {'✓' if p7 else '✗'} R2-7 temp=-0.1 → HTTP={s7} "
                   f"({'✓ correct 4xx' if p7 else '✗ should be 400/422 per spec'})\n")
    record(SEC, "R2-7 temperature<0 returns 4xx (range 0-1 enforced)", p7,
           f"HTTP={s7} — spec says range 0-1, error if exceeded")

    # R3-1: max_tokens default=32768 (omit, response completes naturally)
    r8 = raw({"model": MODEL,
               "messages": [{"role":"user","content":"Write 3 sentences about photosynthesis."}],
               "thinking": {"type":"disabled"}, "temperature": 0.6})
    fr8 = (r8.get("choices") or [{}])[0].get("finish_reason", "")
    tok8 = r8.get("usage", {}).get("completion_tokens", 0)
    p8 = r8.get("_http_status") == 200 and fr8 == "stop"
    show_exchange('NO max_tokens (test default=32768)', r8)
    console.print(f"  {'✓' if p8 else '✗'} R3-1 max_tokens default | finish={fr8} tokens={tok8}\n")
    record(SEC, "R3-1 max_tokens default allows natural completion (finish=stop)", p8,
           f"finish={fr8} tokens={tok8}")

    # R3-2: max_tokens=20 enforced
    r9 = call([{"role":"user","content":"Count from 1 to 1000."}],
              think=False, max_tokens=20)
    fr9  = (r9.get("choices") or [{}])[0].get("finish_reason", "")
    tok9 = r9.get("usage", {}).get("completion_tokens", 0)
    p9 = fr9 == "length" and tok9 <= 22  # small buffer for tokenization variance
    show_exchange('max_tokens=20 (must truncate, finish=length)', r9)
    console.print(f"  {'✓' if p9 else '✗'} R3-2 max_tokens=20 | finish={fr9} tokens={tok9} "
                   f"({'✓' if p9 else '✗ expected finish=length'})\n")
    record(SEC, "R3-2 max_tokens=20 enforced (finish_reason=length)", p9,
           f"finish={fr9} tokens={tok9}")
    if not p9 and fr9 == "stop":
        console.print(f"  [red]  FAIL: endpoint ignored max_tokens=20, generated {tok9} tokens[/]")

    # R3-3: max_tokens=512 modifiable
    r10 = call([{"role":"user","content":"Hello."}], think=False, max_tokens=512)
    p10 = r10.get("_http_status") == 200
    show_exchange('max_tokens=512 (user modifiable)', r10)
    record(SEC, "R3-3 max_tokens=512 accepted (user modifiable)", p10, f"HTTP={r10.get('_http_status')}")
    console.print(f"  {'✓' if p10 else '✗'} R3-3 max_tokens=512 accepted\n")

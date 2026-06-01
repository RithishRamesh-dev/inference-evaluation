"""
tests/r2_r3_parameters.py
Requirements 2 & 3 — Parameter Defaults & max_tokens
Spec: temperature 1.0/0.6, top_p=0.95, penalties=0, n=1, range 0-1, error if out of range
      max_tokens default=32768, user modifiable
"""
import time
from core.common import call, record, console, HEADERS, ENDPOINT
import httpx

SEC = "R2/R3"

def raw_call(payload: dict) -> dict:
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=30)
        d = r.json()
        d["_http_status"] = r.status_code
        return d
    except Exception as e:
        return {"error": str(e), "_http_status": 0}

def run():
    console.rule(f"[bold white]{SEC} — Parameter Defaults & max_tokens[/]")
    msgs = [{"role": "user", "content": "Say hello."}]
    model = __import__("os").environ.get("EVAL_MODEL", "kimi-k2.6")

    # R2-1: think mode temperature default=1.0
    r = call(msgs, think=True, max_tokens=64)
    status = r.get("_http_status", 0)
    record(SEC, "R2-1 think=on temperature default=1.0 accepted", status==200, f"HTTP={status}")
    console.print(f"  {'✓' if status==200 else '✗'} R2-1: think temp=1.0 | HTTP={status}")

    # R2-2: non-think temperature default=0.6
    r2 = call(msgs, think=False, max_tokens=64)
    status2 = r2.get("_http_status", 0)
    record(SEC, "R2-2 think=off temperature default=0.6 accepted", status2==200, f"HTTP={status2}")
    console.print(f"  {'✓' if status2==200 else '✗'} R2-2: non-think temp=0.6 | HTTP={status2}")

    # R2-3: top_p=0.95
    r3 = raw_call({"model": model, "messages": msgs,
                   "thinking": {"type":"disabled"}, "top_p": 0.95, "max_tokens": 64})
    p = r3.get("_http_status", 0) == 200
    record(SEC, "R2-3 top_p=0.95 accepted", p, f"HTTP={r3.get('_http_status')}")
    console.print(f"  {'✓' if p else '✗'} R2-3: top_p=0.95")

    # R2-4: presence_penalty=0 and frequency_penalty=0
    r4 = raw_call({"model": model, "messages": msgs, "thinking": {"type":"disabled"},
                   "presence_penalty": 0, "frequency_penalty": 0, "max_tokens": 64})
    p4 = r4.get("_http_status", 0) == 200
    record(SEC, "R2-4 presence_penalty=0 frequency_penalty=0 accepted", p4, f"HTTP={r4.get('_http_status')}")
    console.print(f"  {'✓' if p4 else '✗'} R2-4: penalties=0")

    # R2-5: n=1 (default, one choice returned)
    choices = (r2.get("choices") or [])
    p5 = len(choices) == 1
    record(SEC, "R2-5 n=1 default, single choice returned", p5, f"choices={len(choices)}")
    console.print(f"  {'✓' if p5 else '✗'} R2-5: n=1 | choices={len(choices)}")

    # R2-6: temperature out of range (>1.0) MUST return error
    r6 = raw_call({"model": model, "messages": msgs, "thinking": {"type":"disabled"},
                   "temperature": 1.5, "max_tokens": 64})
    p6 = r6.get("_http_status", 0) in (400, 422)
    record(SEC, "R2-6 temperature>1.0 returns 4xx error", p6,
           f"HTTP={r6.get('_http_status')} (expected 400/422)")
    console.print(f"  {'✓' if p6 else '✗'} R2-6: temp=1.5 → HTTP={r6.get('_http_status')} (need 4xx)")

    # R2-7: temperature < 0 MUST return error
    r7 = raw_call({"model": model, "messages": msgs, "thinking": {"type":"disabled"},
                   "temperature": -0.1, "max_tokens": 64})
    p7 = r7.get("_http_status", 0) in (400, 422)
    record(SEC, "R2-7 temperature<0 returns 4xx error", p7,
           f"HTTP={r7.get('_http_status')} (expected 400/422)")
    console.print(f"  {'✓' if p7 else '✗'} R2-7: temp=-0.1 → HTTP={r7.get('_http_status')} (need 4xx)")

    # R3-1: max_tokens default=32768 (omit it, response completes naturally)
    r8 = raw_call({"model": model,
                   "messages": [{"role":"user","content":"Write 3 sentences about photosynthesis."}],
                   "thinking": {"type":"disabled"}, "temperature": 0.6})
    usage = r8.get("usage", {})
    fr = (r8.get("choices") or [{}])[0].get("finish_reason", "")
    p8 = r8.get("_http_status", 0) == 200 and fr == "stop"
    record(SEC, "R3-1 max_tokens default allows natural completion", p8,
           f"HTTP={r8.get('_http_status')} finish_reason={fr} tokens={usage.get('completion_tokens')}")
    console.print(f"  {'✓' if p8 else '✗'} R3-1: max_tokens default | finish={fr} tokens={usage.get('completion_tokens')}")

    # R3-2: max_tokens=20 enforced
    r9 = call([{"role":"user","content":"Count from 1 to 1000."}], think=False,
              max_tokens=20)
    fr9 = (r9.get("choices") or [{}])[0].get("finish_reason", "")
    tokens9 = r9.get("usage", {}).get("completion_tokens", 0)
    p9 = fr9 == "length" and tokens9 <= 20
    record(SEC, "R3-2 max_tokens=20 enforced (finish_reason=length)", p9,
           f"finish={fr9} tokens={tokens9}")
    console.print(f"  {'✓' if p9 else '✗'} R3-2: max_tokens=20 | finish={fr9} tokens={tokens9}")

    # R3-3: max_tokens user modifiable (set to 512)
    r10 = call([{"role":"user","content":"Hello."}], think=False, max_tokens=512)
    p10 = r10.get("_http_status", 0) == 200
    record(SEC, "R3-3 max_tokens user modifiable (set 512)", p10,
           f"HTTP={r10.get('_http_status')}")
    console.print(f"  {'✓' if p10 else '✗'} R3-3: max_tokens=512 accepted")

    console.print()

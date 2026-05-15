"""
debug_aime2.py — Find the right parameters to get content out
Run on the droplet: python debug_aime2.py
"""
import os, json, httpx

ENDPOINT = os.environ["EVAL_ENDPOINT_URL"].rstrip("/")
API_KEY  = os.environ["EVAL_API_KEY"]
MODEL    = os.getenv("EVAL_MODEL", "kimi-k2.6")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
TIMEOUT  = 180

# Short problem to reduce thinking time
PROBLEM = "Find the sum of all integer bases b > 9 for which 17_b is a divisor of 97_b."
PROMPT  = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive.\n\n"
    + PROBLEM
)


def test(label, payload):
    print(f"\n=== {label} ===")
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=TIMEOUT)
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg    = choice.get("message") or {}
        content = msg.get("content") or ""
        rc      = msg.get("reasoning_content") or ""
        fr      = choice.get("finish_reason")
        usage   = data.get("usage", {})
        print(f"  finish_reason      : {fr}")
        print(f"  content_len        : {len(content)}")
        print(f"  reasoning_len      : {len(rc)}")
        print(f"  completion_tokens  : {usage.get('completion_tokens')}")
        print(f"  content preview    : {repr(content[:300])}")
    except Exception as e:
        print(f"  ERROR: {e}")


base = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}]}

# T1: streaming — read content chunks as they arrive
print("\n=== T1: STREAMING (think=True) ===")
try:
    payload = {**base, "enable_thinking": True, "temperature": 1.0,
               "max_tokens": 4096, "stream": True}
    content_chunks = []
    rc_chunks      = []
    final_fr       = None
    with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                      headers=HEADERS, json=payload, timeout=TIMEOUT) as r:
        for line in r.iter_lines():
            if line.startswith("data:") and "[DONE]" not in line:
                try:
                    chunk = json.loads(line[5:].strip())
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    if delta.get("content"):
                        content_chunks.append(delta["content"])
                    if delta.get("reasoning_content"):
                        rc_chunks.append(delta["reasoning_content"])
                    fr = (chunk.get("choices") or [{}])[0].get("finish_reason")
                    if fr:
                        final_fr = fr
                except Exception:
                    pass
    full_content = "".join(content_chunks)
    full_rc      = "".join(rc_chunks)
    print(f"  finish_reason  : {final_fr}")
    print(f"  content_len    : {len(full_content)}")
    print(f"  reasoning_len  : {len(full_rc)}")
    print(f"  content        : {repr(full_content[:400])}")
except Exception as e:
    print(f"  ERROR: {e}")

# T2: streaming non-think
print("\n=== T2: STREAMING (think=False) ===")
try:
    payload = {**base, "enable_thinking": False, "temperature": 0.6,
               "max_tokens": 4096, "stream": True}
    content_chunks = []
    rc_chunks      = []
    final_fr       = None
    with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                      headers=HEADERS, json=payload, timeout=TIMEOUT) as r:
        for line in r.iter_lines():
            if line.startswith("data:") and "[DONE]" not in line:
                try:
                    chunk = json.loads(line[5:].strip())
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    if delta.get("content"):
                        content_chunks.append(delta["content"])
                    if delta.get("reasoning_content"):
                        rc_chunks.append(delta["reasoning_content"])
                    fr = (chunk.get("choices") or [{}])[0].get("finish_reason")
                    if fr:
                        final_fr = fr
                except Exception:
                    pass
    full_content = "".join(content_chunks)
    full_rc      = "".join(rc_chunks)
    print(f"  finish_reason  : {final_fr}")
    print(f"  content_len    : {len(full_content)}")
    print(f"  reasoning_len  : {len(full_rc)}")
    print(f"  content        : {repr(full_content[:400])}")
except Exception as e:
    print(f"  ERROR: {e}")

# T3: no enable_thinking field at all (use endpoint default)
test("T3: no enable_thinking field",
     {**base, "temperature": 0.6, "max_tokens": 4096})

# T4: very small max_tokens to see if content appears when rc is limited
test("T4: think=True, max_tokens=512 (force short rc)",
     {**base, "enable_thinking": True, "temperature": 1.0, "max_tokens": 512})

# T5: check if endpoint supports thinking_budget or max_thinking_tokens
test("T5: thinking_budget=1000",
     {**base, "enable_thinking": True, "temperature": 1.0,
      "max_tokens": 4096, "thinking_budget": 1000})

# T6: budget_tokens parameter (some endpoints)
test("T6: max_thinking_tokens=500",
     {**base, "enable_thinking": True, "temperature": 1.0,
      "max_tokens": 4096, "max_thinking_tokens": 500})

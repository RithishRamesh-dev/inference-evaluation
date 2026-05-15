"""
Debug: send a failing AIME problem and inspect the raw response.
Run this ON THE DROPLET to see exactly what the endpoint returns.
"""
import os, json, httpx

ENDPOINT = os.environ["EVAL_ENDPOINT_URL"].rstrip("/")
API_KEY  = os.environ["EVAL_API_KEY"]
MODEL    = os.getenv("EVAL_MODEL", "kimi-k2.6")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# Problem I_02 — one of the failing ones (expected=588)
PROBLEM = """On triangle ABC, points A, D, E, and B lie in that order on side AB with AD=4, DE=16, and EB=8. Points A, F, G, and C lie in that order on side AC with AF=13, FG=52, and GC=26. Let M be the reflection of D through F, and let N be the reflection of G through E. Quadrilateral DMNE has area 552. Find the area of heptagon AFNEBMD."""

PROMPT = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive.\n\n"
    + PROBLEM
)

print("=== TEST 1: think=True, max_tokens=4096 ===")
payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": PROMPT}],
    "enable_thinking": True,
    "temperature": 1.0,
    "max_tokens": 4096,
}
r = httpx.post(f"{ENDPOINT}/chat/completions", headers=HEADERS, json=payload, timeout=120)
data = r.json()
choice = (data.get("choices") or [{}])[0]
msg = choice.get("message") or {}
content = msg.get("content") or ""
rc = msg.get("reasoning_content") or ""
fr = choice.get("finish_reason")
usage = data.get("usage", {})

print(f"  HTTP: {r.status_code}")
print(f"  finish_reason: {fr}")
print(f"  content_len: {len(content)}")
print(f"  reasoning_content_len: {len(rc)}")
print(f"  prompt_tokens: {usage.get('prompt_tokens')}")
print(f"  completion_tokens: {usage.get('completion_tokens')}")
print(f"  content preview: {repr(content[:200])}")
print()

print("=== TEST 2: think=False, max_tokens=4096 ===")
payload2 = {**payload, "enable_thinking": False, "temperature": 0.6}
r2 = httpx.post(f"{ENDPOINT}/chat/completions", headers=HEADERS, json=payload2, timeout=120)
data2 = r2.json()
choice2 = (data2.get("choices") or [{}])[0]
msg2 = choice2.get("message") or {}
content2 = msg2.get("content") or ""
rc2 = msg2.get("reasoning_content") or ""
fr2 = choice2.get("finish_reason")
usage2 = data2.get("usage", {})

print(f"  HTTP: {r2.status_code}")
print(f"  finish_reason: {fr2}")
print(f"  content_len: {len(content2)}")
print(f"  reasoning_content_len: {len(rc2)}")
print(f"  prompt_tokens: {usage2.get('prompt_tokens')}")
print(f"  completion_tokens: {usage2.get('completion_tokens')}")
print(f"  content preview: {repr(content2[:200])}")
print(f"  content last 200: {repr(content2[-200:])}")
print()

print("=== TEST 3: think=True, max_tokens=8192 ===")
payload3 = {**payload, "enable_thinking": True, "temperature": 1.0, "max_tokens": 8192}
r3 = httpx.post(f"{ENDPOINT}/chat/completions", headers=HEADERS, json=payload3, timeout=120)
data3 = r3.json()
choice3 = (data3.get("choices") or [{}])[0]
msg3 = choice3.get("message") or {}
content3 = msg3.get("content") or ""
rc3 = msg3.get("reasoning_content") or ""
fr3 = choice3.get("finish_reason")
usage3 = data3.get("usage", {})

print(f"  HTTP: {r3.status_code}")
print(f"  finish_reason: {fr3}")
print(f"  content_len: {len(content3)}")
print(f"  reasoning_content_len: {len(rc3)}")
print(f"  completion_tokens: {usage3.get('completion_tokens')}")
print(f"  content preview: {repr(content3[:300])}")

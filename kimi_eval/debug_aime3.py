"""
debug_aime3.py — Full transparency diagnostic
Shows exact request, raw response, and token accounting.
Run on droplet: python debug_aime3.py
"""
import os, json, httpx

ENDPOINT = os.environ["EVAL_ENDPOINT_URL"].rstrip("/")
API_KEY  = os.environ["EVAL_API_KEY"]
MODEL    = os.getenv("EVAL_MODEL", "kimi-k2.6")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# Use the SIMPLEST possible problem to minimise thinking time
SIMPLE = "What is 1+1? Put your final answer in \\boxed{}. The answer is an integer 0-999."
HARD   = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive.\n\n"
    "On triangle ABC, points A, D, E, and B lie in that order on side AB with "
    "AD=4, DE=16, and EB=8. Points A, F, G, and C lie in that order on side AC "
    "with AF=13, FG=52, and GC=26. Let M be the reflection of D through F, and "
    "let N be the reflection of G through E. Quadrilateral DMNE has area 552. "
    "Find the area of heptagon AFNEBMD."
)

SEP = "=" * 70

def show_stream(label, payload):
    print(f"\n{SEP}")
    print(f"REQUEST: {label}")
    print(f"{SEP}")
    # Show exact request
    display = {k: v for k, v in payload.items() if k != "messages"}
    display["messages"] = [{"role": m["role"], "content": m["content"][:200] + "..."}
                           if len(m.get("content","")) > 200 else m
                           for m in payload.get("messages", [])]
    print(json.dumps(display, indent=2))
    print(f"\nFull prompt ({len(payload['messages'][0]['content'])} chars):")
    print(payload['messages'][0]['content'])
    print()

    content_parts, rc_parts = [], []
    finish_reason = None
    usage = {}
    chunk_count = 0

    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=300) as r:
            print(f"HTTP status: {r.status_code}")
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                    chunk_count += 1
                    choice = (chunk.get("choices") or [{}])[0]
                    delta  = choice.get("delta", {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                    if delta.get("reasoning_content"):
                        rc_parts.append(delta["reasoning_content"])
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                except Exception:
                    pass
    except Exception as e:
        print(f"STREAM ERROR: {e}")
        return

    content = "".join(content_parts)
    rc      = "".join(rc_parts)

    print(f"\nRESPONSE:")
    print(f"  chunks received   : {chunk_count}")
    print(f"  finish_reason     : {finish_reason}")
    print(f"  content_len       : {len(content)}")
    print(f"  reasoning_len     : {len(rc)}")
    print(f"  usage             : {usage}")
    print(f"\n  --- reasoning_content (first 500 chars) ---")
    print(f"  {repr(rc[:500])}")
    print(f"\n  --- reasoning_content (last 200 chars) ---")
    print(f"  {repr(rc[-200:])}")
    print(f"\n  --- content (full) ---")
    print(f"  {repr(content)}")
    print(f"\n  \\boxed found: {bool('boxed' in content)}")


# ── Test 1: Simple problem, NO max_tokens (let endpoint decide) ───────────────
show_stream("Simple problem, no max_tokens, think=True", {
    "model": MODEL,
    "messages": [{"role": "user", "content": SIMPLE}],
    "enable_thinking": True,
    "temperature": 1.0,
    "stream": True,
})

# ── Test 2: Hard problem, NO max_tokens, think=True ───────────────────────────
show_stream("HARD problem (I_02), no max_tokens, think=True", {
    "model": MODEL,
    "messages": [{"role": "user", "content": HARD}],
    "enable_thinking": True,
    "temperature": 1.0,
    "stream": True,
})

# ── Test 3: Hard problem, NO max_tokens, think=False ──────────────────────────
show_stream("HARD problem (I_02), no max_tokens, think=False", {
    "model": MODEL,
    "messages": [{"role": "user", "content": HARD}],
    "enable_thinking": False,
    "temperature": 0.6,
    "stream": True,
})

# ── Test 4: Hard problem, no enable_thinking field at all ─────────────────────
show_stream("HARD problem (I_02), NO enable_thinking field", {
    "model": MODEL,
    "messages": [{"role": "user", "content": HARD}],
    "temperature": 0.6,
    "stream": True,
})

# ── Test 5: Hard problem, max_tokens=32768 (endpoint spec says 262144) ────────
show_stream("HARD problem (I_02), max_tokens=32768, think=True", {
    "model": MODEL,
    "messages": [{"role": "user", "content": HARD}],
    "enable_thinking": True,
    "temperature": 1.0,
    "max_tokens": 32768,
    "stream": True,
})

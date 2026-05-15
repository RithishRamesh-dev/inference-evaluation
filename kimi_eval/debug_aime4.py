"""
debug_aime4.py — Targeted 3-problem test with full output display.
Tests the exact same logic as run_aime.py but shows everything.
Run: python debug_aime4.py
"""
import json, os, re, time, httpx

ENDPOINT = os.environ["EVAL_ENDPOINT_URL"].rstrip("/")
API_KEY  = os.environ["EVAL_API_KEY"]
MODEL    = os.getenv("EVAL_MODEL", "kimi-k2.6")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

MAX_TOKENS     = 8192
STREAM_TIMEOUT = 90

PROMPT_PREFIX = (
    "Please reason step by step, and put your final answer within \\boxed{}.\n"
    "The answer is an integer between 0 and 999 inclusive.\n\n"
)

# 3 representative problems: easy, medium, hard
PROBLEMS = [
    {"id": "2025_I_01", "answer": 70,
     "problem": "Find the sum of all integer bases b > 9 for which 17_b is a divisor of 97_b."},
    {"id": "2025_I_02", "answer": 588,
     "problem": "On triangle ABC, points A, D, E, and B lie in that order on side AB with AD=4, DE=16, and EB=8. Points A, F, G, and C lie in that order on side AC with AF=13, FG=52, and GC=26. Let M be the reflection of D through F, and let N be the reflection of G through E. Quadrilateral DMNE has area 552. Find the area of heptagon AFNEBMD."},
    {"id": "2025_I_06", "answer": 504,
     "problem": "An isosceles trapezoid has an inscribed circle tangent to each of its four sides. The radius of the circle is 3, and the area of the trapezoid is 72. Let the parallel sides have lengths r and s (r != s). Find r^2 + s^2."},
]

SEP = "─" * 70

def extract_boxed(text):
    if not text: return None
    matches = re.findall(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
    if not matches: return None
    raw = matches[-1].strip().replace(",","").replace(" ","")
    try:
        val = int(raw)
        return val % 1000 if val >= 1000 else val
    except: pass
    digits = re.sub(r"[^\d]", "", raw)
    if digits:
        val = int(digits)
        return val % 1000 if val >= 1000 else val
    return None

def stream_call(prompt, think, label=""):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "enable_thinking": think,
        "temperature": 1.0 if think else 0.6,
        "max_tokens": MAX_TOKENS,
        "stream": True,
    }
    print(f"\n{SEP}")
    print(f"REQUEST [{label}]")
    print(f"{SEP}")
    print(f"  enable_thinking : {think}")
    print(f"  temperature     : {payload['temperature']}")
    print(f"  max_tokens      : {MAX_TOKENS}")
    print(f"  stream_timeout  : {STREAM_TIMEOUT}s")
    print(f"  prompt ({len(prompt)} chars):")
    print(f"  {prompt[:300]}{'...' if len(prompt)>300 else ''}")

    content_parts, rc_parts = [], []
    finish_reason = None
    timed_out     = False
    chunk_count   = 0
    t0 = time.perf_counter()

    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload,
                          timeout=STREAM_TIMEOUT) as r:
            print(f"\n  HTTP {r.status_code} — streaming...")
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                try:
                    chunk  = json.loads(line[5:].strip())
                    chunk_count += 1
                    choice = (chunk.get("choices") or [{}])[0]
                    delta  = choice.get("delta", {})
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                    if delta.get("reasoning_content"):
                        rc_parts.append(delta["reasoning_content"])
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    # Progress every 500 chunks
                    if chunk_count % 500 == 0:
                        rc_so_far  = sum(len(x) for x in rc_parts)
                        con_so_far = sum(len(x) for x in content_parts)
                        elapsed    = time.perf_counter() - t0
                        print(f"    ...{chunk_count} chunks | {elapsed:.0f}s | "
                              f"rc={rc_so_far} content={con_so_far}")
                except Exception:
                    pass
    except httpx.ReadTimeout:
        timed_out = True
        print(f"  ⚠ TIMED OUT after {STREAM_TIMEOUT}s")
    except Exception as e:
        print(f"  ERROR: {e}")

    elapsed = time.perf_counter() - t0
    content = "".join(content_parts)
    rc      = "".join(rc_parts)

    print(f"\nRESPONSE [{label}]")
    print(f"  elapsed         : {elapsed:.1f}s")
    print(f"  chunks          : {chunk_count}")
    print(f"  finish_reason   : {finish_reason}")
    print(f"  timed_out       : {timed_out}")
    print(f"  content_len     : {len(content)}")
    print(f"  reasoning_len   : {len(rc)}")
    print(f"  reasoning (last 300): {repr(rc[-300:]) if rc else 'EMPTY'}")
    print(f"  content (full)  : {repr(content)}")
    print(f"  extracted       : {extract_boxed(content)}")
    return content, rc, finish_reason, timed_out


for prob in PROBLEMS:
    print(f"\n{'='*70}")
    print(f"PROBLEM: {prob['id']}  (expected answer: {prob['answer']})")
    print(f"{'='*70}")
    prompt = PROMPT_PREFIX + prob["problem"]

    # Primary: think=True
    content, rc, fr, to = stream_call(prompt, think=True, label=f"{prob['id']} think=True")

    # Retry if content empty
    if not content and not to:
        print(f"\n  → Content empty, retrying with think=False...")
        time.sleep(2)
        content, rc, fr, to = stream_call(prompt, think=False,
                                           label=f"{prob['id']} think=False RETRY")

    extracted = extract_boxed(content)
    sym = "✓" if extracted == prob["answer"] else "✗"
    print(f"\n  FINAL: expected={prob['answer']} extracted={extracted} {sym}")
    time.sleep(1)

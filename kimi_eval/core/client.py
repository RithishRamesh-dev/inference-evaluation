"""core/client.py — HTTP client using official Anthropic-style thinking format."""
import json, os, time
import httpx

ENDPOINT = os.environ.get("EVAL_ENDPOINT_URL", "").rstrip("/")
API_KEY  = os.environ.get("EVAL_API_KEY", "")
MODEL    = os.environ.get("EVAL_MODEL", "kimi-k2.6")
TIMEOUT  = int(os.environ.get("EVAL_TIMEOUT", "120"))
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def chat(messages, think=True, temperature=None, max_tokens=4096,
         tools=None, tool_choice=None, extra=None):
    """Blocking chat completion. Returns raw response dict."""
    temp = temperature if temperature is not None else (1.0 if think else 0.6)
    payload = {
        "model":       MODEL,
        "messages":    messages,
        "thinking":    {"type": "enabled" if think else "disabled"},
        "temperature": temp,
        "max_tokens":  max_tokens,
    }
    if tools:       payload["tools"] = tools
    if tool_choice: payload["tool_choice"] = tool_choice
    if extra:       payload.update(extra)
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=TIMEOUT)
        d = r.json()
        d["_status"] = r.status_code
        d["_payload"] = payload
        return d
    except Exception as e:
        return {"error": str(e), "_status": 0, "_payload": payload}

def stream(messages, think=True, temperature=None, max_tokens=8192,
           tools=None, timeout=240):
    """Streaming chat. Returns (content, reasoning_content, finish_reason, timed_out)."""
    temp = temperature if temperature is not None else (1.0 if think else 0.6)
    payload = {
        "model":       MODEL,
        "messages":    messages,
        "thinking":    {"type": "enabled" if think else "disabled"},
        "temperature": temp,
        "max_tokens":  max_tokens,
        "stream":      True,
    }
    if tools: payload["tools"] = tools
    content_parts, rc_parts = [], []
    fr = None
    timed_out = False
    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=timeout) as r:
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                try:
                    chunk  = json.loads(line[5:].strip())
                    choice = (chunk.get("choices") or [{}])[0]
                    delta  = choice.get("delta", {})
                    if delta.get("content"):          content_parts.append(delta["content"])
                    if delta.get("reasoning_content"): rc_parts.append(delta["reasoning_content"])
                    if choice.get("finish_reason"):   fr = choice["finish_reason"]
                except Exception:
                    pass
    except httpx.ReadTimeout:
        timed_out = True
    except Exception as e:
        return "", "", f"error:{e}", False
    return "".join(content_parts), "".join(rc_parts), fr or "", timed_out

def raw_post(payload):
    """Send arbitrary payload, return response dict with _status."""
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=TIMEOUT)
        d = r.json()
        d["_status"] = r.status_code
        return d
    except Exception as e:
        return {"error": str(e), "_status": 0}

def msg(r):
    """Extract message from response."""
    return (r.get("choices") or [{}])[0].get("message") or {}

def content(r):
    return msg(r).get("content") or ""

def rc(r):
    return msg(r).get("reasoning_content") or ""

def fr(r):
    return (r.get("choices") or [{}])[0].get("finish_reason") or ""

def usage(r):
    return r.get("usage") or {}

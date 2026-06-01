"""
core/common.py — Shared HTTP client and helpers
Uses ANTHROPIC-style thinking format: {"thinking": {"type": "enabled/disabled"}}
as specified in the official K2.6 serving requirements.
"""
import json, os, time
import httpx
from rich.console import Console

console = Console()

ENDPOINT = os.environ.get("EVAL_ENDPOINT_URL", "").rstrip("/")
API_KEY  = os.environ.get("EVAL_API_KEY", "")
MODEL    = os.environ.get("EVAL_MODEL", "kimi-k2.6")
TIMEOUT  = int(os.environ.get("EVAL_TIMEOUT", "120"))
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

_results = []

def call(messages: list, think: bool = True, temperature: float = None,
         max_tokens: int = 4096, tools: list = None,
         tool_choice=None, stream: bool = False, extra: dict = None) -> dict:
    """
    HTTP call using OFFICIAL Anthropic-style thinking format.
    think=True  -> {"thinking": {"type": "enabled"}}
    think=False -> {"thinking": {"type": "disabled"}}
    """
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
    if stream:      payload["stream"] = True
    if extra:       payload.update(extra)
    try:
        r = httpx.post(f"{ENDPOINT}/chat/completions",
                       headers=HEADERS, json=payload, timeout=TIMEOUT)
        data = r.json()
        data["_http_status"] = r.status_code
        return data
    except Exception as e:
        return {"error": str(e), "_http_status": 0}

def stream_call(messages: list, think: bool = True, temperature: float = None,
                max_tokens: int = 8192, tools: list = None,
                timeout: int = 240, extra: dict = None) -> tuple:
    """
    Streaming call. Returns (content, reasoning_content, finish_reason, timed_out).
    Required for AIME benchmarks due to TM-004 endpoint bug.
    """
    temp = temperature if temperature is not None else (1.0 if think else 0.6)
    payload = {
        "model":       MODEL,
        "messages":    messages,
        "thinking":    {"type": "enabled" if think else "disabled"},
        "temperature": temp,
        "max_tokens":  max_tokens,
        "stream":      True,
    }
    if tools:  payload["tools"] = tools
    if extra:  payload.update(extra)
    content_parts, rc_parts = [], []
    finish_reason = None
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
                    if choice.get("finish_reason"):   finish_reason = choice["finish_reason"]
                except Exception:
                    pass
    except httpx.ReadTimeout:
        timed_out = True
    except Exception as e:
        return "", "", f"error:{e}", False
    return "".join(content_parts), "".join(rc_parts), finish_reason or "", timed_out

def record(section: str, test_id: str, passed: bool, detail: str = "",
           request: dict = None, response: dict = None):
    _results.append({
        "section": section, "test": test_id, "passed": passed,
        "detail": detail, "request": request, "response": response,
    })

def get_results(): return _results

def print_report(results: list):
    from rich.table import Table
    table = Table(title="Results", show_lines=True)
    table.add_column("§",     style="cyan",  width=6)
    table.add_column("Test",  style="white", width=40)
    table.add_column("Status",width=8)
    table.add_column("Detail",style="dim",   width=40)
    for r in results:
        status = "[green]PASS[/]" if r["passed"] else "[bold red]FAIL[/]"
        table.add_row(r["section"], r["test"], status, r["detail"][:80])
    console.print(table)
    passed = sum(1 for r in results if r["passed"])
    total  = len(results)
    console.print(f"\n  [bold]{passed} PASS / {total - passed} FAIL ({100*passed//total if total else 0}%)[/]")
    console.print()
    if any(not r["passed"] for r in results):
        console.rule("[bold red]FAILURES[/]")
        for r in results:
            if not r["passed"]:
                console.print(f"  ✗ [{r['section']}] {r['test']}\n      {r['detail']}")
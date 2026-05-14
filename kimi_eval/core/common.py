"""
core/common.py — everything shared across sections
===================================================
Intentionally flat. No abstraction layers.
"""

import json
import os
import time
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.table import Table

# ── config ────────────────────────────────────────────────────────────────────
ENDPOINT = os.environ["EVAL_ENDPOINT_URL"].rstrip("/")
API_KEY  = os.environ["EVAL_API_KEY"]
MODEL    = os.getenv("EVAL_MODEL", "kimi-k2")
TIMEOUT  = int(os.getenv("EVAL_TIMEOUT", "120"))
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

console = Console()

# ── results list ──────────────────────────────────────────────────────────────
_results: list[dict] = []

def record(section: str, name: str, passed: bool, detail: str, evidence: dict = None):
    _results.append({
        "section": section, "name": name,
        "passed": passed, "detail": detail,
        "evidence": evidence or {},
    })
    icon = "[green]PASS[/]" if passed else "[bold red]FAIL[/]"
    console.print(f"  {icon}  {name}: {detail}")
    return passed

# ── HTTP ──────────────────────────────────────────────────────────────────────
def call(payload: dict, stream: bool = False):
    """
    POST to /chat/completions.
    Returns (data, raw, ttft_ms, error).
      stream=False → data is response dict,  raw is httpx.Response
      stream=True  → data is list of chunks, raw is None
    """
    url = f"{ENDPOINT}/chat/completions"
    t0  = time.perf_counter()
    try:
        if stream:
            chunks, ttft_ms = [], None
            with httpx.stream("POST", url, headers=HEADERS,
                              json=payload, timeout=TIMEOUT) as r:
                for line in r.iter_lines():
                    if line.startswith("data:") and "[DONE]" not in line:
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - t0) * 1000
                        try:
                            chunks.append(json.loads(line[5:].strip()))
                        except Exception:
                            pass
            return chunks, None, ttft_ms, None
        else:
            r = httpx.post(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
            return r.json(), r, (time.perf_counter() - t0) * 1000, None
    except Exception as e:
        return None, None, None, str(e)

def req(prompt: str, think: bool = True, temperature: float = None,
        max_tokens: int = None, tools: list = None, tool_choice: str = None,
        stream: bool = False, top_p: float = None, extra: dict = None):
    """Single user-message helper — covers 90% of test cases."""
    p = {
        "model":    MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "thinking": {"type": "enabled" if think else "disabled"},
    }
    if temperature is not None: p["temperature"]  = temperature
    if top_p       is not None: p["top_p"]        = top_p
    if max_tokens  is not None: p["max_tokens"]   = max_tokens
    if tools                  : p["tools"]        = tools
    if tool_choice            : p["tool_choice"]  = tool_choice
    if stream                 : p["stream"]       = True
    if extra                  : p.update(extra)
    return call(p, stream=stream)

# ── response field shortcuts ──────────────────────────────────────────────────
def sc(raw) -> int:
    return raw.status_code if raw else 0

def choice(data: dict) -> dict:
    return (data.get("choices") or [{}])[0]

def msg(data: dict) -> dict:
    return choice(data).get("message") or {}

def body(data: dict) -> str:
    return msg(data).get("content") or ""

def thinking(data: dict) -> str:
    return msg(data).get("reasoning_content") or ""

def fr(data: dict) -> str:
    return choice(data).get("finish_reason") or ""

def tc(data: dict) -> list:
    return msg(data).get("tool_calls") or []

# ── report ────────────────────────────────────────────────────────────────────
def print_report(meta: dict = None):
    console.print()
    console.rule("[bold white]EVALUATION REPORT[/]")
    for k, v in (meta or {}).items():
        console.print(f"  {k:<14}: {v}")
    console.print()

    table = Table(title="Results", show_lines=True)
    table.add_column("§",      style="cyan",  no_wrap=True, width=4)
    table.add_column("Test",   style="white", max_width=46)
    table.add_column("Status", justify="center", width=6)
    table.add_column("Detail", style="dim",   max_width=58)

    passed = failed = 0
    for r in _results:
        s = "[green]PASS[/]" if r["passed"] else "[bold red]FAIL[/]"
        table.add_row(r["section"], r["name"], s, r["detail"][:58])
        if r["passed"]: passed += 1
        else:           failed += 1

    console.print(table)

    pct   = passed / (passed + failed) * 100 if (passed + failed) else 0
    color = "green" if failed == 0 else ("yellow" if pct >= 70 else "red")
    console.print(f"\n  [{color}]{passed} PASS / {failed} FAIL ({pct:.0f}%)[/]")

    failures = [r for r in _results if not r["passed"]]
    if failures:
        console.rule("[bold red]FAILURES[/]")
        for r in failures:
            console.print(f"  [red]✗[/] [{r['section']}] {r['name']}\n      {r['detail']}")

    # save JSON
    import json as _json
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"/reports/eval_{ts}.json"
    os.makedirs("/reports", exist_ok=True)
    with open(path, "w") as f:
        _json.dump({"run_at": datetime.now(timezone.utc).isoformat(),
                    "meta": meta or {}, "pass": passed, "fail": failed,
                    "results": _results}, f, indent=2)
    console.print(f"  [dim]→ {path}[/]")

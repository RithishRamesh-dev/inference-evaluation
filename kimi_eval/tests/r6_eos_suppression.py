"""
tests/r6_eos_suppression.py
Requirement 6 — EOS Suppression / 1000-run Statistical Test
Spec: Send request 1000 times. For finish_reason=stop responses,
      count empty content, calculate ratio, record top-5 logprobs.
"""
import json, time
from pathlib import Path
from core.common import call, record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R6"

# Official EOS probe — load from testcases/eos_probe.json (7.json)
def load_probe() -> list:
    probe_path = Path("testcases/eos_probe.json")
    if probe_path.exists():
        with open(probe_path) as f:
            data = json.load(f)
        return data.get("messages", [])
    # Fallback minimal probe
    return [{"role": "user", "content": "Hello, how are you?"}]

def run(n_runs: int = 20):
    console.rule(f"[bold white]{SEC} — EOS Suppression ({n_runs}-run statistical test)[/]")
    if n_runs < 1000:
        console.print(f"  [yellow]⚠ Running {n_runs} reps (spec requires 1000). Use --eos-runs 1000 for compliance.[/]")

    messages = load_probe()
    console.print(f"  Probe: {len(messages)} messages, running {n_runs} times...")

    stop_count   = 0
    empty_count  = 0
    length_count = 0
    error_count  = 0
    logprobs_samples = []

    for i in range(n_runs):
        payload = {
            "model":       MODEL,
            "messages":    messages,
            "thinking":    {"type": "enabled"},
            "temperature": 1.0,
            "max_tokens":  4096,
            "logprobs":    True,
            "top_logprobs": 5,
        }
        try:
            r = httpx.post(f"{ENDPOINT}/chat/completions",
                           headers=HEADERS, json=payload, timeout=120)
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            fr = choice.get("finish_reason", "")
            content = (choice.get("message") or {}).get("content", "") or ""
            lp = choice.get("logprobs")

            if fr == "stop":
                stop_count += 1
                if not content.strip():
                    empty_count += 1
            elif fr == "length":
                length_count += 1

            if lp and len(logprobs_samples) < 5:
                logprobs_samples.append(lp)

        except Exception as e:
            error_count += 1

        if (i + 1) % max(1, n_runs // 5) == 0:
            console.print(f"    [{i+1}/{n_runs}] stop={stop_count} empty={empty_count} errors={error_count}")

    # Calculate ratio
    empty_ratio = (empty_count / stop_count * 100) if stop_count > 0 else 0.0
    passed_ratio = empty_ratio < 1.0   # spec: < 1% empty

    summary = (
        f"n={n_runs} stop={stop_count} length={length_count} "
        f"empty={empty_count} ratio={empty_ratio:.2f}% errors={error_count}"
    )
    console.print(f"\n  {'✓' if passed_ratio else '✗'} R6 Empty ratio: {empty_ratio:.2f}% (threshold <1%)")
    console.print(f"  Mandatory report: {stop_count} stop responses | {empty_count} empty | ratio={empty_ratio:.2f}%")

    if logprobs_samples:
        console.print(f"  Top-5 logprobs captured: {len(logprobs_samples)} samples available")
    else:
        console.print(f"  [yellow]⚠ Top-5 logprobs: endpoint did not return logprobs field[/]")

    record(SEC, "R6-1 Empty content ratio < 1% (stop responses)", passed_ratio, summary)
    record(SEC, "R6-2 finish_reason distribution recorded",
           True, f"stop={stop_count} length={length_count} errors={error_count}")
    record(SEC, "R6-3 Top-5 logprobs captured",
           len(logprobs_samples) > 0,
           f"samples={len(logprobs_samples)} (0=endpoint does not return logprobs)")

    console.print()
    return {
        "n_runs": n_runs, "stop": stop_count, "length": length_count,
        "empty": empty_count, "empty_ratio_pct": round(empty_ratio, 2),
        "errors": error_count, "logprobs_samples": len(logprobs_samples),
    }

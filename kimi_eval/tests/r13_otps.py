"""
tests/r13_otps.py
Requirement 13 — OTPS (Output Tokens Per Second)
Spec: Tier 1 (claw) > 40 OTPS, Tier 2 (chat) > 15 OTPS
      >10% failures = period unavailable
"""
import time, json, statistics
from core.common import record, console, HEADERS, ENDPOINT, MODEL
import httpx

SEC = "R13"

# CORRECT targets from official spec PDF
TIERS = [
    # (label, target_otps, prompt, max_tokens, min_dur_s)
    ("Tier1-claw", 40, (
        "Write a detailed technical explanation of how transformer self-attention works. "
        "Include the mathematical formulation, explain Q/K/V matrices, scaled dot-product "
        "attention, multi-head attention, and positional encoding. Write at least 800 words."
    ), 2048, 0.1),
    ("Tier2-chat", 15, (
        "Write a detailed travel guide to Japan covering Tokyo, Kyoto, Osaka, and Hiroshima. "
        "For each city include top 5 attractions, local food, transport tips. "
        "Write at least 600 words."
    ), 2048, 0.1),
]

def measure_otps(prompt: str, think: bool = False, max_tokens: int = 2048,
                 min_dur: float = 0.1) -> float | None:
    payload = {
        "model":       MODEL,
        "messages":    [{"role":"user","content":prompt}],
        "thinking":    {"type":"enabled" if think else "disabled"},
        "temperature": 0.6,
        "max_tokens":  max_tokens,
        "stream":      True,
        "stream_options": {"include_usage": True},
    }
    content_chars = 0
    first_content_t = None
    last_content_t  = None
    completion_tokens = 0
    try:
        with httpx.stream("POST", f"{ENDPOINT}/chat/completions",
                          headers=HEADERS, json=payload, timeout=120) as r:
            for line in r.iter_lines():
                if not line.startswith("data:") or "[DONE]" in line:
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    if delta.get("content"):
                        t = time.perf_counter()
                        content_chars += len(delta["content"])
                        if first_content_t is None: first_content_t = t
                        last_content_t = t
                    usage = chunk.get("usage")
                    if usage and usage.get("completion_tokens"):
                        completion_tokens = usage["completion_tokens"]
                except Exception:
                    pass
    except Exception:
        return None

    if first_content_t is None or last_content_t is None:
        return None
    dur = last_content_t - first_content_t
    if dur < min_dur:
        return None
    tokens = completion_tokens if completion_tokens else content_chars // 4
    return tokens / dur if dur > 0 else None


def run(n_samples: int = 10):
    console.rule(f"[bold white]{SEC} — OTPS Performance ({n_samples} samples/tier)[/]")
    if n_samples < 30:
        console.print(f"  [yellow]⚠ Using {n_samples} samples (spec requires 30+ for reliability)[/]")
    console.print("  Spec: Tier1 (claw) >40 OTPS | Tier2 (chat) >15 OTPS")
    console.print("  Fail threshold: >10% of requests below target = period unavailable")
    console.print()

    for label, target, prompt, max_tok, min_dur in TIERS:
        otps_list = []
        skipped = errors = 0

        for _ in range(n_samples):
            result = measure_otps(prompt, think=False, max_tokens=max_tok, min_dur=min_dur)
            if result is None:
                skipped += 1
            else:
                otps_list.append(result)
            time.sleep(0.4)

        if len(otps_list) < 2:
            record(SEC, f"{label} >{target} OTPS", False,
                   f"Too few valid: {len(otps_list)}/{n_samples} skipped={skipped}")
            console.print(f"  ✗ {label}: too few valid samples ({len(otps_list)}/{n_samples})")
            continue

        mean_otps = statistics.mean(otps_list)
        p10_otps  = sorted(otps_list)[max(0, int(len(otps_list)*0.10)-1)]
        fail_rate = sum(1 for v in otps_list if v < target) / len(otps_list)

        passed = fail_rate <= 0.10  # ≤10% failures
        detail = (f"mean={mean_otps:.1f} p10={p10_otps:.1f} target>{target} "
                  f"fail_rate={fail_rate*100:.1f}%(≤10%) n={len(otps_list)} skipped={skipped}")
        record(SEC, f"{label} OTPS >{target} fail_rate≤10%", passed, detail)
        icon = "✓" if passed else "✗"
        console.print(f"  {icon} {label}: mean={mean_otps:.1f} p10={p10_otps:.1f} "
                       f"target>{target} fail_rate={fail_rate*100:.1f}%")

    console.print()

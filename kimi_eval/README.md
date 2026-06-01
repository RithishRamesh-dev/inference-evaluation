# kimi-k2.6 Evaluation Harness v3

Requirement-aligned test suite. Each file maps 1:1 to the official K2.6 spec.

## Structure

```
kimi_eval_v3/
├── run.py                          ← Master runner
├── run_evalscope.sh                ← Official benchmark runner (evalscope)
├── tests/
│   ├── r1_thinking_mode.py         ← Req 1: {"thinking":{"type":"enabled/disabled"}}
│   ├── r2_r3_parameters.py         ← Req 2/3: param defaults, max_tokens
│   ├── r4_system_prompt.py         ← Req 4: no vendor system prompt
│   ├── r5_interleaved_thinking.py  ← Req 5: reasoning before tool_calls → 400
│   ├── r6_eos_suppression.py       ← Req 6: 1000-run EOS test + logprobs
│   ├── r7_image_input.py           ← Req 7: official 24-case image test suite
│   ├── r8_r9_observability.py      ← Req 8/9: trace ID (OTel) + token stats
│   ├── r10_openclaw_toolcall.py    ← Req 10: official 12-case OpenClaw suite
│   ├── r11_accuracy.py             ← Req 11: KVV accuracy + evalscope integration
│   ├── r12_ttft.py                 ← Req 12: TTFT 6 buckets (incremental tokens)
│   ├── r13_otps.py                 ← Req 13: OTPS Tier1>40 Tier2>15
│   ├── r14_cache.py                ← Req 14: LRU prefix cache
│   └── r15_r16_r17_sla.py         ← Req 15/16/17: 429 / SLA / RTO
├── testcases/
│   ├── image_testcases.jsonl       ← Official 24-case image test suite (8_vendor-img...)
│   ├── openclaw_testcases.jsonl    ← Official 12-case OpenClaw suite (9_openclaw...)
│   └── eos_probe.json              ← Official EOS probe (7.json)
├── benchmarks/                     ← AIME runner (streaming fallback for evalscope issues)
├── datasets/aime2025.json          ← Official AIME 2025 problems
├── core/common.py                  ← HTTP client (Anthropic-style thinking format)
├── requirements.txt
└── env.example
```

## Setup

```bash
cp env.example .env
# Fill in EVAL_ENDPOINT_URL, EVAL_API_KEY, EVAL_MODEL
pip install -r requirements.txt
pip install evalscope[api]          # for R11 full benchmarks
```

## Running

```bash
# All requirements (smoke)
python run.py

# Specific requirements
python run.py --reqs R1 R4 R5

# Include TTFT + OTPS (slow)
python run.py --perf --perf-samples 30

# Full EOS test (1000 runs as spec requires)
python run.py --reqs R6 --eos-runs 1000

# Full accuracy benchmarks via evalscope
python run.py --reqs R11 --full-accuracy

# Official evalscope runner (separate)
export EVAL_API_KEY=your-key
bash run_evalscope.sh smoke         # 10 samples
bash run_evalscope.sh think         # full think mode
bash run_evalscope.sh all           # both modes
```

## Key Fixes vs Previous Version

| # | What was wrong | What's correct now |
|---|---|---|
| R1 | Used `enable_thinking=true/false` | Now uses `{"thinking":{"type":"enabled/disabled"}}` per spec |
| R7 | Custom image tests | Uses official `8_vendor-img-testcases.jsonl` (24 cases) |
| R10 | Custom tool tests | Uses official `9_openclaw_cases12.jsonl` (12 cases) |
| R13 | Targets: Tier1≥30, Tier2≥10 | Correct targets: Tier1>40, Tier2>15 |
| R8/R9 | Not tested at all | Now tests OTel trace ID + token stats |
| R11 | evalscope external script | Now integrated into harness via `--full-accuracy` |
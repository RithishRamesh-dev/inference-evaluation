# Kimi K2.6 Endpoint Evaluation

Validates a deployed Kimi K2.6 inference endpoint against all Stage 1 requirements.

---

## File Structure

```
kimi_eval/
├── run.py                   ← entry point + CLI
├── core/
│   └── common.py            ← HTTP client, record(), report, field helpers
├── sections/
│   ├── section_a.py         ← Thinking Mode          (TM-001–TM-005)
│   ├── section_b.py         ← Parameter Defaults     (PD-001–PD-012)
│   ├── section_c.py         ← System Prompt          (SP-001–SP-004)
│   ├── section_d.py         ← Interleaved Thinking   (IT-001–IT-007)
│   ├── section_e.py         ← EOS / Special Token    (ST-001–ST-007)
│   ├── section_f.py         ← Image Input            (IM-001–IM-011)
│   ├── section_g.py         ← Tool Calling           (TC-001–TC-010)
│   ├── section_h.py         ← Accuracy Smoke Tests   (ACC-001–ACC-006)
│   └── section_i_to_o.py    ← TTFT / OTPS / Cache / Rate Limit / SLA / RTO / Load
├── reports/                 ← JSON reports written here (auto-created)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Setup

### 1. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```env
EVAL_ENDPOINT_URL=https://your-endpoint/v1
EVAL_API_KEY=your-api-key-here
EVAL_MODEL=kimi-k2
EVAL_TIMEOUT=120
```

---

## Running — Docker (recommended)

Docker ensures a consistent environment across machines. Reports are saved to `./reports/` on your host.

```bash
# Build the image
docker compose build

# Run all sections (A–H, K–O — no perf tests)
docker compose run eval

# Run specific sections only
docker compose run eval --sections A B C

# Include TTFT (I) and OTPS (J) performance tests
docker compose run eval --perf

# Full spec-compliant run (100 samples, 1000 EOS reps)
docker compose run eval --perf --perf-samples 100 --eos-runs 1000
```

---

## Running — Local Python

```bash
pip install -r requirements.txt

export EVAL_ENDPOINT_URL=https://your-endpoint/v1
export EVAL_API_KEY=your-api-key
export EVAL_MODEL=kimi-k2

python run.py                                               # all sections
python run.py --sections A B G                             # specific sections
python run.py --perf                                       # include TTFT + OTPS
python run.py --perf --perf-samples 100 --eos-runs 1000   # full spec
```

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--sections A B ...` | all | Sections to run |
| `--perf` | off | Enable TTFT (I) and OTPS (J) tests |
| `--perf-samples N` | 20 | Samples per TTFT/OTPS bucket (spec = 100) |
| `--eos-runs N` | 20 | EOS test repetitions (spec = 1000) |

---

## Sections & Requirements

| Section | Name | Requirements | Perf flag? |
|---------|------|-------------|-----------|
| A | Thinking Mode | TM-001–TM-005 | No |
| B | Parameter Defaults | PD-001–PD-012 | No |
| C | System Prompt Injection | SP-001–SP-004 | No |
| D | Interleaved Thinking | IT-001–IT-007 | No |
| E | EOS / Special Token | ST-001–ST-007 | No |
| F | Image Input | IM-001–IM-011 | No |
| G | Tool Calling | TC-001–TC-010 | No |
| H | Accuracy Smoke Tests | ACC-001–ACC-006 | No |
| I | TTFT Performance | TTFT-001–TTFT-011 | **Yes** |
| J | OTPS Performance | OTPS-001–OTPS-002 | **Yes** |
| K | Cache Behavior | CACHE-001–CACHE-011 | No |
| L | Rate Limiting | RL-001–RL-004 | No |
| M | SLA Availability | SLA-001–SLA-008 | No |
| N | RTO Observability | RTO-001–RTO-003 | No |
| O | Load Smoke Test | LOAD-001–LOAD-004 | No |

---

## Official Accuracy Targets (Section H / full benchmark)

| Benchmark | Think Mode | Non-Think Mode | Tolerance |
|-----------|-----------|----------------|-----------|
| OCRBench | 91% | 92% | ±2% |
| AIME 2025 | 98.4% | 70.5% | ±2% |
| MMMU Pro Vision | 78.8% | 74.9% | ±2% |

> Section H runs smoke tests only. Full benchmark evaluation against official datasets is a future stage.

---

## Output

Each run writes a timestamped JSON report to `./reports/`:

```
reports/eval_20250514_120000.json
```

Fields: `run_at`, `meta`, `pass`, `fail`, `results[]`

---

## Extending for Future Stages

Each section file is independent. To add tests:
- **New tool variant** → edit `sections/section_g.py`, add `record(...)` calls
- **Full OCRBench dataset** → edit `sections/section_h.py`, add dataset loader
- **Async load testing** → edit `sections/section_i_to_o.py`, replace threading with asyncio

No other files need to change.
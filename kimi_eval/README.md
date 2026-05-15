# kimi-k2.6 Endpoint Evaluation

Full evaluation suite for a deployed kimi-k2.6 inference endpoint.
Covers Stages 1–5: compliance, performance, and accuracy benchmarking.

---

## Structure

```
kimi_eval/
├── run.py                    ← Stages 1–4: compliance + performance (sections A–O)
├── run_benchmarks.py         ← Stage 5: accuracy benchmarks
├── report.py                 ← Detailed failure report generator
│
├── core/
│   ├── common.py             ← HTTP client, record(), report helpers
│   └── bench_common.py       ← Benchmark scoring, CI, answer extraction
│
├── sections/                 ← One file per requirement section (A–O)
│   ├── section_a.py          ← Thinking Mode
│   ├── section_b.py          ← Parameter Defaults
│   ├── section_c.py          ← System Prompt Injection
│   ├── section_d.py          ← Interleaved Thinking
│   ├── section_e.py          ← EOS / Special Token
│   ├── section_f.py          ← Image Input
│   ├── section_g.py          ← Tool Calling
│   ├── section_h.py          ← Accuracy Smoke Tests
│   └── section_i_to_o.py     ← TTFT / OTPS / Cache / Rate Limit / SLA / RTO / Load
│
├── benchmarks/               ← Stage 5 benchmark runners
│   ├── run_aime.py           ← AIME 2025 (text-only, works now)
│   ├── run_ocrbench.py       ← OCRBench (needs image support)
│   └── run_mmmu.py           ← MMMU Pro (needs image support)
│
├── datasets/
│   └── aime2025.json         ← Fill in official AIME 2025 problems + answers
│
├── reports/                  ← All JSON reports written here
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Setup

```bash
cp env.example .env
# Edit .env — fill in EVAL_ENDPOINT_URL, EVAL_API_KEY, EVAL_MODEL
pip install -r requirements.txt
```

---

## Running

### Stages 1–4: Compliance + Performance

```bash
# All sections (A–H, K–O — no perf)
python run.py

# Specific sections
python run.py --sections A B D G

# Include TTFT + OTPS performance tests
python run.py --perf --perf-samples 30

# Full spec-compliant (100 TTFT/OTPS samples, 1000 EOS reps)
python run.py --perf --perf-samples 100 --eos-runs 1000
```

### Generate Failure Report (after any run.py run)

```bash
python report.py \
  --report reports/eval_YYYYMMDD_HHMMSS.json \
  --out reports/failure_report.md
```

### Stage 5: Accuracy Benchmarks

```bash
# AIME 2025 — text-only, works immediately
python run_benchmarks.py --benchmark aime

# AIME with 3-pass majority vote (spec-grade)
python run_benchmarks.py --benchmark aime --passes 3

# With your own official AIME 2025 dataset file
python run_benchmarks.py --benchmark aime --dataset datasets/aime2025.json

# Dev smoke run (50 samples per benchmark)
python run_benchmarks.py --limit 50

# Think mode only
python run_benchmarks.py --benchmark aime --mode think

# Full run — all benchmarks, both modes (OCRBench/MMMU need image support first)
python run_benchmarks.py
```

---

## Official Accuracy Targets (Stage 1 Spec, ±2% tolerance)

| Benchmark       | Think Mode | Non-Think Mode | Floor (think) | Floor (non-think) |
|-----------------|-----------|----------------|--------------|-------------------|
| OCRBench        | 91%       | 92%            | 89%          | 90%               |
| AIME 2025       | 98.4%     | 70.5%          | 96.4%        | 68.5%             |
| MMMU Pro Vision | 78.8%     | 74.9%          | 76.8%        | 72.9%             |

Any delta > ±2% = **service considered unavailable** per spec.

---

## AIME 2025 Dataset

Fill in `datasets/aime2025.json` with the official AIME 2025 problems.
The built-in problems are representative placeholders — use official
AMC/AIME 2025 problems for spec-compliant results.

Format:
```json
[
  {
    "id": "2025_I_01",
    "source": "AIME_2025_I",
    "problem": "Full problem text here...",
    "answer": 42
  }
]
```

---

## Stage Roadmap

| Stage | What | Command |
|-------|------|---------|
| 1–4 | Compliance + Performance | `python run.py --perf` |
| 4b | Failure report | `python report.py --report reports/...` |
| **5** | **Accuracy benchmarks** | `python run_benchmarks.py` |
| 6 | 1000-run EOS test | `python run.py --sections E --eos-runs 1000` |
| 7 | SLA stress test | `python run.py --sections M --perf` |
| 8 | Final audit report | `python report.py` |

---

## Docker

```bash
docker compose build
docker compose run eval                          # run.py all sections
docker compose run eval --perf                   # include TTFT/OTPS
```

For Stage 5 in Docker, add to docker-compose.yml:
```yaml
command: python run_benchmarks.py --benchmark aime
```

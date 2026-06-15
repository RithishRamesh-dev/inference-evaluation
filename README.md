# Crest by DigitalOcean

**Crest** is an inference benchmarking and evaluation platform for OpenAI-compatible endpoints. It lets you run standardized benchmarks, probe endpoints, compare models side-by-side, track costs, and continuously monitor model health — all from a single interface.

Live at: `https://inference-bench-omltx.ondigitalocean.app`

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS + Recharts |
| Backend | FastAPI (Python 3.11) + pymongo |
| Database | MongoDB (DigitalOcean Managed Cluster) |
| Deployment | DigitalOcean App Platform (multi-stage Docker) |

---

## Features

### Home
The landing page gives a live overview of your evaluation activity — total models, runs, benchmarks seeded, and average score. Below the stats, feature cards link to every section of the platform. Recent evaluations are listed with status and score at a glance.

---

### New Evaluation (`/new`)
Run benchmark suites against any model in your catalog.

**How it works:**
1. Pick a model from your catalog (Step 1)
2. Select one or more benchmark suites — filter by category (Reasoning, Coding, Math, Safety, etc.) or use the Recommended set (Step 2)
3. Configure run parameters: Full / Sample mode, sample count, batch size, temperature, max tokens, thinking mode (Step 3)
4. Submit — the run is queued and executed asynchronously with live progress streaming

Benchmark suites include MMLU, HumanEval, GSM8K, HellaSwag, ARC, TruthfulQA, MT-Bench, BBH, and 40+ others powered by EvalScope.

---

### History (`/dashboard`)
Lists all evaluation runs with status, score, model name, and timestamps. Shows active runs with a live pulse indicator. Includes a "Best Scores" leaderboard (highest score per benchmark across all completed runs) and a regression alert panel for score drops.

---

### Eval Progress (`/progress/:runId`)
Live view of a running evaluation via Server-Sent Events (SSE). Shows:
- Real-time progress bar with % complete and ETA
- Per-benchmark status as each suite completes
- Live score updates

Automatically redirects to the results page when the run finishes.

---

### Eval Results (`/results/:runId`)
Detailed results for a completed run:
- Overall score, wall time, benchmark breakdown table
- Per-benchmark score, samples scored, error rate, avg latency, token counts
- Sample-level outputs (question, expected answer, model output, correctness)
- LLM-as-Judge scoring panel (qualitative evaluation across configurable dimensions)
- Export options: JSON, CSV, Markdown, HTML
- Notes/annotations per run
- Smart recommendations (which benchmarks to add based on gaps)

---

### Compare (`/compare`)
Select two or more completed runs and compare them side-by-side:
- Benchmark score diff table (color-coded improvements/regressions)
- Radar chart across benchmark categories
- Token usage and latency comparison

---

### Model Catalog (`/models`)
Manage all your inference endpoints.

**Per model:**
- Name, provider, endpoint URL, model ID, API key (encrypted with Fernet)
- Capability flags: vision, tool calling, structured output, reasoning, multimodal
- Custom headers support
- **Connection test** — live latency check
- **Stress test** — configurable concurrency ramp (1→2→4→8 concurrent requests), P50/P90/P99 latency, throughput (tokens/sec), error rate
- **Validate** — run the full 35-check validation suite (see Probe Endpoint below)

---

### Intelligence (`/intelligence`)
Live endpoint intelligence dashboard:
- Per-model status cards showing real-time latency (probed on page load), online/offline status, best eval score, and capability summary
- **Benchmark Comparison Matrix** — models as columns, benchmarks as rows, best scores filled in (color-coded green/yellow/red)

---

### A/B Tests (`/ab-tests`)
Run the same benchmark set against multiple models simultaneously.

**How it works:**
1. Create an A/B test: give it a name, select 2–4 models, choose benchmark suites, set sample count
2. Crest creates one EvaluationRun per model and starts all of them in parallel
3. View results: individual run links, per-benchmark winner table

Useful for head-to-head comparisons — e.g. "GPT-4o vs Claude 3.5 Sonnet on coding benchmarks."

---

### Probe Endpoint (`/probe`)
Test any OpenAI-compatible endpoint without adding it to the catalog.

**Quick Probe (5 checks):** connectivity, basic completion, usage object, streaming, function calling

**Full Suite (35+ checks):** covers all of the above plus:
- Structured output (JSON mode, JSON schema)
- Vision / multimodal
- Long context, context following
- Reasoning / thinking tokens
- Token counting accuracy
- Rate limit / error handling behavior
- Hallucination resistance (famous facts, fabrication detection, consistency)
- Prompt injection resistance
- Sensitive data refusal

Results show pass/warn/fail per check with latency, message, and raw detail. Probe history is saved and shareable via link.

---

### Playground (`/playground`)
Interactive prompt testing environment:
- Multi-turn conversation builder
- Parameter controls: temperature, max_tokens, top_p, seed, stop sequences, JSON mode
- **Batch run**: send the same prompt N times and see consistency score, latency variance, token variance
- Saved templates: load from library or save your own
- Cost estimate per run

---

### Custom Datasets (`/datasets`)
Upload or create custom test sets to use as benchmark input.

- Create a dataset with name, description, and task type (QA, classification, generation, etc.)
- Add items: question + expected answer + optional context
- Export as JSON or CSV
- Use datasets in evaluations (select during New Evaluation → Step 2)

---

### Live Monitor (`/monitor`)
Continuous health monitoring for your models.

- Configure check interval (5–60 min), which checks to run, and alert-on-fail
- Monitor results timeline with pass/fail counts and avg latency per check run
- Uptime percentages: 24h, 7d, 30d
- Incident list with start/end times and duration

The `crest-monitor` background thread (runs every 60s) executes all enabled monitor configs automatically.

---

### Schedules (`/schedules`)
Automate recurring evaluations on a cron schedule.

- Set a cron expression (e.g. `0 2 * * *` = 2 AM daily) with human-readable preview
- Pick model + benchmarks + eval config
- Optional notification email
- Enable/disable without deleting
- Webhook keys for CI/CD integration: `POST /api/webhooks/trigger` with `X-Webhook-Key` header triggers an immediate eval run

The `crest-scheduler` thread (runs every 60s) checks for due schedules and queues eval runs automatically.

---

### Alerts (`/alerts`)
Automatic regression detection. When a completed evaluation scores more than a configurable threshold below a previous run on the same benchmark, an alert is created.

- Unacknowledged alerts shown on Dashboard and Alerts page
- Shows delta, previous score → current score, and links to the regression run
- Dismiss (acknowledge) individually

---

### Cost Analytics (`/cost`)
Track token spending across all evaluations.

- Total cost for a configurable time window (7d / 30d / 90d / all time)
- Cost breakdown by model (bar chart)
- Daily cost trend (line chart)
- Manage pricing rates per model: input tokens, output tokens, reasoning tokens (per 1K)

---

### Integrations (`/integrations`)
Export and CI/CD integration tools:
- **Python script** export: a ready-to-run Python script that runs validation checks against any model
- **GitHub Actions workflow** export: drop-in `.github/workflows/` YAML that runs validation in CI
- Webhook key management for triggering evaluations from external pipelines

---

## Deployment

### Local Development
```bash
# Backend
cd inference-bench/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd inference-bench/frontend
npm install
npm run dev
```

Set environment variables:
```
MONGODB_URI=<your mongodb uri>
ENCRYPTION_KEY=<fernet key>
API_KEY=<your api key>
```

### DigitalOcean App Platform
The app uses a multi-stage Dockerfile:
1. Stage 1 (node:20-slim): builds the React frontend with `npm run build`
2. Stage 2 (python:3.11-slim): installs Python deps, copies built frontend into `/app/static`, starts uvicorn

The FastAPI backend serves the React SPA from `/app/static` via a catch-all route handler, so all React Router paths work correctly.

To deploy a new build:
```bash
git push origin fix/dockerfile-path
doctl apps create-deployment <app-id>
```

---

## API Authentication

All `/api/*` routes require the header:
```
X-API-Key: <your api key>
```

The frontend reads `VITE_API_KEY` from the environment (set in DigitalOcean App Platform → Environment Variables).

---

## Background Threads

| Thread | Interval | Purpose |
|--------|----------|---------|
| `crest-scheduler` | 60s | Checks for due scheduled evaluations and queues runs |
| `crest-monitor` | 60s | Runs enabled monitor configs and records results |
| `crest-load-profiler` | 300s | Samples all model latencies to build 7×24 load heatmaps |

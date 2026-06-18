# Crest by DigitalOcean

**Crest** is a full-stack inference benchmarking and evaluation platform built for teams running OpenAI-compatible models. It provides everything needed to measure model quality, track performance over time, monitor endpoint health, control costs, and integrate evaluation into automated pipelines — all from a single interface deployed on DigitalOcean.

> Live at: `https://inference-bench-omltx.ondigitalocean.app`

---

## What is Crest?

When you deploy or adopt an inference model — whether it's a hosted API, a self-hosted open-weight model, or a fine-tuned checkpoint — you need answers to several questions:

- **Does it work correctly?** Can it stream, call functions, return structured output, handle long context?
- **How good is it?** How does it score on reasoning, coding, math, and general knowledge benchmarks?
- **How does it compare?** Is model A better than model B on the tasks I care about?
- **Is it staying healthy?** Is it still responding? Has quality regressed since last week?
- **What does it cost?** How many tokens am I spending per evaluation, and what does that translate to in dollars?

Crest answers all of these. You point it at any OpenAI-compatible endpoint, and it handles the rest — probing capabilities, running benchmark suites, tracking scores over time, alerting on regressions, and giving you the data to make informed decisions about which models to use and when.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS + Recharts |
| Backend | FastAPI (Python 3.11) |
| Database | MongoDB (DigitalOcean Managed Cluster) |
| Eval Engine | EvalScope (with mock fallback) |
| Deployment | DigitalOcean App Platform — multi-stage Docker build |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  React SPA (Vite + TypeScript)                          │
│  Served from FastAPI /static catch-all route            │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP + SSE  (X-API-Key header)
┌────────────────────▼────────────────────────────────────┐
│  FastAPI Backend  (Python 3.11)                         │
│                                                         │
│  Routers: models, benchmarks, evaluations, probe,       │
│  playground, judge, datasets, schedules, webhooks,      │
│  monitors, cost, ab_tests, templates, load_profile      │
│                                                         │
│  Background threads:                                    │
│  ├── crest-scheduler   (60s)  — scheduled eval runs     │
│  ├── crest-monitor     (60s)  — health check polling    │
│  └── crest-load-profiler (5m) — latency heatmap sampling│
└────────────────────┬────────────────────────────────────┘
                     │ pymongo (sync)
┌────────────────────▼────────────────────────────────────┐
│  MongoDB Atlas / DigitalOcean Managed MongoDB           │
│  Collections: models, evaluation_runs, run_benchmarks,  │
│  sample_outputs, benchmark_suites, datasets, schedules, │
│  monitors, probe_history, ab_test_runs, load_samples,   │
│  eval_templates, benchmark_relationships, ...           │
└─────────────────────────────────────────────────────────┘
```

Evaluation runs are executed asynchronously via a `ThreadPoolExecutor` (4 workers). Progress is streamed to the frontend over Server-Sent Events (SSE) in real time.

---

## Feature Reference

### Home (`/`)

The landing page. Provides an at-a-glance view of your platform activity:

- **Live stats**: total models configured, evaluations run, benchmark suites seeded, and average score across all completed runs
- **Feature grid**: cards linking to every section with a one-line description of what each does
- **Recent evaluations**: the last 3 runs with model name, status badge, and score — click any to go straight to results

Use this as your starting point when you open the platform.

---

### Model Catalog (`/models`)

Central registry of all inference endpoints you want to evaluate. Each entry represents one model at one endpoint.

**What you configure per model:**
- Display name and provider label
- Endpoint URL (the base URL for OpenAI-compatible API calls, e.g. `https://api.openai.com/v1`)
- Model ID (passed as the `model` field in API requests, e.g. `gpt-4o` or `moonshotai/Kimi-K2.6`)
- API key — stored encrypted using Fernet symmetric encryption, never returned in plaintext after saving
- Capability flags: Vision, Tool Calling, Structured Output, Reasoning/Thinking, Multimodal
- Reasoning configuration: format, enable/disable parameter names (for models like Claude that use `thinking` blocks)
- Custom HTTP headers (e.g. for enterprise proxies or versioned APIs)

**Actions per model:**

**Connection Test** — sends a minimal completion request and reports latency. Useful to confirm credentials and network access before running a full evaluation.

**Stress Test** — ramps up concurrent requests across configurable concurrency levels (default: 1, 2, 4, 8). For each level it measures:
- P50 / P90 / P95 / P99 latency
- Time to first token (TTFT)
- Throughput in requests/sec and tokens/sec
- Error rate and timeout rate

Use stress tests to understand how a model behaves under load, find the concurrency ceiling before errors appear, and compare throughput between endpoints.

**Validate** — runs the full 35-check validation suite against the model. See Probe Endpoint below for the full check list. Useful after onboarding a new model to confirm all the capabilities you've flagged actually work.

---

### New Evaluation (`/new`)

A 5-step wizard for configuring and launching a benchmark evaluation run.

**Step 1 — Select Model**
Choose which model from your catalog to evaluate. Search by name. All configured models are shown with their provider, model ID, context length, and capability badges.

**Step 2 — Configure Endpoint**
Set reasoning/thinking options for models that support extended thinking. Options:
- *Default* — uses the model's normal behavior
- *Enabled* — activates thinking tokens (set effort: low / medium / high)
- *Disabled* — explicitly suppresses thinking tokens

You can also run a quick connection test here before proceeding.

**Step 3 — Select Benchmarks**
Filter by category (Math, Coding, Vision, Reasoning, Science, Tool Calling, Compliance) or search by name. Each benchmark card shows:
- Category label and display name
- Description of what the benchmark tests
- Sample count and primary metric
- Whether it requires Vision or Tool Calling (greyed out if the model doesn't support it)
- ★ Recommended tag for high-signal benchmarks

Available benchmark suites include: MMLU, MMLU-Pro, HumanEval, HumanEval+, MBPP, GSM8K, MATH, AIME, ARC-Challenge, HellaSwag, Winogrande, TruthfulQA, BoolQ, CommonsenseQA, NaturalQuestions, RACE, BBH (Big-Bench Hard), MT-Bench, AlpacaEval, IFEval, GPQA, MMMU, MathVista, OCRBench, SimpleQA, and more — 53 suites total.

**Step 4 — Configure Execution**
- **Run name**: optional label for finding this run in history
- **Evaluation scope**: *Sample Run* (random subset per benchmark, faster/cheaper) or *Full Benchmark* (complete dataset, definitive scores)
- **Sample count**: 10 / 25 / 50 / 100 or custom
- **Batch size**: concurrent API requests per benchmark (higher = faster, risks rate limits)
- **Timeout**: per-request timeout in seconds
- **Temperature / Max Tokens**: override model defaults if needed

**Step 5 — Review & Launch**
Summary of your configuration. Click Launch to submit — you'll be taken directly to the live progress view.

---

### Eval Progress (`/progress/:runId`)

Live monitoring view for a running evaluation. Updates in real time via Server-Sent Events (SSE):

- Progress bar showing overall % complete with estimated time remaining
- Per-benchmark status rows — each benchmark shows queued → running → completed/failed as it progresses
- Elapsed time counter
- Live overall score (updates as benchmarks complete)
- Cancel button — safely stops the run mid-execution

When the run completes (or fails), the page automatically redirects to the results view.

---

### Eval Results (`/results/:runId`)

Full results view for a completed evaluation run.

**Overview tab:**
- Overall score and benchmark breakdown (score, samples scored, avg latency, avg input/output tokens per benchmark)
- Radar chart of scores grouped by category (Reasoning, Coding, Math, etc.)
- Export buttons: JSON (raw data), CSV (spreadsheet-friendly), Markdown (for reports), HTML (rendered page)
- Smart recommendations — the system scores 7 rules (e.g. "no reasoning benchmark run", "high error rate on coding", "below-average on math") and suggests next steps

**Samples tab:**
Browse individual sample outputs per benchmark. For each question you can see:
- The input question
- The expected/reference answer
- What the model actually output
- Whether it was scored correct
- Individual score, latency, token counts, finish reason
- Reasoning content (for thinking-enabled runs)

Use this to understand *why* a model is scoring the way it is — not just the number.

**LLM-as-Judge tab:**
Run a secondary qualitative evaluation on the model's outputs using another model as the judge. Configure:
- Which judge model and configuration to use (multiple rubrics available: helpfulness, factual accuracy, code quality, instruction following)
- The judge scores each output across multiple dimensions with a reason for each score

This catches quality issues that automatic metrics miss — e.g. a response that is technically "correct" but poorly explained or unnecessarily verbose.

**Notes tab:**
Attach free-text annotations to any run. Notes can be pinned and categorized. Useful for recording why a run was done, what changed, or what the results mean for a decision.

---

### Compare (`/compare`)

Side-by-side comparison of two or more completed evaluation runs.

Select runs from the picker (up to 4). Once selected:

- **Score diff table**: every benchmark both runs have in common, with scores for each run and a delta column (green = improvement, red = regression)
- **Radar chart**: overlapping category-level radar for visual comparison across capability areas
- **Token & latency comparison**: avg input tokens, output tokens, and latency per benchmark across runs

Common use case: compare the same model before and after a fine-tune, or compare two different models on an identical benchmark set.

---

### Intelligence (`/intelligence`)

A live endpoint intelligence dashboard that gives you a real-time snapshot of all your models at once.

**Model status cards** — for each model in your catalog:
- Online/offline indicator (live latency check on page load)
- Current latency in milliseconds
- Best evaluation score achieved (across all completed runs)
- Context window size
- Capability summary (Vision / Tools / Reasoning)
- Quick links to validate or start a new evaluation

**Benchmark Comparison Matrix** — a table with benchmarks as rows and models as columns, filled with the best score each model has achieved on each benchmark. Color-coded: green (≥90%), yellow (≥70%), red (<70%), dash (never run). Use this to identify which model excels at which task type, and spot gaps where no model has been tested.

---

### A/B Tests (`/ab-tests`)

Run the same benchmark configuration against multiple models simultaneously, with a unified view of results.

**How to create an A/B test:**
1. Give the test a name (e.g. "GPT-4o vs Claude 3.5 — Coding Suite")
2. Select 2–4 models from your catalog
3. Choose the benchmark suites to run
4. Set the sample count

Crest creates one independent EvaluationRun per model and starts all of them in parallel. Once runs complete, you can view:
- Links to individual run results for each model
- Status of each run

Use A/B tests to make apples-to-apples comparisons under controlled conditions — same prompts, same sample count, same evaluation logic — so differences in scores reflect the model, not the setup.

---

### Probe Endpoint (`/probe`)

Test any OpenAI-compatible endpoint without adding it to the Model Catalog first. Useful for evaluating a new endpoint before committing to it, or for one-off checks.

Enter the endpoint URL, API key, and model ID. Choose:

**Quick Probe (5 checks):**
1. `connectivity` — can we reach the endpoint at all?
2. `basic_completion` — does a simple chat completion return a non-empty response?
3. `usage_object` — does the response include a `usage` object with token counts?
4. `streaming_basic` — does streaming mode (`stream: true`) work correctly?
5. `function_calling` — does the model correctly call a defined tool?

**Full Suite (35+ checks)** — everything in Quick Probe plus:
- JSON mode (unstructured)
- JSON schema mode (structured output)
- Vision / image input
- Long context (near context limit)
- Context window following (does the model use information from earlier in the context?)
- System prompt adherence
- Reasoning / thinking token support
- Token count accuracy (does reported usage match actual?)
- Temperature sensitivity (does output vary with temperature?)
- Stop sequence handling
- Max token truncation behavior
- Rate limit / error handling (does the endpoint return proper error codes?)
- Retry behavior under 429 responses
- **Hallucination resistance** — famous facts (does it state false things about known entities?), fabrication detection (does it make up citations?), consistency (does it give the same answer to rephrased questions?)
- **Prompt injection resistance** — does the model follow injected instructions that contradict the system prompt?
- **Sensitive data refusal** — does the model decline requests to generate PII, credentials, or harmful content?

Each check returns: `pass` / `warn` / `fail` / `skip`, latency in ms, a human-readable message, and raw JSON detail for debugging.

Results are saved in probe history and each probe session gets a shareable link.

---

### Playground (`/playground`)

An interactive prompt editor for experimenting with a model before or after running a formal evaluation.

**Conversation builder:**
- Add system prompt, user messages, and assistant turns
- Multi-turn conversations supported

**Generation parameters:**
- Temperature (0–2)
- Max tokens
- Top-p
- Seed (for reproducibility)
- Stop sequences
- Response format: plain text, JSON mode, or JSON schema (paste your schema)
- Thinking mode toggle (for reasoning models)

**Single run:**
Submit the conversation and see the response with token counts, latency, and cost estimate.

**Batch run:**
Send the same conversation N times (default 5). Useful for measuring:
- **Consistency score** — how similar are the responses across runs? (0–100%)
- **Latency variance** — is the endpoint stable or highly variable?
- **Token variance** — is output length consistent or wildly different per run?

**Templates:**
Save any conversation + parameter configuration as a named template. Load templates from the library to quickly set up common test scenarios (e.g. "Code review prompt", "Translation test", "Instruction following eval").

---

### Custom Datasets (`/datasets`)

Create and manage custom test sets that can be used as benchmark input instead of (or in addition to) standard benchmark suites.

**Creating a dataset:**
- Name, description, and task type (QA, Classification, Generation, Code)
- Add items one by one: question/prompt + expected answer + optional context
- Or import in bulk via tab-separated format: `question\tanswer` (one per line)
- Or upload a `.csv` or `.json` file

**Using datasets in evaluations:**
Select a custom dataset in Step 3 of the New Evaluation wizard instead of a standard benchmark suite. Crest will use your questions as prompts and score the model's answers against your expected outputs.

**Exporting:**
Download any dataset as CSV or JSON for use in other tools.

---

### Live Monitor (`/monitor`)

Continuous automated health monitoring for any model in your catalog.

**Setting up a monitor:**
- Choose a model
- Set check interval: 5 / 15 / 30 / 60 minutes
- Choose which checks to run (subset of the probe suite)
- Enable alert-on-fail

Once created, the `crest-monitor` background thread polls every 60 seconds, finds all monitors whose next check is due, runs the configured checks against each model, and records the result.

**Per-monitor dashboard:**
- **Status indicator**: healthy / degraded / down with color-coded dot
- **24h status timeline**: a horizontal bar chart showing the status at each check slot over the past 24 hours — green healthy, yellow degraded, red down, gray no data
- **Uptime stats**: percentage uptime over 24h, 7 days, and 30 days
- **Recent checks table**: timestamp, pass count, fail count, avg latency for each check run
- **Incident log**: list of downtime incidents with start time, end time, and duration

Pause/resume individual monitors without deleting them.

---

### Schedules (`/schedules`)

Automate recurring evaluations to run on a defined schedule without manual intervention.

**Creating a schedule:**
- Select model and benchmark suites
- Set a cron expression (e.g. `0 2 * * *` = 2:00 AM every day, `0 9 * * 1` = 9:00 AM every Monday)
- Preset options: Daily 9am, Weekly Monday, Biweekly, Monthly 1st
- Human-readable preview of the cron expression shown live as you type
- Optional notification email
- Configure eval scope and sample count

**How it works:**
The `crest-scheduler` background thread runs every 60 seconds, compares the current time against each schedule's next_run_at, queues any due runs, and updates next_run_at using the cron expression.

**CI/CD integration via webhooks:**
Generate a webhook key (a signed secret) and use it to trigger evaluation runs from any CI/CD pipeline:
```
POST /api/webhooks/trigger
X-Webhook-Key: whk_<your key>
Content-Type: application/json

{ "model_id": "...", "benchmark_ids": ["..."], "eval_scope": "sample" }
```

Use this to automatically run quality checks on every model deployment, before promoting a new checkpoint, or as a step in a release gate.

---

### Alerts (`/alerts`)

Automatic regression detection. Every time a benchmark evaluation completes, Crest compares the new score against the previous score for the same benchmark on the same model. If the delta exceeds a threshold, a regression alert is created.

**Alert details:**
- Which benchmark regressed
- Previous score → current score and the exact delta
- Link to the regression run to drill into what changed
- Timestamp

**Managing alerts:**
- Unacknowledged alerts appear as a warning banner on the Dashboard
- Acknowledge (dismiss) alerts individually once you've reviewed them
- Toggle to view all historical alerts including acknowledged ones

Alerts catch silent degradation — situations where a model update or infrastructure change broke something that you wouldn't notice without automated tracking.

---

### Cost Analytics (`/cost`)

Track token usage and estimated spending across all evaluations.

**Overview panel:**
- Total estimated cost for a selectable time window (7 days / 30 days / 90 days / all time)
- Cost breakdown by model (bar chart) — which models are consuming the most budget
- Daily cost trend (line chart) — spending over time

**Pricing configuration:**
Crest estimates costs using per-model pricing rates you configure:
- Input tokens price (per 1,000 tokens)
- Output tokens price (per 1,000 tokens)
- Reasoning tokens price (per 1,000 tokens, for thinking-enabled runs)
- Currency

Configure pricing for each model and Crest will automatically calculate estimated costs for all past and future evaluation runs based on recorded token counts.

---

### Integrations (`/integrations`)

Tools for integrating Crest validation into external systems.

**Python script export:**
Download a ready-to-run Python script that runs the Crest probe validation checks directly against any model endpoint — no Crest server required. Use it in local development, in containerized environments, or as a standalone QA script.

**GitHub Actions workflow export:**
Download a complete `.github/workflows/validate-model.yml` YAML file. Drop it into any repository to run model validation checks on every push, pull request, or release. The workflow calls your Crest instance (or runs standalone) and fails the CI job if the model fails critical checks.

**Webhook keys:**
Generate named webhook keys for programmatic access. Each key is a signed secret that can be used to trigger evaluation runs via the `/api/webhooks/trigger` endpoint from any external system — deployment pipelines, Slack bots, monitoring systems, or custom scripts.

---

## API Reference

All API routes are prefixed `/api/` and require:
```
X-API-Key: <your api key>
```

The frontend reads `VITE_API_KEY` from the environment. The backend validates it against the `API_KEY` environment variable.

### Core endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/models` | List all models |
| `POST` | `/api/models` | Add a model |
| `PUT` | `/api/models/:id` | Update a model |
| `DELETE` | `/api/models/:id` | Delete a model |
| `POST` | `/api/models/:id/test` | Live connection test |
| `GET` | `/api/benchmarks` | List benchmark suites |
| `POST` | `/api/evaluations` | Create an evaluation run |
| `POST` | `/api/evaluations/:id/start` | Start a queued run |
| `GET` | `/api/evaluations/:id/stream` | SSE progress stream |
| `GET` | `/api/evaluations/:id/results` | Full results |
| `POST` | `/api/probe` | Probe any endpoint |
| `GET` | `/api/ab-tests` | List A/B tests |
| `POST` | `/api/ab-tests` | Create an A/B test |
| `GET` | `/api/templates` | List eval templates |
| `POST` | `/api/templates/:id/launch` | Launch a template |
| `GET` | `/api/search` | Global search |
| `GET` | `/api/health` | Health check with DB ping and uptime |

---

## Deployment

### Local Development

**Backend:**
```bash
cd inference-bench/backend
pip install -r requirements.txt
export MONGODB_URI="mongodb+srv://..."
export ENCRYPTION_KEY="<fernet key>"  # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export API_KEY="your-api-key"
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd inference-bench/frontend
npm install
echo "VITE_API_KEY=your-api-key" > .env.local
npm run dev
```

The frontend dev server proxies `/api/*` to `http://localhost:8000` via the Vite config.

### DigitalOcean App Platform

The project uses a multi-stage Dockerfile:

**Stage 1 (node:20-slim):** installs frontend dependencies and runs `npm run build`, producing a compiled static bundle in `frontend/dist/`

**Stage 2 (python:3.11-slim):** installs Python dependencies, copies the frontend build into `/app/static`, and starts the uvicorn server

FastAPI serves the React SPA via a catch-all route:
```python
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    # serves static files directly, falls back to index.html for SPA routes
```

This means all React Router paths (`/dashboard`, `/results/:id`, etc.) are served correctly without a separate web server.

**Environment variables** (set in DigitalOcean App Platform):
```
MONGODB_URI      — MongoDB connection string
ENCRYPTION_KEY   — Fernet key for API key encryption
API_KEY          — Static API key for frontend authentication
VITE_API_KEY     — Same key, injected into the React build
```

**Triggering a new deployment:**
```bash
git push origin fix/dockerfile-path
doctl apps create-deployment <app-id>
```

---

## Background Threads

Three daemon threads start automatically when the server boots:

| Thread | Interval | What it does |
|--------|----------|--------------|
| `crest-scheduler` | 60s | Finds scheduled evaluations due to run, queues them via the eval worker |
| `crest-monitor` | 60s | Finds monitors whose next check is due, runs the configured probe checks, records results, updates uptime stats |
| `crest-load-profiler` | 5 min | Sends a lightweight ping to every model endpoint, records latency and availability into `load_samples`, which are aggregated into a 7×24 heatmap (day-of-week × hour-of-day) |

All three threads are daemon threads — they terminate when the main server process exits and do not block shutdown.

---

## Project Structure

```
inference-evaluation/
├── inference-bench/
│   ├── backend/
│   │   ├── main.py           — FastAPI app, routes, SPA catch-all
│   │   ├── worker.py         — Eval executor, scheduler, monitor, load profiler
│   │   ├── database.py       — MongoDB init, indexes
│   │   ├── schemas.py        — Pydantic v2 request/response models
│   │   ├── seeds.py          — Benchmark suite seeding (53 suites)
│   │   ├── validation.py     — 35-check probe validation logic
│   │   └── routers/
│   │       ├── ab_tests.py   — A/B test CRUD and parallel run launch
│   │       ├── cost.py       — Token cost tracking and pricing
│   │       ├── datasets.py   — Custom dataset CRUD
│   │       ├── judge.py      — LLM-as-Judge evaluation
│   │       ├── load_profile.py — Load heatmap aggregation
│   │       ├── monitor.py    — Health monitor CRUD and results
│   │       ├── playground.py — Interactive prompt runner
│   │       ├── probe_history.py — Probe session storage
│   │       ├── schedules.py  — Scheduled eval CRUD
│   │       ├── templates.py  — Eval template CRUD
│   │       └── webhooks.py   — Webhook key management
│   ├── frontend/
│   │   ├── src/
│   │   │   ├── App.tsx       — Route definitions
│   │   │   ├── api.ts        — All API client methods
│   │   │   ├── types.ts      — TypeScript interfaces
│   │   │   ├── components/   — Shared UI components
│   │   │   └── pages/        — One file per route
│   │   ├── tailwind.config.js
│   │   └── package.json
│   └── Dockerfile            — Multi-stage build
└── README.md
```

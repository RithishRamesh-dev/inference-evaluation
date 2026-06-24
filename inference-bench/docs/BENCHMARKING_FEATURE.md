# Benchmarking Evaluation — Design & Implementation Plan

> Automate the manual GPU-benchmarking workflow (create droplet → SSH in → run an
> inference engine in Docker → run NVIDIA aiperf) entirely inside Crest.

---

## 1. Motivation

Today, benchmarking a model on different GPUs / inference engines is manual:

1. Create a DigitalOcean GPU droplet.
2. SSH into it.
3. Spin up a Docker container for the inference engine.
4. Run NVIDIA `aiperf` commands inside it.
5. Read the numbers off the terminal.

We want all of this driven from the Crest GUI, with results persisted to the
existing MongoDB and shown in dashboards.

---

## 2. How this fits the existing codebase

This feature is a third instance of patterns Crest already uses — we are not
inventing new infrastructure, only a thin orchestration layer.

| Concern | Existing pattern we reuse | Location |
|---|---|---|
| Long-running jobs | `ThreadPoolExecutor` + in-memory `progress_store` | `backend/worker.py` |
| Live progress to browser | Server-Sent Events (`EventSource`) | `backend/main.py` SSE endpoint, `frontend/.../EvalProgress.tsx` |
| Secrets at rest | Fernet encryption | `backend/encryption.py` |
| Feature API | one router file per feature, registered in `main.py` | `backend/routers/*.py` |
| List + detail screens | sidebar + detail panel | `frontend/.../Monitor.tsx` |
| Global history list | persistent list read from Mongo | `frontend/.../Dashboard.tsx` (`/dashboard`) |
| Resource-nested API client | `api.<resource>.<verb>()` | `frontend/src/api.ts` |
| Charts | Recharts | `frontend/.../RadarChart.tsx` |
| DO theme / styling | Tailwind tokens (`do-blue`, `do-navy`, …) | `frontend/tailwind.config.js` |

**The only genuinely new concept** is the orchestration layer: provisioning real
infrastructure and driving it over SSH. Every existing Crest feature only makes
HTTP calls to a model endpoint; this one creates and controls droplets.

The nav already contains an **empty "Benchmarking Evaluation" dropdown**
(`frontend/src/components/Layout.tsx`) — this feature fills it.

---

## 3. Settled design decisions

| Decision | Choice | Rationale |
|---|---|---|
| DO access | **DO REST API via `httpx`** (not `doctl`) | No new binary in the image, structured JSON, native async, fewer failure modes. `doctl` is just a wrapper over the same API. |
| Droplet control channel | **SSH** (`paramiko` / `asyncssh`) | docker pull/run/stop, health curl, log tail, and aiperf all run over one channel. |
| Where aiperf runs | **On the droplet, against `localhost`**, over SSH | Model endpoint never needs public exposure — no firewall/public-IP/auth on the served port. Backend health checks + log tail also go over SSH. |
| Recipe pre-fill | **Live fetch** of vLLM recipe YAML from GitHub at config time | Recipes change often. Cache briefly; fall back to per-engine defaults if missing/unreachable so a hiccup never blocks a deploy. |
| SSH key management | **Backend-managed, one keypair per droplet** | User never touches SSH. Public key registered with DO at create; private key stored Fernet-encrypted. Key auto-deleted on droplet destroy. |
| UI model | **Resource-oriented sections** (not a linear wizard) | Droplet, deployment, and benchmark run are long-lived and reusable; matches the rest of the app (list+detail). |
| Result persistence | aiperf results stored fully in Mongo, **decoupled from droplet lifecycle** | History survives droplet teardown; destroy-on-finish is safe because results are written before teardown. |

---

## 4. The two control channels

```
                 ┌──────────────────────────── Backend ────────────────────────────┐
  DO REST API ◄──┤ create droplet · poll status · destroy droplet · (de)register key │
   (httpx)       └──────────────────────────────────────────────────────────────────┘
                 ┌──────────────────────────── Backend ────────────────────────────┐
  SSH         ◄──┤ docker pull/run/stop · curl localhost/health · docker logs ·      │
   (paramiko)    │ run aiperf against localhost                                       │
                 └──────────────────────────────────────────────────────────────────┘
```

- **DO REST API** handles only create / destroy / status / SSH-key registration.
- **SSH** handles everything post-provision.

---

## 5. Resource hierarchy & lifecycles

```
Droplet  ──< Deployment (vLLM/SGLang recipe)  ──< Benchmark run (aiperf)
```

One-to-many at each level (foreign keys: `deployments.droplet_id`,
`aiperf_runs.deployment_id`). The reuse the user asked for falls straight out of
"list children of X" — no special logic.

Three **independent** lifecycles:

- **Droplet** — `create` / `destroy`. Destroy = DO API delete (the expensive one).
- **Deployment** — `deploy` (`docker run`) / `stop` (`docker stop && rm`).
  A GPU is fully consumed by one served model, so **one active deployment per
  droplet at a time, many over its life**. "Try a different recipe" = stop
  current → deploy new on the *same* droplet. `stop` frees the GPU but keeps the
  droplet (distinct from destroy).
- **Benchmark** — `run` / `view`. Many per deployment, cheap, non-destructive.

**Destroy is surfaced in three places:** (a) a "destroy droplet when benchmark
finishes" checkbox on a benchmark run, (b) a manual destroy per droplet, (c) the
Droplets tab as the safety net.

Suggested status enums:

- `gpu_droplets.status`: `provisioning → active → destroying → destroyed | failed`
- `deployments.status`: `pulling → starting → serving → stopped | failed`
- `aiperf_runs.status`: `queued → running → completed | failed`

---

## 6. Data model (new MongoDB collections)

No migration needed (Mongo). Mirror existing schema conventions: string `_id`,
`created_at` / `updated_at` datetimes, encrypted secrets as bytes.

### `gpu_droplets`
```
_id, name, region, size_slug (GPU size), image,
do_token_encrypted,            # Fernet
do_droplet_id,                 # numeric id from DO
ip,                            # public IP once active
ssh_public_key, ssh_private_key_encrypted, do_ssh_key_id,
status, status_detail,
hourly_price_usd,              # from DO size catalog, for cost display
created_at, destroyed_at
```

### `deployments`
```
_id, droplet_id (FK), engine ('vllm' | 'sglang'), model,
docker_image, recipe_source_url,
server_args,                   # dict {flag: value}, editable
port,                          # served port on the droplet
status, status_detail, health, # health = last /health result
log_tail,                      # recent docker logs
created_at, stopped_at
```

### `aiperf_runs`
```
_id, deployment_id (FK),
# tombstone copies so History survives droplet/deployment teardown:
droplet_snapshot,              # {size_slug, region, gpu}
deployment_snapshot,           # {engine, model, server_args}
profile,                       # dict of aiperf params (editable in GUI)
status, status_detail,
metrics,                       # {ttft, itl, throughput, p50, p90, p95, p99, ...}
raw_output,
destroy_on_finish,             # bool
created_at, completed_at
```

> `*_snapshot` fields are why History keeps working after a droplet is destroyed.

---

## 7. Backend changes

### New router files (registered in `main.py`, same shape as eval endpoints)
- `routers/droplets.py` — CRUD + `POST /{id}/destroy`, `GET /{id}/stream` (SSE provisioning progress).
- `routers/deployments.py` — list (filter by `droplet_id`) + `POST` deploy, `POST /{id}/stop`, `GET /{id}/logs`, `GET /{id}/health`, `GET /{id}/stream`.
- `routers/aiperf.py` — list (filter by `deployment_id`) + `POST` run, `GET /{id}`, `GET /{id}/stream`, and a global `GET /history`.
- `routers/recipes.py` — `GET /recipes/{model}` → live-fetch + parse vLLM recipe YAML → `{flag: value}`, cached, with engine-default fallback.

### New module: `orchestrator.py`
The only substantial new code. Functions:
- `create_droplet(cfg) -> droplet` — generate keypair, register public key (DO API), `POST /v2/droplets`, poll `GET /v2/droplets/{id}` until `active` + IP.
- `destroy_droplet(droplet)` — `DELETE` droplet, delete registered SSH key.
- `deploy_model(droplet, deployment)` — over SSH: `docker pull`, `docker run` the engine image with `server_args`, wait for serve, `curl localhost:<port>/health`.
- `stop_deployment(deployment)` — over SSH: `docker stop && rm`.
- `tail_logs(deployment)` — over SSH: `docker logs --tail`.
- `run_aiperf(deployment, profile)` — over SSH: run aiperf against `localhost:<port>`, capture + parse metrics.

### Reuse `worker.py`
Each long step (`create_droplet`, `deploy_model`, `run_aiperf`) becomes an
executor job that updates `progress_store` with events
(`droplet_provisioning`, `droplet_ready`, `image_pulled`, `model_serving`,
`health_ok`, `aiperf_running`, `done`, plus failures) — exactly like benchmarks
emit events today. The existing SSE endpoint streams it. For aiperf-with-destroy:
write results to Mongo first, *then* destroy.

### New dependencies (`requirements.txt`)
- `paramiko` (or `asyncssh`) — SSH.
- `pyyaml` — parse recipe YAML.
- (`httpx` already present for the DO REST API.)

### Config
- DO API token: entered per droplet in the GUI, stored Fernet-encrypted
  (matches how model API keys are handled). No new global env var required.

---

## 8. Frontend changes

### Nav — fill the empty dropdown (`components/Layout.tsx`)
```
Benchmarking Evaluation ▾
  Droplets        /benchmark/droplets
  Deployments     /benchmark/deployments
  Benchmarks      /benchmark/runs
  History         /benchmark/history
```
Add matching `ROUTE_LABELS` entries and routes in `App.tsx`. Consider a count
badge on Droplets so a forgotten (costly) droplet is visible from anywhere.

### Pages (sidebar+detail, à la `Monitor.tsx`)
1. **Droplets** (`/benchmark/droplets`) — list existing + "Create Droplet"
   (token, region, GPU size, name). Each card: GPU/region/IP, status,
   **running-since + estimated cost-to-date**, destroy button.
2. **Deployments** (`/benchmark/deployments`) — pick a droplet → see what has
   run on it → deploy a new recipe. Engine picker (vLLM/SGLang), model picker,
   and a **dynamic key/value editor for server args** seeded live from the
   recipe (add/remove/edit flags). Deploy, then tail logs + show health.
3. **Benchmarks** (`/benchmark/runs`) — pick a deployment → see its past aiperf
   runs → configure a new aiperf profile (form over profile params) + the
   **"destroy droplet when finished"** checkbox → run → stream progress.
4. **History** (`/benchmark/history`) — global, persistent list of *all* aiperf
   runs across every droplet/deployment, including destroyed ones (reads from
   Mongo only). Dashboards via Recharts: latency percentiles, throughput vs.
   concurrency, TTFT/ITL.

### `api.ts`
Add `api.droplets`, `api.deployments`, `api.aiperf`, `api.recipes` resource
blocks following the existing nested pattern, plus `streamUrl` helpers for SSE.

### `types.ts`
Add `GpuDroplet`, `Deployment`, `AiperfRun`, `Recipe`, and progress/event types.

---

## 9. Risks / things to get right

- **Cost & cleanup** — GPU droplets are expensive. Destroy-on-finish, manual
  destroy, and the Droplets safety-net tab with live cost are all required, not
  nice-to-have.
- **SSH + Docker fragility** — connection drops, slow image pulls, multi-minute
  model loads. Each step needs timeouts, retries, and a clear failure event.
- **`progress_store` is process-local** — a backend restart mid-provision loses
  stream state (the droplet keeps running). Acceptable for v1; reconcile by
  re-querying DO/SSH on reconnect later if needed.
- **Results before teardown** — always persist aiperf results to Mongo before
  destroying the droplet.

---

## 10. Suggested build order (de-risks the orchestration layer)

1. **Droplets** section end-to-end (create/list/destroy/cost) + DO REST + keypair mgmt.
2. **Deployments** section (SSH + docker run/stop + live recipe fetch + health/logs).
3. **Benchmarks** section (aiperf over SSH + metrics parse + destroy-on-finish).
4. **History** dashboards.

---

## 11. Claude Code implementation prompt

> Paste the block below to the agent. It assumes this doc is at
> `inference-bench/docs/BENCHMARKING_FEATURE.md`.

```
Implement the "Benchmarking Evaluation" feature described in
inference-bench/docs/BENCHMARKING_FEATURE.md. Read that doc fully first, then
read backend/worker.py, backend/main.py, backend/encryption.py, one existing
router (e.g. backend/routers/monitor.py), frontend/src/api.ts,
frontend/src/components/Layout.tsx, frontend/src/pages/Monitor.tsx,
frontend/src/pages/EvalProgress.tsx, and frontend/src/pages/NewEvaluation.tsx so
your code matches existing conventions exactly (string Mongo _ids, Fernet for
secrets, ThreadPoolExecutor + progress_store + SSE for long jobs, the
api.<resource>.<verb>() client pattern, Tailwind DO theme tokens).

Build it in this order, and STOP after each step for me to review before
continuing:

STEP 1 — Droplets (provisioning):
- backend/orchestrator.py with create_droplet/destroy_droplet using the DO REST
  API via httpx (NOT doctl): generate one SSH keypair per droplet, register the
  public key with DO, store the private key Fernet-encrypted, POST /v2/droplets,
  poll until active + IP. destroy_droplet deletes the droplet and the registered
  key.
- New collection gpu_droplets per the doc's schema. DO token entered per droplet,
  stored Fernet-encrypted.
- backend/routers/droplets.py: CRUD + POST /{id}/destroy + SSE progress stream,
  using worker.py's executor + progress_store. Register it in main.py.
- Frontend: /benchmark/droplets page (sidebar+detail like Monitor.tsx) with
  create form (token, region, GPU size, name), status, running-since +
  estimated cost-to-date, and destroy. Fill the empty "Benchmarking Evaluation"
  nav dropdown in Layout.tsx, add the route in App.tsx, add api.droplets and
  types. Add a count badge for live droplets.

STEP 2 — Deployments (serve a model):
- orchestrator.py: deploy_model (SSH: docker pull + docker run engine image with
  server_args, wait, curl localhost:<port>/health), stop_deployment (docker stop
  && rm), tail_logs. Use paramiko (add to requirements.txt).
- backend/routers/recipes.py: GET /recipes/{model} live-fetches and parses the
  vLLM recipe YAML from GitHub into {flag: value}, cached, with per-engine
  default fallback if missing/unreachable. Add pyyaml to requirements.txt.
- New collection deployments. backend/routers/deployments.py: list (filter by
  droplet_id), POST deploy, POST /{id}/stop, GET /{id}/logs, GET /{id}/health,
  SSE stream.
- Frontend: /benchmark/deployments page — pick a droplet, see its deployments,
  engine picker (vllm/sglang), model picker, a dynamic key/value editor for
  server args seeded from the recipe endpoint, deploy + live logs + health.

STEP 3 — Benchmarks (aiperf):
- orchestrator.py: run_aiperf (SSH: run aiperf against localhost:<port>, parse
  metrics ttft/itl/throughput/p50..p99).
- New collection aiperf_runs storing full results PLUS droplet/deployment
  snapshots so results survive teardown. Honor destroy_on_finish: persist
  results to Mongo BEFORE destroying.
- backend/routers/aiperf.py: list (filter by deployment_id), POST run, GET /{id},
  SSE stream, GET /history.
- Frontend: /benchmark/runs page — pick a deployment, see past runs, aiperf
  profile form + "destroy droplet when finished" checkbox, run + stream progress.

STEP 4 — History:
- Frontend: /benchmark/history page — global persistent list of all aiperf_runs
  (reads Mongo only, includes destroyed droplets) with Recharts dashboards:
  latency percentiles, throughput vs concurrency, TTFT/ITL.

Constraints: keep it simple, match existing patterns, no over-engineering. Each
long-running op must emit progress events and handle timeouts/failures with a
clear failure event. Always write benchmark results before any teardown.
```
```

---

*Generated as a planning artifact — no application code has been changed.*

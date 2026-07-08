"""All Pydantic v2 request/response schemas.

IDs are strings throughout (MongoDB ObjectId hex strings).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, field_serializer


# Datetime fields stored in MongoDB come back naive (pymongo tz_aware=False) even
# though they're UTC. Serialized as-is they'd carry no offset, and the browser
# would parse them as LOCAL time — skewing live runtimes/costs until a fixed
# end-time made the offset cancel out. This base serializes every timestamp as
# unambiguous UTC ("…Z") so every Out model is correct app-wide.
_TS_FIELDS = ("created_at", "updated_at", "started_at", "completed_at",
              "destroyed_at", "droplet_destroyed_at", "run_at", "sampled_at",
              "last_run_at", "next_run_at")


class UTCModel(BaseModel):
    @field_serializer(*_TS_FIELDS, when_used="json", check_fields=False)
    def _serialize_utc(self, v: Optional[datetime]):
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Models ────────────────────────────────────────────────────────────────────

class ModelCreate(UTCModel):
    name: str
    provider: str
    endpoint_url: str
    model_id: str
    api_key: str = ""
    context_length: Optional[int] = None
    supports_vision: bool = False
    supports_tool_calling: bool = False
    supports_structured_output: bool = False
    supports_reasoning: bool = False
    supports_multimodal: bool = False
    reasoning_format: Optional[str] = None
    reasoning_enable_param: Optional[str] = None
    reasoning_disable_param: Optional[str] = None
    custom_headers: str = "{}"
    is_custom: bool = True


class ModelUpdate(UTCModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    endpoint_url: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    context_length: Optional[int] = None
    supports_vision: Optional[bool] = None
    supports_tool_calling: Optional[bool] = None
    supports_structured_output: Optional[bool] = None
    supports_reasoning: Optional[bool] = None
    supports_multimodal: Optional[bool] = None
    reasoning_format: Optional[str] = None
    reasoning_enable_param: Optional[str] = None
    reasoning_disable_param: Optional[str] = None
    custom_headers: Optional[str] = None


class ModelOut(UTCModel):
    id: str
    name: str
    provider: str
    endpoint_url: str
    model_id: str
    context_length: Optional[int] = None
    supports_vision: bool = False
    supports_tool_calling: bool = False
    supports_structured_output: bool = False
    supports_reasoning: bool = False
    supports_multimodal: bool = False
    reasoning_format: Optional[str] = None
    reasoning_enable_param: Optional[str] = None
    reasoning_disable_param: Optional[str] = None
    custom_headers: str = "{}"
    is_custom: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConnectionTestOut(UTCModel):
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


# ── Benchmarks ────────────────────────────────────────────────────────────────

class BenchmarkOut(UTCModel):
    id: str
    name: str
    display_name: str
    category: str
    description: Optional[str] = None
    evalscope_id: str
    default_metric: str
    is_recommended: bool = False
    is_vision: bool = False
    requires_tools: bool = False
    total_samples: Optional[int] = None
    tags: str = ""
    evalscope_config: str = "{}"


class CategoryOut(UTCModel):
    category: str
    count: int


# ── Evaluations ───────────────────────────────────────────────────────────────

class EvaluationCreate(UTCModel):
    model_id: str                    # ObjectId string
    display_name: Optional[str] = None
    benchmark_ids: list[str]         # list of ObjectId strings
    eval_scope: str = "sample"
    sample_count: Optional[int] = None
    eval_batch_size: int = 8
    timeout_seconds: int = 120
    retry_count: int = 3
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    thinking_mode: Optional[str] = None
    reasoning_effort: Optional[str] = None


class RunBenchmarkOut(UTCModel):
    id: str
    run_id: str
    benchmark_suite_id: str
    suite_name: Optional[str] = None
    suite_display_name: Optional[str] = None
    suite_category: Optional[str] = None
    status: str = "pending"
    primary_score: Optional[float] = None
    subset_scores: str = "{}"
    samples_total: Optional[int] = None
    samples_scored: Optional[int] = None
    samples_errored: Optional[int] = None
    avg_latency_s: Optional[float] = None
    avg_input_tokens: Optional[float] = None
    avg_output_tokens: Optional[float] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class EvaluationOut(UTCModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    model_provider: Optional[str] = None
    display_name: Optional[str] = None
    eval_scope: str = "sample"
    sample_count: Optional[int] = None
    eval_batch_size: int = 8
    timeout_seconds: int = 120
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    thinking_mode: Optional[str] = None
    reasoning_effort: Optional[str] = None
    status: str = "queued"
    overall_score: Optional[float] = None
    total_benchmarks: int = 0
    passed_benchmarks: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    wall_time_seconds: Optional[int] = None
    created_at: Optional[datetime] = None
    run_benchmarks: list[RunBenchmarkOut] = []


class SampleOutputOut(UTCModel):
    id: str
    run_benchmark_id: str
    sample_index: int
    question: Optional[str] = None
    expected_answer: Optional[str] = None
    model_output: Optional[str] = None
    reasoning_content: Optional[str] = None
    is_correct: Optional[bool] = None
    score: Optional[float] = None
    finish_reason: Optional[str] = None
    latency_s: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None


# ── Notes ─────────────────────────────────────────────────────────────────────

class NoteCreate(UTCModel):
    content: str
    note_type: str = "general"
    is_pinned: bool = False


class NoteUpdate(UTCModel):
    content: Optional[str] = None
    note_type: Optional[str] = None
    is_pinned: Optional[bool] = None


class NoteOut(UTCModel):
    id: str
    run_id: str
    note_type: str = "general"
    content: str
    is_pinned: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationCheckResult(UTCModel):
    check_id: str
    name: str
    category: str
    status: str        # pass | fail | warn | skip
    latency_ms: float
    detail: dict[str, Any] = {}
    message: str


class ValidationRunOut(UTCModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    status: str        # running | completed | failed
    total_checks: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    skipped: int = 0
    checks: list[ValidationCheckResult] = []
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None


# ── Benchmark targets ─────────────────────────────────────────────────────────

class BenchmarkTargetOut(UTCModel):
    id: str
    benchmark_suite_id: str
    target_score: float
    target_label: str
    created_at: Optional[datetime] = None


# ── Stress test ───────────────────────────────────────────────────────────────

class StressTestCreate(UTCModel):
    concurrency_levels: list[int] = [1, 2, 4, 8, 16]
    requests_per_level: int = 10
    prompt_tokens: int = 128
    output_tokens: int = 256
    test_duration_seconds: int = 60


class StressLevelResult(UTCModel):
    concurrency: int
    requests_total: int
    requests_succeeded: int
    requests_failed: int
    avg_latency_ms: float
    p50_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    ttft_ms_avg: Optional[float] = None
    throughput_requests_per_second: float
    throughput_tokens_per_second: float
    total_output_tokens: int
    error_rate: float
    timeout_rate: float


class StressTestOut(UTCModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    status: str
    config: dict[str, Any] = {}
    results: list[StressLevelResult] = []
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── System info ───────────────────────────────────────────────────────────────

class SystemInfoOut(UTCModel):
    python_version: str
    database: str = "mongodb"
    benchmarks_seeded: int
    total_runs: int
    total_models: int
    evalscope_available: bool
    worker_threads: int = 4


# ── Probe (unauthenticated endpoint test) ─────────────────────────────────────

class ProbeRequest(UTCModel):
    endpoint_url: str
    api_key: str
    model_id: str
    checks: Optional[list[str]] = None   # None = run all


# ── Regression alert ──────────────────────────────────────────────────────────

class RegressionAlertOut(UTCModel):
    id: str
    run_id: str
    benchmark_suite_id: str
    benchmark_name: Optional[str] = None
    prev_score: float
    curr_score: float
    delta: float
    acknowledged: bool = False
    created_at: Optional[datetime] = None


# ── Playground ────────────────────────────────────────────────────────────────
class PlaygroundMessage(UTCModel):
    role: str  # user | assistant | system
    content: str

class PlaygroundParams(UTCModel):
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 1.0
    seed: Optional[int] = None
    stop: list[str] = []
    response_format: Optional[str] = None  # none | json_object | json_schema
    json_schema: Optional[str] = None
    thinking_mode: bool = False
    reasoning_effort: Optional[str] = None  # low | medium | high

class PlaygroundRunRequest(UTCModel):
    endpoint_url: str
    api_key: str
    model_id: str
    messages: list[PlaygroundMessage]
    params: PlaygroundParams = PlaygroundParams()
    system_prompt: Optional[str] = None

class PlaygroundRunResult(UTCModel):
    content: str
    reasoning_content: Optional[str] = None
    finish_reason: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: float = 0.0
    cost_estimate: Optional[float] = None
    error: Optional[str] = None

class PlaygroundBatchResult(UTCModel):
    results: list[PlaygroundRunResult]
    consistency_score: float  # 0-1
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    token_variance: float

class PlaygroundTemplateCreate(UTCModel):
    name: str
    description: str = ""
    messages: list[dict]  # [{role, content}]
    params: dict = {}
    system_prompt: str = ""

class PlaygroundTemplateOut(UTCModel):
    id: str
    name: str
    description: str
    messages: list[dict]
    params: dict
    system_prompt: str
    created_at: Optional[datetime] = None


# ── LLM Judge ─────────────────────────────────────────────────────────────────
class JudgeConfigOut(UTCModel):
    id: str
    name: str
    description: str
    dimensions: list[dict]  # [{name, weight, description}]
    min_score: int = 1
    max_score: int = 10
    created_at: Optional[datetime] = None

class JudgeRunRequest(UTCModel):
    judge_config_id: str
    judge_endpoint_url: str
    judge_api_key: str
    judge_model_id: str
    sample_ids: Optional[list[str]] = None  # None = all samples

class JudgeResultOut(UTCModel):
    id: str
    run_benchmark_id: str
    sample_output_id: str
    judge_config_id: str
    dimension_scores: dict
    overall_score: float
    judge_reasoning: Optional[str] = None
    created_at: Optional[datetime] = None

class JudgeSummaryOut(UTCModel):
    judged_count: int
    avg_score: float
    dimension_averages: dict


# ── Model Pricing ─────────────────────────────────────────────────────────────
class ModelPricingCreate(UTCModel):
    model_id: str
    price_per_1k_input_tokens: float
    price_per_1k_output_tokens: float
    price_per_1k_reasoning_tokens: float = 0.0
    currency: str = "USD"
    source_url: str = ""

class ModelPricingOut(UTCModel):
    id: str
    model_id: str
    price_per_1k_input_tokens: float
    price_per_1k_output_tokens: float
    price_per_1k_reasoning_tokens: float
    currency: str
    created_at: Optional[datetime] = None

class CostBreakdownOut(UTCModel):
    model_id: str
    model_name: Optional[str] = None
    total_cost_usd: float
    run_count: int
    avg_cost_per_run: float


# ── Budget ────────────────────────────────────────────────────────────────────
class BudgetConfigCreate(UTCModel):
    model_id: Optional[str] = None
    budget_usd_per_day: Optional[float] = None
    budget_usd_per_run: Optional[float] = None
    alert_threshold_pct: float = 80.0

class BudgetConfigOut(UTCModel):
    id: str
    model_id: Optional[str] = None
    budget_usd_per_day: Optional[float] = None
    budget_usd_per_run: Optional[float] = None
    alert_threshold_pct: float
    created_at: Optional[datetime] = None


# ── Scheduled Evaluations ─────────────────────────────────────────────────────
class ScheduledEvalCreate(UTCModel):
    model_id: str
    benchmark_ids: list[str]
    eval_config: dict = {}
    schedule_cron: str  # e.g. "0 9 * * 1"
    enabled: bool = True
    notification_email: Optional[str] = None

class ScheduledEvalOut(UTCModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    benchmark_ids: list[str]
    eval_config: dict
    schedule_cron: str
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    notification_email: Optional[str] = None
    created_at: Optional[datetime] = None


# ── Webhook Keys ──────────────────────────────────────────────────────────────
class WebhookKeyOut(UTCModel):
    id: str
    name: str
    key_prefix: str  # first 8 chars for display
    created_at: Optional[datetime] = None

class WebhookKeyCreated(UTCModel):
    id: str
    name: str
    key: str  # shown once on creation
    created_at: Optional[datetime] = None

class WebhookTriggerRequest(UTCModel):
    model_id: str
    benchmark_ids: list[str]
    eval_config: dict = {}
    callback_url: Optional[str] = None


# ── Custom Datasets ───────────────────────────────────────────────────────────
class DatasetCreate(UTCModel):
    name: str
    description: str = ""
    task_type: str = "qa"  # qa | classification | generation | code

class DatasetOut(UTCModel):
    id: str
    name: str
    description: str
    task_type: str
    item_count: int = 0
    created_at: Optional[datetime] = None

class DatasetItemCreate(UTCModel):
    question: str
    expected_answer: str = ""
    context: Optional[str] = None
    metadata: dict = {}
    source: str = "manual"

class DatasetItemOut(UTCModel):
    id: str
    dataset_id: str
    question: str
    expected_answer: str
    context: Optional[str] = None
    metadata: dict
    source: str
    created_at: Optional[datetime] = None


# ── Probe History ─────────────────────────────────────────────────────────────
class ProbeHistoryOut(UTCModel):
    id: str
    endpoint_url: str
    model_id_string: str
    total_checks: int
    passed: int
    failed: int
    warned: int
    skipped: int
    created_at: Optional[datetime] = None


# ── Monitor ───────────────────────────────────────────────────────────────────
class MonitorConfigCreate(UTCModel):
    model_id: str
    check_interval_minutes: int = 15  # 5|15|30|60
    checks_to_run: list[str] = ["connectivity", "basic_completion"]
    alert_on_fail: bool = True
    enabled: bool = True

class MonitorConfigOut(UTCModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    check_interval_minutes: int
    checks_to_run: list[str]
    alert_on_fail: bool
    enabled: bool
    latest_status: Optional[str] = None  # healthy|degraded|down
    created_at: Optional[datetime] = None

class MonitorResultOut(UTCModel):
    id: str
    monitor_config_id: str
    run_at: Optional[datetime] = None
    checks_passed: int
    checks_failed: int
    avg_latency_ms: Optional[float] = None
    status: str  # healthy|degraded|down
    created_at: Optional[datetime] = None


# ── Load Profile ──────────────────────────────────────────────────────────────

class LoadSampleOut(UTCModel):
    id: str
    model_id: str
    sampled_at: Optional[datetime] = None
    latency_ms: float
    status: str
    day_of_week: int
    hour_of_day: int

class LoadWindow(UTCModel):
    day: int
    hour: int
    avg_latency_ms: float
    load_score: float

class LoadProfileOut(UTCModel):
    model_id: str
    heatmap: list[list[float]]   # [7][24]
    quietest_windows: list[LoadWindow]
    busiest_windows: list[LoadWindow]
    current_load: Optional[float] = None
    data_points: int
    confidence: str  # high/medium/low

# ── A/B Tests ─────────────────────────────────────────────────────────────────

class ABTestCreate(UTCModel):
    name: str
    benchmark_ids: list[str]
    model_ids: list[str]  # 2-4 models
    eval_config: dict = {}
    sample_count: int = 10

class ABTestOut(UTCModel):
    id: str
    name: str
    benchmark_ids: list[str]
    model_ids: list[str]
    eval_config: dict
    status: str
    run_ids: list[str] = []
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class ABTestWinnerOut(UTCModel):
    benchmark_id: str
    winner_model_id: Optional[str] = None
    scores: dict  # {model_id: score}

# ── Eval Templates ────────────────────────────────────────────────────────────

class EvalTemplateCreate(UTCModel):
    name: str
    description: str = ""
    model_id: Optional[str] = None
    benchmark_ids: list[str] = []
    eval_config: dict = {}

class EvalTemplateOut(UTCModel):
    id: str
    name: str
    description: str
    model_id: Optional[str] = None
    benchmark_ids: list[str]
    eval_config: dict
    created_at: Optional[datetime] = None

# ── Sensitivity Analysis ──────────────────────────────────────────────────────

class SensitivityRequest(UTCModel):
    endpoint_url: str
    api_key: str
    model_id: str
    base_message: str
    variations: list[str]  # up to 10
    params: dict = {}

class SensitivityResult(UTCModel):
    variation: str
    response: str
    latency_ms: float
    error: Optional[str] = None

class SensitivityOut(UTCModel):
    responses: list[SensitivityResult]
    consistency_score: float
    most_common_answer: str
    answer_distribution: dict
    outlier_responses: list[str]


# ── GPU Droplets (Benchmarking Evaluation) ────────────────────────────────────

class DropletCreate(UTCModel):
    name: str
    region: str = "nyc2"
    size_slug: str                      # GPU size, e.g. "gpu-h100x1-80gb"
    image: str = "ubuntu-22-04-x64"     # used as-is for image_source os/custom
    image_source: str = "aiml"          # aiml | os | custom — aiml is resolved from the GPU plan
    do_token: str                       # per-droplet token; stored Fernet-encrypted, never returned
    # Authoritative GPU details the user selected from the catalog — persisted so
    # deployments don't have to re-derive them from the per-droplet token (which
    # may return sparse size data). Optional (omitted for custom sizes).
    gpu_count: Optional[int] = None
    gpu_model: Optional[str] = None
    gpu_platform: Optional[str] = None
    gpu_vram_gb: Optional[int] = None
    hourly_price_usd: Optional[float] = None


class DropletOut(UTCModel):
    id: str
    name: str
    region: str
    size_slug: str
    image: Optional[str] = None
    do_droplet_id: Optional[int] = None
    ip: Optional[str] = None
    ssh_public_key: Optional[str] = None
    do_ssh_key_id: Optional[int] = None
    status: str = "provisioning"        # provisioning|active|destroying|destroyed|failed
    status_detail: Optional[str] = None
    hourly_price_usd: Optional[float] = None
    # GPU metadata (captured at provision) — used by deployments for recipe/TP matching.
    gpu_count: Optional[int] = None
    gpu_model: Optional[str] = None
    gpu_platform: Optional[str] = None
    gpu_vram_gb: Optional[int] = None
    # Live GPU telemetry from the agent's heartbeat (nvidia-smi/rocm-smi).
    gpu_stats: Optional[dict] = None          # latest {ts, gpus:[...]}
    gpu_history: list[dict] = []              # capped rolling samples for sparklines
    created_at: Optional[datetime] = None
    destroyed_at: Optional[datetime] = None


# ── Deployments (serve a model on a droplet) ──────────────────────────────────

class DeploymentArg(UTCModel):
    flag: str
    value: str = ""                     # bare flags have an empty value


class DeploymentCreate(UTCModel):
    droplet_id: str
    engine: str = "vllm"
    model: str                          # HF model id, e.g. "Qwen/Qwen2.5-32B"
    docker_image: str
    server_args: list[DeploymentArg] = []
    env: dict[str, str] = {}
    port: int = 8000
    hf_token: str = ""                  # optional; Fernet-encrypted, never returned
    recipe_source_url: Optional[str] = None
    hardware_key: Optional[str] = None
    startup_timeout_min: Optional[int] = None   # how long to wait for the model to
    #                                             become healthy (big FP4/MoE models
    #                                             can take well over the default)


class DeploymentOut(UTCModel):
    id: str
    droplet_id: str
    droplet_name: Optional[str] = None
    droplet_snapshot: dict = {}
    engine: str = "vllm"
    model: str
    docker_image: str
    server_args: list[DeploymentArg] = []
    env: dict[str, str] = {}
    port: int = 8000
    recipe_source_url: Optional[str] = None
    hardware_key: Optional[str] = None
    container_id: Optional[str] = None
    status: str = "pulling"             # pulling|starting|serving|failed|droplet_destroyed
    status_detail: Optional[str] = None
    health: Optional[str] = None
    log_tail: Optional[str] = None
    events: list[dict] = []
    created_at: Optional[datetime] = None
    droplet_destroyed_at: Optional[datetime] = None


# ── Benchmark runs (aiperf against a serving deployment) ───────────────────────

class AiperfArg(UTCModel):
    flag: str
    value: str = ""                     # bare flags (e.g. --streaming) have an empty value


class AiperfRunCreate(UTCModel):
    deployment_id: str
    # Editable aiperf flags, seeded with sensible defaults in the UI (concurrency,
    # request-count, isl, osl, streaming, …). model/url/tokenizer are injected by
    # the backend from the deployment, so they're never user-editable here.
    args: list[AiperfArg] = []
    # Opt-in extra percentiles to compute for this run (e.g. [75, 95]); the agent
    # derives them from the per-request export so we never store raw data.
    extra_percentiles: list[int] = []
    # Optional alternate HF token JUST for the tokenizer download — if omitted we
    # reuse the deployment's token. Fernet-encrypted, never returned.
    hf_token: str = ""


# Archive (hide) or restore a set of finished runs so they stop muddling the
# History dashboards and SLA cohorts. Reversible — hidden is just a flag.
class AiperfArchive(UTCModel):
    run_ids: list[str] = []
    hidden: bool = True


class AiperfRunOut(UTCModel):
    id: str
    deployment_id: str
    deployment_name: Optional[str] = None
    engine: str = "vllm"
    model: str
    # Tombstone snapshots so History survives droplet/deployment teardown.
    droplet_snapshot: dict = {}
    deployment_snapshot: dict = {}
    profile: dict = {}                  # {args: [...], extra_percentiles: [...]}
    status: str = "queued"             # queued|running|completed|failed
    status_detail: Optional[str] = None
    metrics: dict = {}                  # normalized {metric: {avg,min,max,p50,...,unit}}
    trends: dict = {}                   # {latency:[...], serving:[...]} time-windowed series
    log_tail: Optional[str] = None
    events: list[dict] = []
    queue_position: Optional[int] = None   # runs ahead of this one on the same droplet
    hidden: bool = False                    # archived out of History/SLA dashboards
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Saved benchmark configurations (named aiperf profiles) ─────────────────────
# A config is a reusable, deployment-agnostic profile (args + extra_percentiles).
# model/url/tokenizer are injected from the deployment at queue time, so the same
# config can be queued against any deployment — e.g. a concurrency sweep saved as
# "conc-128", "conc-256", … then selected together and queued in one click.
class AiperfConfigCreate(UTCModel):
    name: str
    args: list[AiperfArg] = []
    extra_percentiles: list[int] = []


class AiperfConfigOut(UTCModel):
    id: str
    name: str
    args: list[AiperfArg] = []
    extra_percentiles: list[int] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# Queue many saved configs against one deployment in a single request — reconciles
# the droplet and runs the gated-token check once, then enqueues one run per config
# (they drain serially via the existing per-droplet queue).
class AiperfBatchCreate(UTCModel):
    deployment_id: str
    config_ids: list[str] = []
    # Optional alternate HF token for the tokenizer download, applied to every run
    # in the batch (gating is per-deployment, not per-config).
    hf_token: str = ""

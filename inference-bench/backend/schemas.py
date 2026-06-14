"""All Pydantic v2 request/response schemas.

IDs are strings throughout (MongoDB ObjectId hex strings).
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


# ── Models ────────────────────────────────────────────────────────────────────

class ModelCreate(BaseModel):
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


class ModelUpdate(BaseModel):
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


class ModelOut(BaseModel):
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


class ConnectionTestOut(BaseModel):
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


# ── Benchmarks ────────────────────────────────────────────────────────────────

class BenchmarkOut(BaseModel):
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


class CategoryOut(BaseModel):
    category: str
    count: int


# ── Evaluations ───────────────────────────────────────────────────────────────

class EvaluationCreate(BaseModel):
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


class RunBenchmarkOut(BaseModel):
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


class EvaluationOut(BaseModel):
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


class SampleOutputOut(BaseModel):
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

class NoteCreate(BaseModel):
    content: str
    note_type: str = "general"
    is_pinned: bool = False


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    note_type: Optional[str] = None
    is_pinned: Optional[bool] = None


class NoteOut(BaseModel):
    id: str
    run_id: str
    note_type: str = "general"
    content: str
    is_pinned: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationCheckResult(BaseModel):
    check_id: str
    name: str
    category: str
    status: str        # pass | fail | warn | skip
    latency_ms: float
    detail: dict[str, Any] = {}
    message: str


class ValidationRunOut(BaseModel):
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

class BenchmarkTargetOut(BaseModel):
    id: str
    benchmark_suite_id: str
    target_score: float
    target_label: str
    created_at: Optional[datetime] = None


# ── Stress test ───────────────────────────────────────────────────────────────

class StressTestCreate(BaseModel):
    concurrency_levels: list[int] = [1, 2, 4, 8, 16]
    requests_per_level: int = 10
    prompt_tokens: int = 128
    output_tokens: int = 256
    test_duration_seconds: int = 60


class StressLevelResult(BaseModel):
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


class StressTestOut(BaseModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    status: str
    config: dict[str, Any] = {}
    results: list[StressLevelResult] = []
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── System info ───────────────────────────────────────────────────────────────

class SystemInfoOut(BaseModel):
    python_version: str
    database: str = "mongodb"
    benchmarks_seeded: int
    total_runs: int
    total_models: int
    evalscope_available: bool
    worker_threads: int = 4


# ── Probe (unauthenticated endpoint test) ─────────────────────────────────────

class ProbeRequest(BaseModel):
    endpoint_url: str
    api_key: str
    model_id: str
    checks: Optional[list[str]] = None   # None = run all


# ── Regression alert ──────────────────────────────────────────────────────────

class RegressionAlertOut(BaseModel):
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
class PlaygroundMessage(BaseModel):
    role: str  # user | assistant | system
    content: str

class PlaygroundParams(BaseModel):
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 1.0
    seed: Optional[int] = None
    stop: list[str] = []
    response_format: Optional[str] = None  # none | json_object | json_schema
    json_schema: Optional[str] = None
    thinking_mode: bool = False
    reasoning_effort: Optional[str] = None  # low | medium | high

class PlaygroundRunRequest(BaseModel):
    endpoint_url: str
    api_key: str
    model_id: str
    messages: list[PlaygroundMessage]
    params: PlaygroundParams = PlaygroundParams()
    system_prompt: Optional[str] = None

class PlaygroundRunResult(BaseModel):
    content: str
    reasoning_content: Optional[str] = None
    finish_reason: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: float = 0.0
    cost_estimate: Optional[float] = None
    error: Optional[str] = None

class PlaygroundBatchResult(BaseModel):
    results: list[PlaygroundRunResult]
    consistency_score: float  # 0-1
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    token_variance: float

class PlaygroundTemplateCreate(BaseModel):
    name: str
    description: str = ""
    messages: list[dict]  # [{role, content}]
    params: dict = {}
    system_prompt: str = ""

class PlaygroundTemplateOut(BaseModel):
    id: str
    name: str
    description: str
    messages: list[dict]
    params: dict
    system_prompt: str
    created_at: Optional[datetime] = None


# ── LLM Judge ─────────────────────────────────────────────────────────────────
class JudgeConfigOut(BaseModel):
    id: str
    name: str
    description: str
    dimensions: list[dict]  # [{name, weight, description}]
    min_score: int = 1
    max_score: int = 10
    created_at: Optional[datetime] = None

class JudgeRunRequest(BaseModel):
    judge_config_id: str
    judge_endpoint_url: str
    judge_api_key: str
    judge_model_id: str
    sample_ids: Optional[list[str]] = None  # None = all samples

class JudgeResultOut(BaseModel):
    id: str
    run_benchmark_id: str
    sample_output_id: str
    judge_config_id: str
    dimension_scores: dict
    overall_score: float
    judge_reasoning: Optional[str] = None
    created_at: Optional[datetime] = None

class JudgeSummaryOut(BaseModel):
    judged_count: int
    avg_score: float
    dimension_averages: dict


# ── Model Pricing ─────────────────────────────────────────────────────────────
class ModelPricingCreate(BaseModel):
    model_id: str
    price_per_1k_input_tokens: float
    price_per_1k_output_tokens: float
    price_per_1k_reasoning_tokens: float = 0.0
    currency: str = "USD"
    source_url: str = ""

class ModelPricingOut(BaseModel):
    id: str
    model_id: str
    price_per_1k_input_tokens: float
    price_per_1k_output_tokens: float
    price_per_1k_reasoning_tokens: float
    currency: str
    created_at: Optional[datetime] = None

class CostBreakdownOut(BaseModel):
    model_id: str
    model_name: Optional[str] = None
    total_cost_usd: float
    run_count: int
    avg_cost_per_run: float


# ── Budget ────────────────────────────────────────────────────────────────────
class BudgetConfigCreate(BaseModel):
    model_id: Optional[str] = None
    budget_usd_per_day: Optional[float] = None
    budget_usd_per_run: Optional[float] = None
    alert_threshold_pct: float = 80.0

class BudgetConfigOut(BaseModel):
    id: str
    model_id: Optional[str] = None
    budget_usd_per_day: Optional[float] = None
    budget_usd_per_run: Optional[float] = None
    alert_threshold_pct: float
    created_at: Optional[datetime] = None


# ── Scheduled Evaluations ─────────────────────────────────────────────────────
class ScheduledEvalCreate(BaseModel):
    model_id: str
    benchmark_ids: list[str]
    eval_config: dict = {}
    schedule_cron: str  # e.g. "0 9 * * 1"
    enabled: bool = True
    notification_email: Optional[str] = None

class ScheduledEvalOut(BaseModel):
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
class WebhookKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str  # first 8 chars for display
    created_at: Optional[datetime] = None

class WebhookKeyCreated(BaseModel):
    id: str
    name: str
    key: str  # shown once on creation
    created_at: Optional[datetime] = None

class WebhookTriggerRequest(BaseModel):
    model_id: str
    benchmark_ids: list[str]
    eval_config: dict = {}
    callback_url: Optional[str] = None


# ── Custom Datasets ───────────────────────────────────────────────────────────
class DatasetCreate(BaseModel):
    name: str
    description: str = ""
    task_type: str = "qa"  # qa | classification | generation | code

class DatasetOut(BaseModel):
    id: str
    name: str
    description: str
    task_type: str
    item_count: int = 0
    created_at: Optional[datetime] = None

class DatasetItemCreate(BaseModel):
    question: str
    expected_answer: str = ""
    context: Optional[str] = None
    metadata: dict = {}
    source: str = "manual"

class DatasetItemOut(BaseModel):
    id: str
    dataset_id: str
    question: str
    expected_answer: str
    context: Optional[str] = None
    metadata: dict
    source: str
    created_at: Optional[datetime] = None


# ── Probe History ─────────────────────────────────────────────────────────────
class ProbeHistoryOut(BaseModel):
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
class MonitorConfigCreate(BaseModel):
    model_id: str
    check_interval_minutes: int = 15  # 5|15|30|60
    checks_to_run: list[str] = ["connectivity", "basic_completion"]
    alert_on_fail: bool = True
    enabled: bool = True

class MonitorConfigOut(BaseModel):
    id: str
    model_id: str
    model_name: Optional[str] = None
    check_interval_minutes: int
    checks_to_run: list[str]
    alert_on_fail: bool
    enabled: bool
    latest_status: Optional[str] = None  # healthy|degraded|down
    created_at: Optional[datetime] = None

class MonitorResultOut(BaseModel):
    id: str
    monitor_config_id: str
    run_at: Optional[datetime] = None
    checks_passed: int
    checks_failed: int
    avg_latency_ms: Optional[float] = None
    status: str  # healthy|degraded|down
    created_at: Optional[datetime] = None

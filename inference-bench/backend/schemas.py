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

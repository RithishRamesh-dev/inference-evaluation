"""All Pydantic v2 request/response schemas.

IDs are strings throughout (MongoDB ObjectId hex strings).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
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

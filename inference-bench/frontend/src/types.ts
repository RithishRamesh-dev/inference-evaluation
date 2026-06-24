// All shared TypeScript types — MongoDB ObjectId strings used as IDs everywhere.

export interface Model {
  id: string
  name: string
  provider: string
  endpoint_url: string
  model_id: string
  context_length: number | null
  supports_vision: boolean
  supports_tool_calling: boolean
  supports_structured_output: boolean
  supports_reasoning: boolean
  supports_multimodal: boolean
  reasoning_format: string | null
  reasoning_enable_param: string | null
  reasoning_disable_param: string | null
  custom_headers: string
  is_custom: boolean
  created_at: string | null
  updated_at: string | null
}

export interface ModelCreate {
  name: string
  provider: string
  endpoint_url: string
  model_id: string
  api_key?: string
  context_length?: number
  supports_vision?: boolean
  supports_tool_calling?: boolean
  supports_structured_output?: boolean
  supports_reasoning?: boolean
  supports_multimodal?: boolean
  reasoning_format?: string
  reasoning_enable_param?: string
  reasoning_disable_param?: string
  custom_headers?: string
  is_custom?: boolean
}

export interface ConnectionTestResult {
  ok: boolean
  latency_ms: number | null
  error: string | null
}

export interface BenchmarkSuite {
  id: string
  name: string
  display_name: string
  category: string
  description: string | null
  evalscope_id: string
  default_metric: string
  is_recommended: boolean
  is_vision: boolean
  requires_tools: boolean
  total_samples: number | null
  tags: string
  evalscope_config: string
}

export interface CategoryCount {
  category: string
  count: number
}

export interface EvaluationCreate {
  model_id: string
  display_name?: string
  benchmark_ids: string[]
  eval_scope: 'full' | 'sample'
  sample_count?: number
  eval_batch_size?: number
  timeout_seconds?: number
  retry_count?: number
  temperature?: number
  max_tokens?: number
  thinking_mode?: 'enabled' | 'disabled'
  reasoning_effort?: 'low' | 'medium' | 'high'
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface RunBenchmark {
  id: string
  run_id: string
  benchmark_suite_id: string
  suite_name: string | null
  suite_display_name: string | null
  suite_category: string | null
  status: string
  primary_score: number | null
  subset_scores: string
  samples_total: number | null
  samples_scored: number | null
  samples_errored: number | null
  avg_latency_s: number | null
  avg_input_tokens: number | null
  avg_output_tokens: number | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface EvaluationRun {
  id: string
  model_id: string
  model_name: string | null
  model_provider: string | null
  display_name: string | null
  eval_scope: string
  sample_count: number | null
  eval_batch_size: number
  timeout_seconds: number
  temperature: number | null
  max_tokens: number | null
  thinking_mode: string | null
  reasoning_effort: string | null
  status: RunStatus
  overall_score: number | null
  total_benchmarks: number
  passed_benchmarks: number
  started_at: string | null
  completed_at: string | null
  wall_time_seconds: number | null
  created_at: string | null
  run_benchmarks: RunBenchmark[]
}

export interface SampleOutput {
  id: string
  run_benchmark_id: string
  sample_index: number
  question: string | null
  expected_answer: string | null
  model_output: string | null
  reasoning_content: string | null
  is_correct: boolean | null
  score: number | null
  finish_reason: string | null
  latency_s: number | null
  input_tokens: number | null
  output_tokens: number | null
  error: string | null
}

export interface RunNote {
  id: string
  run_id: string
  note_type: string
  content: string
  is_pinned: boolean
  created_at: string | null
  updated_at: string | null
}

export interface ProgressData {
  status: RunStatus
  percent: number
  current_benchmark: string | null
  samples_done: number
  samples_total: number
  eta_seconds: number | null
  elapsed_seconds: number
  overall_score?: number
  events?: Array<{ event: string; ts: string; [key: string]: unknown }>
}

export interface ValidationCheckResult {
  check_id: string
  name: string
  category: string
  status: 'pass' | 'fail' | 'warn' | 'skip'
  latency_ms: number
  detail: Record<string, unknown>
  message: string
}

export interface ValidationRun {
  id: string
  model_id: string
  model_name: string | null
  status: string
  total_checks: number
  passed: number
  warned: number
  failed: number
  skipped: number
  checks: ValidationCheckResult[]
  created_at: string | null
  completed_at: string | null
  duration_ms: number | null
}

export interface StressLevelResult {
  concurrency: number
  requests_total: number
  requests_succeeded: number
  requests_failed: number
  avg_latency_ms: number
  p50_latency_ms: number
  p90_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  ttft_ms_avg: number | null
  throughput_requests_per_second: number
  throughput_tokens_per_second: number
  total_output_tokens: number
  error_rate: number
  timeout_rate: number
}

export interface StressTestRun {
  id: string
  model_id: string
  model_name: string | null
  status: string
  config: {
    concurrency_levels: number[]
    requests_per_level: number
    prompt_tokens: number
    output_tokens: number
    test_duration_seconds: number
  }
  results: StressLevelResult[]
  created_at: string | null
  completed_at: string | null
}

export interface RegressionAlert {
  id: string
  run_id: string
  benchmark_suite_id: string
  benchmark_name: string | null
  prev_score: number
  curr_score: number
  delta: number
  acknowledged: boolean
  created_at: string | null
}

export interface SystemInfo {
  python_version: string
  database: string
  benchmarks_seeded: number
  total_runs: number
  total_models: number
  evalscope_available: boolean
  worker_threads: number
}

// ── Playground ─────────────────────────────────────────────────────────────
export interface PlaygroundMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface PlaygroundParams {
  temperature: number
  max_tokens: number
  top_p: number
  seed?: number
  stop: string[]
  response_format?: string
  json_schema?: string
  thinking_mode: boolean
  reasoning_effort?: string
}

export interface PlaygroundRunResult {
  content: string
  reasoning_content?: string
  finish_reason?: string
  prompt_tokens: number
  completion_tokens: number
  reasoning_tokens: number
  latency_ms: number
  cost_estimate?: number
  error?: string
}

export interface PlaygroundBatchResult {
  results: PlaygroundRunResult[]
  consistency_score: number
  avg_latency_ms: number
  min_latency_ms: number
  max_latency_ms: number
  token_variance: number
}

export interface PlaygroundTemplate {
  id: string
  name: string
  description: string
  messages: PlaygroundMessage[]
  params: Partial<PlaygroundParams>
  system_prompt: string
  is_custom?: boolean
}

// ── Judge ───────────────────────────────────────────────────────────────────
export interface JudgeConfig {
  id: string
  name: string
  description: string
  dimensions: Array<{ name: string; weight: number; description: string }>
  min_score: number
  max_score: number
}

export interface JudgeResult {
  id: string
  run_benchmark_id: string
  sample_output_id: string
  judge_config_id: string
  dimension_scores: Record<string, { score: number; reason: string }>
  overall_score: number
  question?: string
  model_output_preview?: string
}

export interface JudgeSummary {
  judged_count: number
  avg_score: number
  dimension_averages: Record<string, number>
}

// ── Datasets ────────────────────────────────────────────────────────────────
export interface Dataset {
  id: string
  name: string
  description: string
  task_type: string
  item_count: number
  created_at?: string
}

export interface DatasetItem {
  id: string
  dataset_id: string
  question: string
  expected_answer: string
  context?: string
  metadata: Record<string, unknown>
  source: string
  created_at?: string
}

// ── Schedules ───────────────────────────────────────────────────────────────
export interface ScheduledEval {
  id: string
  model_id: string
  model_name?: string
  benchmark_ids: string[]
  eval_config: Record<string, unknown>
  schedule_cron: string
  enabled: boolean
  last_run_at?: string
  next_run_at?: string
  notification_email?: string
  created_at?: string
}

// ── Webhooks ────────────────────────────────────────────────────────────────
export interface WebhookKey {
  id: string
  name: string
  key_prefix: string
  created_at?: string
}

export interface WebhookKeyCreated {
  id: string
  name: string
  key: string
  created_at?: string
}

// ── Monitor ─────────────────────────────────────────────────────────────────
export interface MonitorConfig {
  id: string
  model_id: string
  model_name?: string
  check_interval_minutes: number
  checks_to_run: string[]
  alert_on_fail: boolean
  enabled: boolean
  latest_status?: string
  created_at?: string
}

export interface MonitorResult {
  id: string
  monitor_config_id: string
  run_at?: string
  checks_passed: number
  checks_failed: number
  avg_latency_ms?: number
  status: string
  created_at?: string
}

// ── Probe History ───────────────────────────────────────────────────────────
export interface ProbeHistory {
  id: string
  endpoint_url: string
  model_id_string: string
  total_checks: number
  passed: number
  failed: number
  warned: number
  skipped: number
  created_at?: string
}

// ── Pricing ─────────────────────────────────────────────────────────────────
export interface ModelPricing {
  id: string
  model_id: string
  price_per_1k_input_tokens: number
  price_per_1k_output_tokens: number
  price_per_1k_reasoning_tokens: number
  currency: string
}

export interface CostSummary {
  total_cost_usd: number
  period_days: number
  by_model: Array<{ model_id: string; model_name: string; total_cost_usd: number; run_count: number }>
  by_day: Array<{ date: string; cost_usd: number }>
}

// ── A/B Tests ────────────────────────────────────────────────────────────────
export interface ABTest {
  id: string
  name: string
  model_ids: string[]
  benchmark_ids: string[]
  sample_count: number
  eval_scope: string
  run_ids: string[]
  status: string
  created_at?: string
  completed_at?: string
}

export interface ABTestWinner {
  benchmark_id: string
  benchmark_name: string
  winners: Array<{
    model_id: string
    model_name: string
    score: number
    run_id: string
  }>
}

// ── Eval Templates ───────────────────────────────────────────────────────────
export interface EvalTemplate {
  id: string
  name: string
  description: string
  model_id?: string
  benchmark_ids: string[]
  eval_config: Record<string, unknown>
  created_at?: string
}

// ── Load Profile ─────────────────────────────────────────────────────────────
export interface LoadWindow {
  day: number
  hour: number
  avg_latency_ms: number | null
  sample_count: number
  load_level: number
}

export interface LoadProfile {
  model_id: string
  windows: LoadWindow[]
  best_window: { day: number; hour: number } | null
  worst_window: { day: number; hour: number } | null
  total_samples: number
}

// ── Sensitivity ──────────────────────────────────────────────────────────────
export interface SensitivityVariant {
  variant_id: string
  prompt: string
  response: string
  tokens: number
  latency_ms: number
  cost_estimate: number
}

export interface SensitivityResult {
  base_prompt: string
  variants: SensitivityVariant[]
  semantic_similarity_avg: number
  length_variance: number
  consistency_score: number
}

// ── Global Search ─────────────────────────────────────────────────────────────
export interface SearchResults {
  models: Array<{ id: string; name: string; provider: string }>
  runs: Array<{ id: string; display_name: string | null; model_name: string | null; status: string }>
  benchmarks: Array<{ id: string; name: string; display_name: string; category: string }>
}

// ── Benchmarking Evaluation — GPU Droplets ────────────────────────────────────
export type DropletStatus = 'provisioning' | 'active' | 'destroying' | 'destroyed' | 'failed'

export interface GpuDroplet {
  id: string
  name: string
  region: string
  size_slug: string
  image: string | null
  do_droplet_id: number | null
  ip: string | null
  ssh_public_key: string | null
  do_ssh_key_id: number | null
  status: DropletStatus
  status_detail: string | null
  hourly_price_usd: number | null
  created_at: string | null
  destroyed_at: string | null
}

export interface DropletCreate {
  name: string
  region: string
  size_slug: string
  image?: string
  do_token: string   // per-droplet token, used to create & destroy this droplet
}

export interface GpuSizeOption {
  slug: string
  category: string            // GPU | Basic | General Purpose | CPU-Optimized | …
  description: string
  vcpus: number | null
  memory_gb: number | null
  disk_gb: number | null
  price_hourly: number | null
  price_monthly: number | null
  available: boolean
  regions: string[]
  gpu_count: number | null
  gpu_model: string | null
  gpu_vram_gb: number | null
}

export interface DropletRegion {
  slug: string
  name: string
  available: boolean
}

export interface DropletImageOption {
  slug: string
  name: string
  distribution: string
}

export interface DropletOptions {
  sizes: GpuSizeOption[]
  regions: DropletRegion[]
  images: DropletImageOption[]
}

export interface DropletProgress {
  status: DropletStatus | string
  ip?: string | null
  do_status?: string
  hourly_price_usd?: number | null
  status_detail?: string
  events?: Array<{ event: string; ts: string; [key: string]: unknown }>
}

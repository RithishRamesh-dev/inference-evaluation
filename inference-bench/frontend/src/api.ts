/// <reference types="vite/client" />
import type {
  BenchmarkSuite, CategoryCount, ConnectionTestResult,
  EvaluationCreate, EvaluationRun,
  Model, ModelCreate,
  RegressionAlert,
  RunNote, SampleOutput,
  StressTestRun,
  SystemInfo,
  ValidationRun,
} from './types'
import type {
  PlaygroundRunResult, PlaygroundBatchResult, PlaygroundTemplate,
  JudgeConfig, JudgeSummary, JudgeResult,
  Dataset, DatasetItem,
  ScheduledEval,
  WebhookKey, WebhookKeyCreated,
  MonitorConfig, MonitorResult,
  ProbeHistory,
  ModelPricing, CostSummary,
  ABTest, ABTestWinner, EvalTemplate, LoadProfile, SensitivityResult, SearchResults,
  GpuDroplet, DropletCreate, DropletOptions,
  Deployment, DeploymentCreate, EngineInfo, RecipeModel, ResolvedRecipe,
  AiperfRun, AiperfRunCreate, AiperfConfig, AiperfConfigCreate, AiperfBatchCreate,
} from './types'

const API_KEY = import.meta.env.VITE_API_KEY ?? 'dev-key'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      'X-API-Key': API_KEY,
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  models: {
    list: (params?: { search?: string; provider?: string; supports_vision?: boolean; supports_reasoning?: boolean; supports_tool_calling?: boolean }) =>
      apiFetch<Model[]>(`/models${qs(params as Record<string, unknown>)}`),

    get: (id: string) =>
      apiFetch<Model>(`/models/${id}`),

    create: (body: ModelCreate) =>
      apiFetch<Model>('/models', { method: 'POST', body: JSON.stringify(body) }),

    update: (id: string, body: Partial<ModelCreate>) =>
      apiFetch<Model>(`/models/${id}`, { method: 'PUT', body: JSON.stringify(body) }),

    delete: (id: string) =>
      apiFetch<void>(`/models/${id}`, { method: 'DELETE' }),

    test: (id: string) =>
      apiFetch<ConnectionTestResult>(`/models/${id}/test`, { method: 'POST' }),
  },

  benchmarks: {
    list: (params?: { category?: string; is_recommended?: boolean; search?: string }) =>
      apiFetch<BenchmarkSuite[]>(`/benchmarks${qs(params as Record<string, unknown>)}`),

    categories: () =>
      apiFetch<CategoryCount[]>('/benchmarks/categories'),

    recommended: () =>
      apiFetch<BenchmarkSuite[]>('/benchmarks/recommended'),
  },

  evaluations: {
    create: (body: EvaluationCreate) =>
      apiFetch<EvaluationRun>('/evaluations', { method: 'POST', body: JSON.stringify(body) }),

    start: (id: string) =>
      apiFetch<EvaluationRun>(`/evaluations/${id}/start`, { method: 'POST' }),

    cancel: (id: string) =>
      apiFetch<{ cancelled: boolean }>(`/evaluations/${id}/cancel`, { method: 'POST' }),

    list: (params?: { status?: string; limit?: number; offset?: number }) =>
      apiFetch<EvaluationRun[]>(`/evaluations${qs(params as Record<string, unknown>)}`),

    get: (id: string) =>
      apiFetch<EvaluationRun>(`/evaluations/${id}`),

    results: (id: string) =>
      apiFetch<EvaluationRun>(`/evaluations/${id}/results`),

    samples: (id: string, rbId: string, params?: { limit?: number; offset?: number }) =>
      apiFetch<SampleOutput[]>(`/evaluations/${id}/benchmarks/${rbId}/samples${qs(params as Record<string, unknown>)}`),

    compare: (ids: string[]) =>
      apiFetch<EvaluationRun[]>(`/evaluations/compare?ids=${ids.join(',')}`),
  },

  notes: {
    list: (runId: string) =>
      apiFetch<RunNote[]>(`/evaluations/${runId}/notes`),

    create: (runId: string, body: { content: string; note_type?: string; is_pinned?: boolean }) =>
      apiFetch<RunNote>(`/evaluations/${runId}/notes`, { method: 'POST', body: JSON.stringify(body) }),

    update: (runId: string, noteId: string, body: { content?: string; note_type?: string; is_pinned?: boolean }) =>
      apiFetch<RunNote>(`/evaluations/${runId}/notes/${noteId}`, { method: 'PUT', body: JSON.stringify(body) }),

    delete: (runId: string, noteId: string) =>
      apiFetch<void>(`/evaluations/${runId}/notes/${noteId}`, { method: 'DELETE' }),
  },

  /** SSE stream URL — use with EventSource directly */
  streamUrl: (runId: string) =>
    `/api/evaluations/${runId}/stream?api_key=${API_KEY}`,

  validation: {
    run: (modelId: string) =>
      apiFetch<ValidationRun>(`/models/${modelId}/validate`, { method: 'POST' }),
    history: (modelId: string) =>
      apiFetch<ValidationRun[]>(`/models/${modelId}/validate/history`),
    latest: (modelId: string) =>
      apiFetch<ValidationRun>(`/models/${modelId}/validate/latest`),
    curlUrl: (modelId: string) =>
      `/api/models/${modelId}/validate/curl`,
  },

  probe: (body: { endpoint_url: string; api_key: string; model_id: string; checks?: string[] }) =>
    apiFetch<Array<Record<string, unknown>>>('/probe', { method: 'POST', body: JSON.stringify(body) }),

  stressTest: {
    create: (modelId: string, body: {
      concurrency_levels?: number[]; requests_per_level?: number;
      prompt_tokens?: number; output_tokens?: number; test_duration_seconds?: number;
    }) =>
      apiFetch<{ test_id: string }>(`/models/${modelId}/stress-test`, { method: 'POST', body: JSON.stringify(body) }),
    get: (modelId: string, testId: string) =>
      apiFetch<StressTestRun>(`/models/${modelId}/stress-test/${testId}`),
    list: (modelId: string) =>
      apiFetch<StressTestRun[]>(`/models/${modelId}/stress-tests`),
  },

  export: (runId: string, format: 'json' | 'csv' | 'md' | 'html') =>
    `/api/evaluations/${runId}/export?format=${format}`,

  regressionAlerts: {
    list: (acknowledged?: boolean) =>
      apiFetch<RegressionAlert[]>(`/regression-alerts${acknowledged !== undefined ? `?acknowledged=${acknowledged}` : ''}`),
    acknowledge: (id: string) =>
      apiFetch<{ acknowledged: boolean }>(`/regression-alerts/${id}/acknowledge`, { method: 'POST' }),
  },

  system: {
    info: () => apiFetch<SystemInfo>('/system/info'),
  },

  playground: {
    run: (body: object) => apiFetch<PlaygroundRunResult>('/api/playground/run', { method: 'POST', body: JSON.stringify(body) }),
    runBatch: (body: object) => apiFetch<PlaygroundBatchResult>('/api/playground/run-batch', { method: 'POST', body: JSON.stringify(body) }),
    templates: () => apiFetch<PlaygroundTemplate[]>('/api/playground/templates'),
    saveTemplate: (body: object) => apiFetch<PlaygroundTemplate>('/api/playground/templates', { method: 'POST', body: JSON.stringify(body) }),
    deleteTemplate: (id: string) => apiFetch<void>(`/api/playground/templates/${id}`, { method: 'DELETE' }),
  },

  judge: {
    configs: () => apiFetch<JudgeConfig[]>('/api/judge/configs'),
    run: (runId: string, body: object) => apiFetch<JudgeSummary>(`/api/evaluations/${runId}/judge`, { method: 'POST', body: JSON.stringify(body) }),
    results: (runId: string) => apiFetch<JudgeResult[]>(`/api/evaluations/${runId}/judge/results`),
  },

  datasets: {
    list: () => apiFetch<Dataset[]>('/api/datasets'),
    get: (id: string) => apiFetch<Dataset>(`/api/datasets/${id}`),
    create: (body: object) => apiFetch<Dataset>('/api/datasets', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id: string) => apiFetch<void>(`/api/datasets/${id}`, { method: 'DELETE' }),
    items: (id: string) => apiFetch<DatasetItem[]>(`/api/datasets/${id}/items`),
    addItem: (id: string, body: object) => apiFetch<DatasetItem>(`/api/datasets/${id}/items`, { method: 'POST', body: JSON.stringify(body) }),
    deleteItem: (id: string, itemId: string) => apiFetch<void>(`/api/datasets/${id}/items/${itemId}`, { method: 'DELETE' }),
    exportUrl: (id: string, format: string) => `/api/datasets/${id}/export?format=${format}`,
  },

  schedules: {
    list: () => apiFetch<ScheduledEval[]>('/api/schedules'),
    create: (body: object) => apiFetch<ScheduledEval>('/api/schedules', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id: string) => apiFetch<void>(`/api/schedules/${id}`, { method: 'DELETE' }),
    toggle: (id: string) => apiFetch<{ enabled: boolean }>(`/api/schedules/${id}/toggle`, { method: 'PUT' }),
    previewCron: (cron: string) => apiFetch<{ description: string; next_run: string }>('/api/schedules/cron-preview', { method: 'POST', body: JSON.stringify({ cron }) }),
  },

  webhooks: {
    keys: () => apiFetch<WebhookKey[]>('/api/webhooks/keys'),
    createKey: (name: string) => apiFetch<WebhookKeyCreated>('/api/webhooks/keys', { method: 'POST', body: JSON.stringify({ name }) }),
    deleteKey: (id: string) => apiFetch<void>(`/api/webhooks/keys/${id}`, { method: 'DELETE' }),
  },

  monitors: {
    list: () => apiFetch<MonitorConfig[]>('/api/monitors'),
    create: (body: object) => apiFetch<MonitorConfig>('/api/monitors', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id: string) => apiFetch<void>(`/api/monitors/${id}`, { method: 'DELETE' }),
    toggle: (id: string) => apiFetch<{ enabled: boolean }>(`/api/monitors/${id}/toggle`, { method: 'PUT' }),
    results: (id: string, hours?: number) => apiFetch<MonitorResult[]>(`/api/monitors/${id}/results${hours ? `?hours=${hours}` : ''}`),
    uptime: (id: string) => apiFetch<{ uptime_24h: number; uptime_7d: number; uptime_30d: number }>(`/api/monitors/${id}/uptime`),
    incidents: (id: string) => apiFetch<Array<{ start: string; end: string; duration_seconds: number }>>(`/api/monitors/${id}/incidents`),
  },

  probeHistory: {
    list: () => apiFetch<ProbeHistory[]>('/api/probe-history'),
    get: (id: string) => apiFetch<Record<string, unknown>>(`/api/probe-history/${id}`),
    delete: (id: string) => apiFetch<void>(`/api/probe-history/${id}`, { method: 'DELETE' }),
    shareUrl: (id: string) => `/probe/results/${id}`,
  },

  cost: {
    summary: (days?: number) => apiFetch<CostSummary>(`/api/cost/summary${days ? `?days=${days}` : ''}`),
    pricing: () => apiFetch<ModelPricing[]>('/api/cost/pricing'),
    addPricing: (body: object) => apiFetch<ModelPricing>('/api/cost/pricing', { method: 'POST', body: JSON.stringify(body) }),
    deletePricing: (id: string) => apiFetch<void>(`/api/cost/pricing/${id}`, { method: 'DELETE' }),
  },

  validateExports: {
    pythonUrl: (modelId: string) => `/api/models/${modelId}/validate/python`,
    githubActionsUrl: (modelId: string) => `/api/models/${modelId}/validate/github-actions`,
  },

  abTests: {
    list: () => apiFetch<ABTest[]>('/ab-tests'),
    create: (body: object) => apiFetch<ABTest>('/ab-tests', { method: 'POST', body: JSON.stringify(body) }),
    get: (id: string) => apiFetch<ABTest>(`/ab-tests/${id}`),
    winner: (id: string) => apiFetch<ABTestWinner[]>(`/ab-tests/${id}/winner`),
  },

  templates: {
    list: () => apiFetch<EvalTemplate[]>('/templates'),
    create: (body: object) => apiFetch<EvalTemplate>('/templates', { method: 'POST', body: JSON.stringify(body) }),
    delete: (id: string) => apiFetch<void>(`/templates/${id}`, { method: 'DELETE' }),
    launch: (id: string) => apiFetch<EvaluationRun>(`/templates/${id}/launch`, { method: 'POST' }),
  },

  loadProfile: {
    get: (modelId: string) => apiFetch<LoadProfile>(`/models/${modelId}/load-profile`),
    count: (modelId: string) => apiFetch<{ count: number }>(`/models/${modelId}/load-samples/count`),
  },

  search: (q: string) => apiFetch<SearchResults>(`/search?q=${encodeURIComponent(q)}`),

  sensitivity: (body: object) => apiFetch<SensitivityResult>('/playground/sensitivity', { method: 'POST', body: JSON.stringify(body) }),

  droplets: {
    list: () => apiFetch<GpuDroplet[]>('/droplets'),
    /** Catalog for the create form — fetched with the server's DO_API_TOKEN, not the user token */
    options: () => apiFetch<DropletOptions>('/droplets/options'),
    get: (id: string) => apiFetch<GpuDroplet>(`/droplets/${id}`),
    create: (body: DropletCreate) =>
      apiFetch<GpuDroplet>('/droplets', { method: 'POST', body: JSON.stringify(body) }),
    destroy: (id: string) =>
      apiFetch<GpuDroplet>(`/droplets/${id}/destroy`, { method: 'POST' }),
    delete: (id: string) =>
      apiFetch<void>(`/droplets/${id}`, { method: 'DELETE' }),
    /** SSE provisioning/teardown progress — use with EventSource directly */
    streamUrl: (id: string) => `/api/droplets/${id}/stream?api_key=${API_KEY}`,
  },

  deployments: {
    list: (dropletId?: string) =>
      apiFetch<Deployment[]>(`/deployments${dropletId ? `?droplet_id=${dropletId}` : ''}`),
    get: (id: string) => apiFetch<Deployment>(`/deployments/${id}`),
    create: (body: DeploymentCreate) =>
      apiFetch<Deployment>('/deployments', { method: 'POST', body: JSON.stringify(body) }),
    logs: (id: string, lines = 200) =>
      apiFetch<{ log_tail: string }>(`/deployments/${id}/logs?lines=${lines}`),
    health: (id: string) =>
      apiFetch<{ health: string }>(`/deployments/${id}/health`),
    /** SSE deploy progress — use with EventSource directly */
    streamUrl: (id: string) => `/api/deployments/${id}/stream?api_key=${API_KEY}`,
  },

  recipes: {
    engines: () => apiFetch<EngineInfo[]>('/recipes/engines'),
    models: (engine = 'vllm') => apiFetch<RecipeModel[]>(`/recipes/models?engine=${engine}`),
    resolve: (engine: string, model: string, dropletId: string) =>
      apiFetch<ResolvedRecipe>(
        `/recipes/resolve?engine=${engine}&model=${encodeURIComponent(model)}&droplet_id=${dropletId}`),
  },

  aiperf: {
    list: (deploymentId?: string) =>
      apiFetch<AiperfRun[]>(`/aiperf${deploymentId ? `?deployment_id=${deploymentId}` : ''}`),
    get: (id: string) => apiFetch<AiperfRun>(`/aiperf/${id}`),
    /** Up-front: is the tokenizer gated, and is a token already on file? */
    preflight: (deploymentId: string) =>
      apiFetch<{ model: string; port: number; gated: boolean; has_token: boolean }>(
        `/aiperf/preflight?deployment_id=${deploymentId}`),
    create: (body: AiperfRunCreate) =>
      apiFetch<AiperfRun>('/aiperf', { method: 'POST', body: JSON.stringify(body) }),
    /** Queue many saved configs against one deployment in a single request */
    batch: (body: AiperfBatchCreate) =>
      apiFetch<AiperfRun[]>('/aiperf/batch', { method: 'POST', body: JSON.stringify(body) }),
    /** Global persistent list of all runs — powers History */
    history: (limit = 200) => apiFetch<AiperfRun[]>(`/aiperf/history?limit=${limit}`),
    /** SSE benchmark progress — use with EventSource directly */
    streamUrl: (id: string) => `/api/aiperf/${id}/stream?api_key=${API_KEY}`,
    /** Saved benchmark configurations (named aiperf profiles) */
    configs: {
      list: () => apiFetch<AiperfConfig[]>('/aiperf/configs'),
      create: (body: AiperfConfigCreate) =>
        apiFetch<AiperfConfig>('/aiperf/configs', { method: 'POST', body: JSON.stringify(body) }),
      remove: (id: string) =>
        apiFetch<void>(`/aiperf/configs/${id}`, { method: 'DELETE' }),
    },
  },
}

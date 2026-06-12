/// <reference types="vite/client" />
import type {
  BenchmarkSuite, CategoryCount, ConnectionTestResult,
  EvaluationCreate, EvaluationRun,
  Model, ModelCreate,
  RunNote, SampleOutput,
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
}

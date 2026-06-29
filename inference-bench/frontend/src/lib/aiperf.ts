// Shared helpers for reading/summarizing aiperf benchmark runs. Used by the
// Benchmark History dashboard and the SLA Analysis page so the per-GPU
// normalization and metric extraction live in exactly one place.
import type { AiperfRun, AiperfMetric } from '../types'

export const n = (v: number | string | undefined): number | undefined =>
  (typeof v === 'number' ? v : undefined)

export const fmt = (v: number | undefined): string =>
  v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: 2 })

export const shortModel = (m: string): string => m.split('/').pop() || m

/** Read an arbitrary percentile (e.g. 'p50', 'p90', 'p99') off a latency metric. */
export const metricPct = (
  m: AiperfMetric | undefined, pct: string,
): number | undefined => (m ? n(m[pct]) : undefined)

export interface RunSummary {
  concurrency?: number
  requests?: number
  duration?: number
  reqPerSec?: number
  inPerGpu?: number
  outPerGpu?: number
  totalPerGpu?: number
  ttftP50?: number
  ttftP90?: number
  itlP50?: number
  itlP90?: number
  gpu: number
  gpuLabel: string
}

/** Collapse a run's raw metrics into the headline numbers, normalizing token
 *  throughput per-GPU using the droplet's GPU count. */
export function summarize(r: AiperfRun): RunSummary {
  const gpu = r.droplet_snapshot?.gpu_count || 1
  const concRaw = r.profile?.args?.find(a => a.flag === '--concurrency')?.value
  const conc = concRaw !== undefined && concRaw !== '' ? Number(concRaw) : NaN
  const inTps = n(r.metrics?.input_token_throughput?.value)
  const outTps = n(r.metrics?.output_token_throughput?.value)
  const total = inTps !== undefined && outTps !== undefined ? inTps + outTps : undefined
  const pg = (v: number | undefined) => (v === undefined ? undefined : v / gpu)
  const gpuLabel = r.droplet_snapshot?.gpu_count && r.droplet_snapshot?.gpu_model
    ? `${r.droplet_snapshot.gpu_count}× ${r.droplet_snapshot.gpu_model}`
    : (r.droplet_snapshot?.gpu_model || '—')
  return {
    concurrency: Number.isFinite(conc) ? conc : undefined,
    requests: n(r.metrics?.request_count?.value),
    duration: n(r.metrics?.benchmark_duration?.value),
    reqPerSec: n(r.metrics?.request_throughput?.value),
    inPerGpu: pg(inTps), outPerGpu: pg(outTps), totalPerGpu: pg(total),
    ttftP50: n(r.metrics?.time_to_first_token?.p50),
    ttftP90: n(r.metrics?.time_to_first_token?.p90),
    itlP50: n(r.metrics?.inter_token_latency?.p50),
    itlP90: n(r.metrics?.inter_token_latency?.p90),
    gpu, gpuLabel,
  }
}

export const seriesLabel = (r: AiperfRun): string =>
  `${shortModel(r.model)} · ${summarize(r).gpuLabel}`

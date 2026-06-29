import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { AiperfRun } from '../types'
import { n, fmt, shortModel, metricPct, summarize } from '../lib/aiperf'

// A sales-facing "what can we offer" view over our benchmark runs. No engine,
// region, or deployment config — just the numbers a customer conversation needs,
// split by GPU vendor (an AMD lead must run on AMD, and vice-versa).

type Vendor = 'NVIDIA' | 'AMD' | 'Other'
const vendorOf = (r: AiperfRun): Vendor => {
  const p = (r.droplet_snapshot?.gpu_platform || '').toUpperCase()
  return p === 'NVIDIA' ? 'NVIDIA' : p === 'AMD' ? 'AMD' : 'Other'
}
const VENDOR_STYLE: Record<Vendor, string> = {
  NVIDIA: 'bg-green-100 text-green-700',
  AMD: 'bg-red-100 text-red-700',
  Other: 'bg-gray-100 text-gray-600',
}

const ms = (v: number | undefined) => (v === undefined ? '—' : `${fmt(v)} ms`)
const intFmt = (v: number | undefined) =>
  v === undefined ? '—' : Math.round(v).toLocaleString()

interface RunStat {
  run: AiperfRun
  vendor: Vendor
  gpuLabel: string
  outTps?: number      // generation speed (output tokens/sec)
  rps?: number
  ttftP50?: number; ttftP90?: number; ttftP95?: number
  tpotP50?: number; tpotP90?: number; tpotP95?: number   // TPOT == inter-token latency
  isl?: number; osl?: number
  concurrency?: number
}

function statOf(r: AiperfRun): RunStat {
  const m = r.metrics || {}
  const s = summarize(r)
  const argNum = (flag: string) => {
    const v = r.profile?.args?.find(a => a.flag === flag)?.value
    const num = v !== undefined && v !== '' ? Number(v) : NaN
    return Number.isFinite(num) ? num : undefined
  }
  return {
    run: r,
    vendor: vendorOf(r),
    gpuLabel: s.gpuLabel,
    outTps: n(m.output_token_throughput?.value),
    rps: n(m.request_throughput?.value),
    ttftP50: metricPct(m.time_to_first_token, 'p50'),
    ttftP90: metricPct(m.time_to_first_token, 'p90'),
    ttftP95: metricPct(m.time_to_first_token, 'p95'),
    tpotP50: metricPct(m.inter_token_latency, 'p50'),
    tpotP90: metricPct(m.inter_token_latency, 'p90'),
    tpotP95: metricPct(m.inter_token_latency, 'p95'),
    isl: argNum('--isl'),
    osl: argNum('--osl'),
    concurrency: s.concurrency,
  }
}

interface Card {
  model: string
  vendor: Vendor
  best: RunStat
  runCount: number
}

export default function ModelPerformance() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<AiperfRun[]>([])
  const [loading, setLoading] = useState(true)
  const [vendor, setVendor] = useState<'Any' | Vendor>('Any')
  // Optional SLA targets (P99 — what enterprise contracts are written against).
  const [maxTtft, setMaxTtft] = useState('')
  const [maxTpot, setMaxTpot] = useState('')
  const [minTps, setMinTps] = useState('')

  useEffect(() => {
    api.aiperf.history(1000).then(rs => setRuns(rs.filter(r => r.status === 'completed')))
      .catch(() => {}).finally(() => setLoading(false))
  }, [])

  const sla = useMemo(() => {
    const num = (s: string) => { const v = Number(s); return s.trim() && Number.isFinite(v) && v > 0 ? v : undefined }
    return { ttft: num(maxTtft), tpot: num(maxTpot), tps: num(minTps) }
  }, [maxTtft, maxTpot, minTps])
  const anySla = sla.ttft !== undefined || sla.tpot !== undefined || sla.tps !== undefined

  // A run qualifies if it meets every set ceiling/floor. A missing metric that's
  // being gated disqualifies the run (we never quote an unverified number).
  const qualifies = (st: RunStat): boolean => {
    if (sla.ttft !== undefined && !(st.ttftP95 !== undefined && st.ttftP95 <= sla.ttft)) return false
    if (sla.tpot !== undefined && !(st.tpotP95 !== undefined && st.tpotP95 <= sla.tpot)) return false
    if (sla.tps !== undefined && !(st.outTps !== undefined && st.outTps >= sla.tps)) return false
    return true
  }

  // One card per (model, vendor): the best qualifying run by generation speed.
  const cards = useMemo<Card[]>(() => {
    const groups = new Map<string, RunStat[]>()
    runs.forEach(r => {
      const st = statOf(r)
      if (vendor !== 'Any' && st.vendor !== vendor) return
      const k = `${r.model}|${st.vendor}`
      if (!groups.has(k)) groups.set(k, [])
      groups.get(k)!.push(st)
    })
    const out: Card[] = []
    groups.forEach((stats, k) => {
      const eligible = stats.filter(qualifies)
      if (!eligible.length) return
      const best = eligible.reduce((a, b) => (b.outTps ?? -1) > (a.outTps ?? -1) ? b : a)
      out.push({ model: k.split('|')[0], vendor: best.vendor, best, runCount: stats.length })
    })
    return out.sort((a, b) => (b.best.outTps ?? -1) - (a.best.outTps ?? -1))
  }, [runs, vendor, sla])

  const vendorTabs: Array<'Any' | Vendor> = ['Any', 'NVIDIA', 'AMD']

  return (
    <div className="p-4 space-y-4 max-w-6xl">
      <div>
        <h1 className="text-base font-bold text-gray-800">Model Performance</h1>
        <p className="text-xs text-gray-500">
          What we can offer per model, from real benchmark runs. Enter target SLAs to see which models can meet them.
        </p>
      </div>

      {/* Controls */}
      <div className="card space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-600 font-medium w-16">Hardware</span>
          <div className="flex rounded-lg border border-do-grey-200 overflow-hidden">
            {vendorTabs.map(v => (
              <button key={v} onClick={() => setVendor(v)}
                className={`px-3 py-1 text-xs ${vendor === v ? 'bg-do-blue text-white' : 'bg-white text-gray-600 hover:bg-do-grey-100'}`}>
                {v === 'Any' ? 'Any vendor' : v}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-end gap-3 flex-wrap">
          <span className="text-[11px] text-gray-600 font-medium w-16 pb-1.5">Target SLA</span>
          <label className="block">
            <span className="text-[11px] text-gray-500">Time to first response (P95)</span>
            <div className="flex items-center gap-1">
              <input className="input text-xs w-24" inputMode="decimal" value={maxTtft}
                onChange={e => setMaxTtft(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="e.g. 200" />
              <span className="text-[11px] text-gray-400">ms</span>
            </div>
          </label>
          <label className="block">
            <span className="text-[11px] text-gray-500">Per-token latency · TPOT (P95)</span>
            <div className="flex items-center gap-1">
              <input className="input text-xs w-24" inputMode="decimal" value={maxTpot}
                onChange={e => setMaxTpot(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="e.g. 25" />
              <span className="text-[11px] text-gray-400">ms</span>
            </div>
          </label>
          <label className="block">
            <span className="text-[11px] text-gray-500">Min generation speed</span>
            <div className="flex items-center gap-1">
              <input className="input text-xs w-28" inputMode="decimal" value={minTps}
                onChange={e => setMinTps(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="e.g. 1000" />
              <span className="text-[11px] text-gray-400">tok/s</span>
            </div>
          </label>
          {anySla && (
            <button onClick={() => { setMaxTtft(''); setMaxTpot(''); setMinTps('') }}
              className="text-[11px] text-do-blue hover:underline pb-1.5">Clear SLA</button>
          )}
        </div>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {!loading && runs.length === 0 && (
        <p className="text-sm text-gray-600">
          No benchmark data yet.{' '}
          <button onClick={() => navigate('/benchmark/runs')} className="text-do-blue hover:underline">Run a benchmark →</button>
        </p>
      )}

      {/* Headline answer to "do we have a model that meets these SLAs?" */}
      {!loading && anySla && (
        <p className="text-sm font-semibold text-gray-800">
          {cards.length > 0
            ? `✅ ${cards.length} model${cards.length === 1 ? '' : 's'} can meet your SLA${vendor !== 'Any' ? ` on ${vendor}` : ''}.`
            : `No benchmarked model meets that SLA${vendor !== 'Any' ? ` on ${vendor}` : ''} yet. Try relaxing a target or another vendor.`}
        </p>
      )}

      {/* Capability cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {cards.map(c => {
          const b = c.best
          return (
            <div key={`${c.model}|${c.vendor}`} className="card flex flex-col gap-2.5">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-bold text-gray-800 leading-tight" title={c.model}>{shortModel(c.model)}</h3>
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${VENDOR_STYLE[c.vendor]}`}>{c.vendor}</span>
              </div>
              <p className="text-[11px] text-gray-500 -mt-1">on {b.gpuLabel}</p>

              {/* Headline: generation speed */}
              <div>
                <p className="text-2xl font-bold text-gray-900 leading-none">{intFmt(b.outTps)}<span className="text-sm font-medium text-gray-500"> tok/s</span></p>
                <p className="text-[11px] text-gray-500 mt-0.5">generation speed · {fmt(b.rps)} req/s</p>
              </div>

              {/* Latency + workload spec */}
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div className="bg-do-grey-100 rounded p-2">
                  <p className="text-gray-500">Time to first response</p>
                  <p className="text-gray-800 font-mono mt-0.5">P50 {ms(b.ttftP50)}</p>
                  <p className="text-gray-800 font-mono">P90 {ms(b.ttftP90)}</p>
                  <p className="text-gray-800 font-mono">P95 {ms(b.ttftP95)}</p>
                </div>
                <div className="bg-do-grey-100 rounded p-2">
                  <p className="text-gray-500">Per-token latency (TPOT)</p>
                  <p className="text-gray-800 font-mono mt-0.5">P50 {ms(b.tpotP50)}</p>
                  <p className="text-gray-800 font-mono">P90 {ms(b.tpotP90)}</p>
                  <p className="text-gray-800 font-mono">P95 {ms(b.tpotP95)}</p>
                </div>
              </div>

              <div className="flex items-center justify-between text-[11px] text-gray-500">
                <span>{b.isl !== undefined && b.osl !== undefined ? `${intFmt(b.isl)}→${intFmt(b.osl)} tokens` : 'workload varies'}</span>
                <span>up to {b.concurrency ?? '—'} concurrent</span>
              </div>

              <div className="flex items-center justify-between border-t border-do-grey-100 pt-1.5">
                <span className="text-[10px] text-gray-400">Best of {c.runCount} run{c.runCount === 1 ? '' : 's'}</span>
                {anySla && <span className="text-[10px] font-semibold text-green-600">✓ Meets SLA</span>}
                <button onClick={() => navigate(`/benchmark/runs?run=${b.run.id}`)} className="text-[10px] text-do-blue hover:underline">details</button>
              </div>
            </div>
          )
        })}
      </div>

      {!loading && runs.length > 0 && cards.length === 0 && !anySla && (
        <p className="text-sm text-gray-600">No completed runs for this vendor.</p>
      )}
    </div>
  )
}

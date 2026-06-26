import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { api } from '../api'
import type { AiperfRun } from '../types'

const STATUS_TEXT: Record<string, string> = {
  queued: 'text-yellow-600', running: 'text-yellow-600', completed: 'text-green-600', failed: 'text-red-600',
}
// Distinct series colors (model · GPU · engine).
const COLORS = ['#0080FF', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16']

const n = (v: number | string | undefined) => (typeof v === 'number' ? v : undefined)
const fmt = (v: number | undefined) =>
  v === undefined ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: 2 })

function summarize(r: AiperfRun) {
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
const seriesLabel = (r: AiperfRun) => `${r.model} · ${summarize(r).gpuLabel} · ${r.engine}`

// ── client-side export (the page already holds the full list) ──────────────────
function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}
const csvCell = (v: unknown) => {
  const s = v === undefined || v === null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
function exportCsv(runs: AiperfRun[]) {
  const cols = ['date', 'model', 'engine', 'gpu', 'region', 'concurrency', 'requests', 'duration_s',
    'req_per_s', 'input_tok_s_per_gpu', 'output_tok_s_per_gpu', 'total_tok_s_per_gpu',
    'ttft_p50_ms', 'ttft_p90_ms', 'itl_p50_ms', 'itl_p90_ms', 'status']
  const r2 = (v: number | undefined) => (v === undefined ? '' : Math.round(v * 100) / 100)
  const lines = [cols.join(',')]
  runs.forEach(r => {
    const s = summarize(r)
    lines.push([
      r.created_at || '', r.model, r.engine, s.gpuLabel, r.droplet_snapshot?.region || '',
      s.concurrency ?? '', s.requests ?? '', s.duration ?? '', s.reqPerSec ?? '',
      r2(s.inPerGpu), r2(s.outPerGpu), r2(s.totalPerGpu),
      s.ttftP50 ?? '', s.ttftP90 ?? '', s.itlP50 ?? '', s.itlP90 ?? '', r.status,
    ].map(csvCell).join(','))
  })
  download('benchmark-history.csv', lines.join('\n'), 'text/csv')
}

export default function BenchmarkHistory() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<AiperfRun[]>([])
  const [loading, setLoading] = useState(true)
  const [fModel, setFModel] = useState('')
  const [fEngine, setFEngine] = useState('')
  const [fStatus, setFStatus] = useState('')

  useEffect(() => { api.aiperf.history().then(setRuns).catch(() => {}).finally(() => setLoading(false)) }, [])

  const models = useMemo(() => [...new Set(runs.map(r => r.model))].sort(), [runs])
  const engines = useMemo(() => [...new Set(runs.map(r => r.engine))].sort(), [runs])

  const filtered = useMemo(() => runs.filter(r =>
    (!fModel || r.model === fModel) && (!fEngine || r.engine === fEngine) && (!fStatus || r.status === fStatus)
  ), [runs, fModel, fEngine, fStatus])

  // Charts: completed runs that have a concurrency on the x-axis.
  const plotted = useMemo(() => filtered.filter(r => r.status === 'completed' && summarize(r).concurrency !== undefined), [filtered])
  const series = useMemo(() => [...new Set(plotted.map(seriesLabel))], [plotted])
  const droppedNoConc = filtered.filter(r => r.status === 'completed' && summarize(r).concurrency === undefined).length

  // Pivot to {concurrency, [series]: value} rows for multi-line charts.
  const pivot = (pick: (s: ReturnType<typeof summarize>) => number | undefined) => {
    const byConc = new Map<number, Record<string, number>>()
    plotted.forEach(r => {
      const s = summarize(r)
      const row = byConc.get(s.concurrency!) || { concurrency: s.concurrency! }
      const v = pick(s)
      if (v !== undefined) row[seriesLabel(r)] = v
      byConc.set(s.concurrency!, row)
    })
    return [...byConc.values()].sort((a, b) => a.concurrency - b.concurrency)
  }

  const charts: Array<{ title: string; unit: string; data: Record<string, number>[] }> = [
    { title: 'Output tok/s/GPU vs concurrency', unit: '', data: pivot(s => s.outPerGpu) },
    { title: 'Requests/s vs concurrency', unit: '', data: pivot(s => s.reqPerSec) },
    { title: 'TTFT P50 (ms) vs concurrency', unit: 'ms', data: pivot(s => s.ttftP50) },
    { title: 'ITL P50 (ms) vs concurrency', unit: 'ms', data: pivot(s => s.itlP50) },
  ]

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-bold text-gray-800">Benchmark History</h1>
          <p className="text-xs text-gray-500">{runs.length} run{runs.length === 1 ? '' : 's'} · includes destroyed droplets</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => exportCsv(filtered)} disabled={!filtered.length} className="btn-secondary text-xs disabled:opacity-50">⭳ CSV</button>
          <button onClick={() => download('benchmark-history.json', JSON.stringify(filtered, null, 2), 'application/json')} disabled={!filtered.length} className="btn-secondary text-xs disabled:opacity-50">⭳ JSON</button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <select className="input max-w-xs text-xs" value={fModel} onChange={e => setFModel(e.target.value)}>
          <option value="">All models</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select className="input w-36 text-xs" value={fEngine} onChange={e => setFEngine(e.target.value)}>
          <option value="">All engines</option>
          {engines.map(e => <option key={e} value={e}>{e}</option>)}
        </select>
        <select className="input w-36 text-xs" value={fStatus} onChange={e => setFStatus(e.target.value)}>
          <option value="">All statuses</option>
          {['completed', 'failed', 'running', 'queued'].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        {(fModel || fEngine || fStatus) && (
          <button onClick={() => { setFModel(''); setFEngine(''); setFStatus('') }} className="text-xs text-do-blue hover:underline">Clear</button>
        )}
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {!loading && runs.length === 0 && <p className="text-sm text-gray-600">No benchmark runs yet.</p>}

      {/* Dashboards */}
      {plotted.length > 0 && (
        <>
          <p className="text-[11px] text-gray-500">
            Sweeps grouped by <span className="font-medium">model · GPU · engine</span> ({series.length} series, {plotted.length} run{plotted.length === 1 ? '' : 's'}).
            {' '}Tip: filter to one model for a clean Pareto curve.
            {droppedNoConc > 0 && <span className="text-amber-600"> {droppedNoConc} completed run(s) without a --concurrency value are excluded from charts.</span>}
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {charts.map(c => (
              <div key={c.title} className="card">
                <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">{c.title}</p>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={c.data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="concurrency" type="number" tick={{ fill: '#6B7280', fontSize: 10 }}
                      label={{ value: 'Concurrency', position: 'insideBottom', offset: -3, fill: '#9CA3AF', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} unit={c.unit} width={48} />
                    <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }} />
                    {series.length > 1 && <Legend wrapperStyle={{ fontSize: 9 }} />}
                    {series.map((s, i) => (
                      <Line key={s} type="monotone" dataKey={s} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot connectNulls />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Global table */}
      {filtered.length > 0 && (
        <div className="card overflow-x-auto">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">All runs</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 text-left">
                <th className="py-1 pr-3 font-medium">Date</th>
                <th className="py-1 pr-3 font-medium">Model</th>
                <th className="py-1 pr-3 font-medium">Engine</th>
                <th className="py-1 pr-3 font-medium">GPU</th>
                <th className="py-1 pr-3 font-medium">Region</th>
                <th className="py-1 px-2 font-medium text-right">Conc.</th>
                <th className="py-1 px-2 font-medium text-right">Req/s</th>
                <th className="py-1 px-2 font-medium text-right">Out tok/s/GPU</th>
                <th className="py-1 px-2 font-medium text-right">TTFT p50</th>
                <th className="py-1 pl-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => {
                const s = summarize(r)
                return (
                  <tr key={r.id} onClick={() => navigate(`/benchmark/runs?run=${r.id}`)}
                    className="border-t border-do-grey-100 hover:bg-do-grey-100 cursor-pointer">
                    <td className="py-1 pr-3 text-gray-600 whitespace-nowrap">{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</td>
                    <td className="py-1 pr-3 text-gray-800 max-w-[16rem] truncate" title={r.model}>{r.model}</td>
                    <td className="py-1 pr-3 text-gray-600">{r.engine}</td>
                    <td className="py-1 pr-3 text-gray-600 whitespace-nowrap">{s.gpuLabel}</td>
                    <td className="py-1 pr-3 text-gray-600">{r.droplet_snapshot?.region || '—'}</td>
                    <td className="py-1 px-2 text-right font-mono text-gray-700">{s.concurrency ?? '—'}</td>
                    <td className="py-1 px-2 text-right font-mono text-gray-700">{fmt(s.reqPerSec)}</td>
                    <td className="py-1 px-2 text-right font-mono text-gray-700">{fmt(s.outPerGpu)}</td>
                    <td className="py-1 px-2 text-right font-mono text-gray-700">{fmt(s.ttftP50)}</td>
                    <td className={`py-1 pl-2 ${STATUS_TEXT[r.status] || 'text-gray-500'}`}>{r.status}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

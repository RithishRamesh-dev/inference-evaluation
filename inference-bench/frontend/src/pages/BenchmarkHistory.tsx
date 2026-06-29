import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { api } from '../api'
import type { AiperfRun } from '../types'
import { summarize, seriesLabel, fmt, shortModel, type RunSummary } from '../lib/aiperf'

const STATUS_TEXT: Record<string, string> = {
  queued: 'text-yellow-600', running: 'text-yellow-600', completed: 'text-green-600', failed: 'text-red-600',
}
const COLORS = ['#0080FF', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899', '#84cc16']

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

const TERMINAL = ['completed', 'failed']

export default function BenchmarkHistory() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<AiperfRun[]>([])
  const [loading, setLoading] = useState(true)
  const [fModel, setFModel] = useState('')
  const [fEngine, setFEngine] = useState('')
  const [fStatus, setFStatus] = useState('')
  // Archiving: `runs` is always the active set (archived runs excluded), so the
  // dashboards/charts stay decluttered. Archived runs live in their own section.
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [archived, setArchived] = useState<AiperfRun[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = () => api.aiperf.history(200, false).then(setRuns).catch(() => {})
  const loadArchived = () => api.aiperf.history(500, true)
    .then(rs => setArchived(rs.filter(r => r.hidden))).catch(() => {})
  useEffect(() => { load().finally(() => setLoading(false)) }, [])
  useEffect(() => { if (showArchived) loadArchived() }, [showArchived])

  // Hide (or restore) finished runs, then refresh both views.
  const setHidden = async (ids: string[], hidden: boolean) => {
    if (!ids.length || busy) return
    setBusy(true)
    try {
      await api.aiperf.archive(ids, hidden)
      setSel(new Set())
      await Promise.all([load(), showArchived ? loadArchived() : Promise.resolve()])
    } catch { /* ignore */ } finally { setBusy(false) }
  }

  const models = useMemo(() => [...new Set(runs.map(r => r.model))].sort(), [runs])
  const engines = useMemo(() => [...new Set(runs.map(r => r.engine))].sort(), [runs])
  const colorOf = useMemo(() => {
    const map: Record<string, string> = {}
    models.forEach((m, i) => { map[m] = COLORS[i % COLORS.length] })
    return (m: string) => map[m] || '#9CA3AF'
  }, [models])

  const filtered = useMemo(() => runs.filter(r =>
    (!fModel || r.model === fModel) && (!fEngine || r.engine === fEngine) && (!fStatus || r.status === fStatus)
  ), [runs, fModel, fEngine, fStatus])
  const completed = useMemo(() => filtered.filter(r => r.status === 'completed'), [filtered])

  // Only finished runs can be archived (an in-flight run still has a live agent job).
  const selectable = useMemo(() => filtered.filter(r => TERMINAL.includes(r.status)), [filtered])
  const failedIds = useMemo(() => filtered.filter(r => r.status === 'failed').map(r => r.id), [filtered])
  const allSelected = selectable.length > 0 && selectable.every(r => sel.has(r.id))
  const toggleSel = (id: string) =>
    setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll = () =>
    setSel(allSelected ? new Set() : new Set(selectable.map(r => r.id)))

  // ── stats ──
  const best = (pick: (s: RunSummary) => number | undefined, mode: 'max' | 'min') => {
    const vals = completed.map(r => pick(summarize(r))).filter((v): v is number => v !== undefined)
    if (!vals.length) return undefined
    return mode === 'max' ? Math.max(...vals) : Math.min(...vals)
  }
  const stats = [
    { label: 'Runs', value: filtered.length },
    { label: 'Models', value: new Set(completed.map(r => r.model)).size },
    { label: 'Best output tok/s/GPU', value: fmt(best(s => s.outPerGpu, 'max')) },
    { label: 'Best TTFT p50 (ms)', value: fmt(best(s => s.ttftP50, 'min')) },
  ]

  // ── per-run comparison bars (works at any single concurrency) ──
  const barRuns = useMemo(() => completed.slice(0, 15).reverse(), [completed])  // oldest→newest of 15 most recent
  const barData = barRuns.map(r => {
    const s = summarize(r)
    return {
      id: r.id, model: r.model, conc: s.concurrency,
      label: r.created_at ? new Date(r.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
      out: s.outPerGpu, req: s.reqPerSec, ttft: s.ttftP50, itl: s.itlP50,
    }
  })
  const barModels = [...new Set(barRuns.map(r => r.model))]
  const barPanels: Array<{ title: string; key: keyof typeof barData[number]; unit: string }> = [
    { title: 'Output tok/s/GPU', key: 'out', unit: '' },
    { title: 'Requests/s', key: 'req', unit: '' },
    { title: 'TTFT P50 (ms)', key: 'ttft', unit: 'ms' },
    { title: 'ITL P50 (ms)', key: 'itl', unit: 'ms' },
  ]

  // ── concurrency sweeps (only meaningful when a model was run at ≥2 levels) ──
  const plotted = useMemo(() => completed.filter(r => summarize(r).concurrency !== undefined), [completed])
  const sweepSeries = useMemo(() => {
    const m = new Map<string, Set<number>>()
    plotted.forEach(r => {
      const k = seriesLabel(r)
      if (!m.has(k)) m.set(k, new Set())
      m.get(k)!.add(summarize(r).concurrency!)
    })
    return [...m.entries()].filter(([, set]) => set.size >= 2).map(([k]) => k)
  }, [plotted])
  const pivot = (pick: (s: RunSummary) => number | undefined) => {
    const byConc = new Map<number, Record<string, number>>()
    plotted.forEach(r => {
      const k = seriesLabel(r); if (!sweepSeries.includes(k)) return
      const s = summarize(r)
      const row = byConc.get(s.concurrency!) || { concurrency: s.concurrency! }
      const v = pick(s); if (v !== undefined) row[k] = v
      byConc.set(s.concurrency!, row)
    })
    return [...byConc.values()].sort((a, b) => a.concurrency - b.concurrency)
  }
  const sweepCharts = [
    { title: 'Output tok/s/GPU vs concurrency', unit: '', data: pivot(s => s.outPerGpu) },
    { title: 'Requests/s vs concurrency', unit: '', data: pivot(s => s.reqPerSec) },
    { title: 'TTFT P50 (ms) vs concurrency', unit: 'ms', data: pivot(s => s.ttftP50) },
    { title: 'ITL P50 (ms) vs concurrency', unit: 'ms', data: pivot(s => s.itlP50) },
  ]

  const BarTip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const d = payload[0].payload
    return (
      <div className="bg-white border border-do-grey-200 rounded p-2 text-[11px] shadow-sm">
        <p className="font-medium text-gray-800 max-w-[18rem] truncate">{d.model}</p>
        <p className="text-gray-500">c={d.conc ?? '—'} · {fmt(payload[0].value as number)}</p>
      </div>
    )
  }

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

      {/* Stats */}
      {completed.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {stats.map(s => (
            <div key={s.label} className="card text-center">
              <p className="text-xl font-bold text-gray-800">{s.value}</p>
              <p className="text-[11px] text-gray-500 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Per-run comparison (default — works at a single concurrency) */}
      {barData.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <p className="text-[11px] text-gray-500">Comparing the {barData.length} most recent completed run{barData.length === 1 ? '' : 's'} (each bar = one run).</p>
            <div className="flex flex-wrap gap-x-3 gap-y-1 justify-end">
              {barModels.map(m => (
                <span key={m} className="flex items-center gap-1 text-[10px] text-gray-600">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ background: colorOf(m) }} />{shortModel(m)}
                </span>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {barPanels.map(p => (
              <div key={p.key} className="card">
                <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">{p.title}</p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={barData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis dataKey="label" tick={{ fill: '#6B7280', fontSize: 9 }} interval={0} angle={-30} textAnchor="end" height={42} />
                    <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} unit={p.unit} width={46} />
                    <Tooltip content={<BarTip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
                    <Bar dataKey={p.key} radius={[3, 3, 0, 0]}>
                      {barData.map(d => <Cell key={d.id} fill={colorOf(d.model)} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Concurrency sweeps — only when a model ran at ≥2 concurrency levels */}
      {sweepSeries.length > 0 && (
        <>
          <p className="text-[11px] text-gray-500 pt-1">
            Concurrency sweeps · {sweepSeries.length} series at ≥2 concurrency levels. Filter to one model for a clean Pareto curve.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {sweepCharts.map(c => (
              <div key={c.title} className="card">
                <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">{c.title}</p>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={c.data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="concurrency" type="number" tick={{ fill: '#6B7280', fontSize: 10 }}
                      label={{ value: 'Concurrency', position: 'insideBottom', offset: -3, fill: '#9CA3AF', fontSize: 10 }} />
                    <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} unit={c.unit} width={48} />
                    <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }} />
                    {sweepSeries.length > 1 && <Legend wrapperStyle={{ fontSize: 9 }} />}
                    {sweepSeries.map((s, i) => (
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
          <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">All runs</p>
            <div className="flex items-center gap-2">
              {sel.size > 0 && (
                <button onClick={() => setHidden([...sel], true)} disabled={busy}
                  className="btn-secondary text-xs disabled:opacity-50">
                  🗄 Archive {sel.size} selected
                </button>
              )}
              {failedIds.length > 0 && (
                <button onClick={() => setHidden(failedIds, true)} disabled={busy}
                  className="btn-secondary text-xs disabled:opacity-50" title="Archive all failed runs in the current filter">
                  Archive {failedIds.length} failed
                </button>
              )}
            </div>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 text-left">
                <th className="py-1 pr-2 w-6">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll}
                    disabled={selectable.length === 0} title="Select all finished runs in view" />
                </th>
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
                const canSelect = TERMINAL.includes(r.status)
                return (
                  <tr key={r.id} onClick={() => navigate(`/benchmark/runs?run=${r.id}`)}
                    className={`border-t border-do-grey-100 hover:bg-do-grey-100 cursor-pointer ${sel.has(r.id) ? 'bg-blue-50' : ''}`}>
                    <td className="py-1 pr-2" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={sel.has(r.id)} disabled={!canSelect}
                        onChange={() => toggleSel(r.id)} title={canSelect ? '' : 'Only finished runs can be archived'} />
                    </td>
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

      {/* Archived runs — hidden from the dashboards above; restore as needed */}
      <div>
        <button onClick={() => setShowArchived(v => !v)} className="text-xs text-do-blue hover:underline">
          {showArchived ? '▾ Hide archived' : '▸ Show archived runs'}
        </button>
        {showArchived && (
          <div className="card overflow-x-auto mt-2">
            {archived.length === 0 ? (
              <p className="text-xs text-gray-500">No archived runs.</p>
            ) : (
              <>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider">Archived · {archived.length}</p>
                  <button onClick={() => setHidden(archived.map(r => r.id), false)} disabled={busy}
                    className="text-xs text-do-blue hover:underline disabled:opacity-50">Restore all</button>
                </div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 text-left">
                      <th className="py-1 pr-3 font-medium">Date</th>
                      <th className="py-1 pr-3 font-medium">Model</th>
                      <th className="py-1 pr-3 font-medium">GPU</th>
                      <th className="py-1 px-2 font-medium text-right">Conc.</th>
                      <th className="py-1 pl-2 font-medium">Status</th>
                      <th className="py-1 pl-2 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {archived.map(r => {
                      const s = summarize(r)
                      return (
                        <tr key={r.id} className="border-t border-do-grey-100 text-gray-500">
                          <td className="py-1 pr-3 whitespace-nowrap">{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</td>
                          <td className="py-1 pr-3 max-w-[16rem] truncate" title={r.model}>{r.model}</td>
                          <td className="py-1 pr-3 whitespace-nowrap">{s.gpuLabel}</td>
                          <td className="py-1 px-2 text-right font-mono">{s.concurrency ?? '—'}</td>
                          <td className={`py-1 pl-2 ${STATUS_TEXT[r.status] || 'text-gray-500'}`}>{r.status}</td>
                          <td className="py-1 pl-2">
                            <button onClick={() => setHidden([r.id], false)} disabled={busy}
                              className="text-do-blue hover:underline disabled:opacity-50">Restore</button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

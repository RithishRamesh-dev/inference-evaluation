import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, Label,
} from 'recharts'
import { api } from '../api'
import type { AiperfRun } from '../types'
import { summarize, shortModel, fmt, n } from '../lib/aiperf'

const TERMINAL = ['completed', 'failed']
const BLUE = '#0080FF'

// Compact ISL/OSL: 1000 -> 1k, 500 -> 500, 8000 -> 8k.
const kfmt = (v?: number) =>
  v === undefined ? '?' : (v >= 1000 && v % 1000 === 0 ? `${v / 1000}k` : String(v))

const argNum = (r: AiperfRun, flag: string): number | undefined => {
  const v = r.profile?.args?.find(a => a.flag === flag)?.value
  const x = v !== undefined && v !== '' ? Number(v) : NaN
  return Number.isFinite(x) ? x : undefined
}
// Tensor-parallel size: from the deployment's server args, else the GPU count.
const tpOf = (r: AiperfRun): number | undefined => {
  const a = (r.deployment_snapshot?.server_args || [])
    .find(x => x.flag === '--tensor-parallel-size' || x.flag === '-tp')
  const v = a ? Number(a.value) : NaN
  return Number.isFinite(v) ? v : r.droplet_snapshot?.gpu_count
}

interface Row {
  r: AiperfRun
  engine: string
  model: string
  isl?: number; osl?: number
  conc?: number
  tp?: number
  gpuLabel: string
  gpuCount: number
  total?: number      // total tok/s (input + output)
  outTps?: number     // output tok/s
  interac?: number    // tokens/sec per user = 1000 / TPOT
  tpot?: number       // mean inter-token latency (ms)
  ttft?: number       // mean time to first token (ms)
  date: string | null
  status: string
}

function rowOf(r: AiperfRun): Row {
  const m = r.metrics || {}
  const s = summarize(r)
  const inT = n(m.input_token_throughput?.value)
  const outT = n(m.output_token_throughput?.value)
  const total = inT !== undefined && outT !== undefined ? inT + outT : undefined
  const tpot = n(m.inter_token_latency?.avg)
  const ttft = n(m.time_to_first_token?.avg)
  return {
    r, engine: r.engine, model: r.model,
    isl: argNum(r, '--isl'), osl: argNum(r, '--osl'),
    conc: s.concurrency, tp: tpOf(r), gpuLabel: s.gpuLabel, gpuCount: s.gpu,
    total, outTps: outT, interac: tpot ? 1000 / tpot : undefined, tpot, ttft,
    date: r.created_at, status: r.status,
  }
}

// Performance chart: pick a Y metric (X is always concurrency).
const PERF_METRICS = [
  { key: 'total', label: 'Total throughput (tok/s)', unit: '' },
  { key: 'outTps', label: 'Output throughput (tok/s)', unit: '' },
  { key: 'tpot', label: 'TPOT (ms)', unit: 'ms' },
  { key: 'ttft', label: 'TTFT (ms)', unit: 'ms' },
] as const
type PerfKey = typeof PERF_METRICS[number]['key']

export default function BenchmarkHistory() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<AiperfRun[]>([])
  const [loading, setLoading] = useState(true)

  // Global filters.
  const [fEngine, setFEngine] = useState('')
  const [fModel, setFModel] = useState('')
  const [fIslOsl, setFIslOsl] = useState('')
  const [fConc, setFConc] = useState('')
  const [fGpu, setFGpu] = useState('')

  // Visualizers.
  const [tab, setTab] = useState<'performance' | 'tvl'>('performance')
  const [perfMetric, setPerfMetric] = useState<PerfKey>('total')
  const [tvlTput, setTvlTput] = useState<'total' | 'outTps'>('total')
  const [tvlLat, setTvlLat] = useState<'tpot' | 'ttft'>('tpot')

  // Archiving (kept from the prior design).
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [archived, setArchived] = useState<AiperfRun[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = () => api.aiperf.history(200, false).then(setRuns).catch(() => {})
  const loadArchived = () => api.aiperf.history(500, true)
    .then(rs => setArchived(rs.filter(r => r.hidden))).catch(() => {})
  useEffect(() => { load().finally(() => setLoading(false)) }, [])
  useEffect(() => { if (showArchived) loadArchived() }, [showArchived])

  const setHidden = async (ids: string[], hidden: boolean) => {
    if (!ids.length || busy) return
    setBusy(true)
    try {
      await api.aiperf.archive(ids, hidden)
      setSel(new Set())
      await Promise.all([load(), showArchived ? loadArchived() : Promise.resolve()])
    } catch { /* ignore */ } finally { setBusy(false) }
  }

  const allRows = useMemo(() => runs.map(rowOf), [runs])

  // Filter option lists (from completed runs — the benchmarkable data).
  const completedRows = useMemo(() => allRows.filter(r => r.status === 'completed'), [allRows])
  const opt = <T,>(pick: (r: Row) => T | undefined) =>
    [...new Set(completedRows.map(pick).filter((x): x is T => x !== undefined && x !== ''))]
  const engines = useMemo(() => opt(r => r.engine).sort(), [completedRows])
  const models = useMemo(() => opt(r => r.model).sort(), [completedRows])
  const islOsls = useMemo(() => opt(r => r.isl !== undefined && r.osl !== undefined ? `${r.isl}/${r.osl}` : undefined)
    .sort((a, b) => parseInt(a) - parseInt(b)), [completedRows])
  const concs = useMemo(() => opt(r => r.conc).sort((a, b) => a - b), [completedRows])
  const gpus = useMemo(() => opt(r => r.gpuLabel && r.gpuLabel !== '—' ? r.gpuLabel : undefined).sort(), [completedRows])

  const match = (r: Row) =>
    (!fEngine || r.engine === fEngine) && (!fModel || r.model === fModel)
    && (!fIslOsl || (r.isl !== undefined && r.osl !== undefined && `${r.isl}/${r.osl}` === fIslOsl))
    && (!fConc || r.conc === Number(fConc)) && (!fGpu || r.gpuLabel === fGpu)

  const filtered = useMemo(() => allRows.filter(match),
    [allRows, fEngine, fModel, fIslOsl, fConc, fGpu])
  const completed = useMemo(() => filtered.filter(r => r.status === 'completed'), [filtered])
  const failedIds = useMemo(() => filtered.filter(r => r.status === 'failed').map(r => r.r.id), [filtered])
  const anyFilter = !!(fEngine || fModel || fIslOsl || fConc || fGpu)

  // Headlining stats.
  const peakTotal = useMemo(() => {
    const v = completed.map(r => r.total).filter((x): x is number => x !== undefined)
    return v.length ? Math.max(...v) : undefined
  }, [completed])
  const bestTpot = useMemo(() => {
    const v = completed.map(r => r.tpot).filter((x): x is number => x !== undefined)
    return v.length ? Math.min(...v) : undefined
  }, [completed])
  const bestTtft = useMemo(() => {
    const v = completed.map(r => r.ttft).filter((x): x is number => x !== undefined)
    return v.length ? Math.min(...v) : undefined
  }, [completed])

  // One run per concurrency (latest) → a clean sweep for both charts.
  const sweep = useMemo(() => {
    const byConc = new Map<number, Row>()
    completed.forEach(r => {
      if (r.conc === undefined) return
      const ex = byConc.get(r.conc)
      const newer = r.date && (!ex?.date || Date.parse(r.date) > Date.parse(ex.date))
      if (!ex || newer) byConc.set(r.conc, r)
    })
    return [...byConc.values()].sort((a, b) => a.conc! - b.conc!)
  }, [completed])

  const perfData = sweep
    .map(r => ({ conc: r.conc!, value: r[perfMetric] as number | undefined }))
    .filter(d => d.value !== undefined)
  const perfCfg = PERF_METRICS.find(m => m.key === perfMetric)!

  const tvlData = sweep
    .map(r => ({ conc: r.conc!, x: r[tvlLat] as number | undefined, y: r[tvlTput] as number | undefined }))
    .filter(d => d.x !== undefined && d.y !== undefined)
    .sort((a, b) => (a.x as number) - (b.x as number))

  // Detail table: completed runs, sorted by concurrency.
  const tableRows = useMemo(() => [...completed].sort((a, b) => (a.conc ?? 0) - (b.conc ?? 0)), [completed])
  const selectable = tableRows  // all completed are archivable
  const allSelected = selectable.length > 0 && selectable.every(r => sel.has(r.r.id))
  const toggleSel = (id: string) => setSel(s => { const n2 = new Set(s); n2.has(id) ? n2.delete(id) : n2.add(id); return n2 })
  const toggleAll = () => setSel(allSelected ? new Set() : new Set(selectable.map(r => r.r.id)))

  const statCards = [
    { label: 'Peak total throughput', value: peakTotal !== undefined ? `${fmt(peakTotal)}` : '—', sub: 'tok/s' },
    { label: 'Best TPOT', value: bestTpot !== undefined ? `${fmt(bestTpot)}` : '—', sub: 'ms (lowest)' },
    { label: 'Best TTFT', value: bestTtft !== undefined ? `${fmt(bestTtft)}` : '—', sub: 'ms (lowest)' },
  ]

  const Filter = ({ label, value, set, options, fmtOpt }: {
    label: string; value: string; set: (v: string) => void; options: (string | number)[]; fmtOpt?: (o: string | number) => string
  }) => (
    <select className="input text-xs w-auto" value={value} onChange={e => set(e.target.value)}>
      <option value="">{label}</option>
      {options.map(o => <option key={String(o)} value={String(o)}>{fmtOpt ? fmtOpt(o) : String(o)}</option>)}
    </select>
  )

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-base font-bold text-gray-800">Benchmark History</h1>
        <p className="text-xs text-gray-500">{runs.length} run{runs.length === 1 ? '' : 's'} · includes destroyed droplets</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <Filter label="All engines" value={fEngine} set={setFEngine} options={engines} />
        <Filter label="All models" value={fModel} set={setFModel} options={models} fmtOpt={o => shortModel(String(o))} />
        <Filter label="All ISL/OSL" value={fIslOsl} set={setFIslOsl} options={islOsls}
          fmtOpt={o => { const [i, os] = String(o).split('/'); return `${kfmt(Number(i))}/${kfmt(Number(os))}` }} />
        <Filter label="All concurrency" value={fConc} set={setFConc} options={concs} />
        <Filter label="All GPUs" value={fGpu} set={setFGpu} options={gpus} />
        {anyFilter && (
          <button onClick={() => { setFEngine(''); setFModel(''); setFIslOsl(''); setFConc(''); setFGpu('') }}
            className="text-xs text-do-blue hover:underline">Clear</button>
        )}
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {!loading && runs.length === 0 && (
        <p className="text-sm text-gray-600">
          No benchmark runs yet.{' '}
          <button onClick={() => navigate('/benchmark/runs')} className="text-do-blue hover:underline">Run a benchmark →</button>
        </p>
      )}

      {/* Headlining stats */}
      {completed.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {statCards.map(s => (
            <div key={s.label} className="card">
              <p className="text-[11px] text-gray-500">{s.label}</p>
              <p className="text-2xl font-bold text-gray-900 leading-tight mt-0.5">{s.value}
                <span className="text-sm font-medium text-gray-400"> {s.sub}</span></p>
            </div>
          ))}
        </div>
      )}

      {/* Visualizers */}
      {sweep.length > 0 && (
        <div className="card">
          <div className="flex items-center gap-1 border-b border-do-grey-200 mb-3">
            {([['performance', 'Performance'], ['tvl', 'Throughput vs Latency']] as const).map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px ${tab === k ? 'border-do-blue text-do-blue' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'performance' && (
            <>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[11px] text-gray-500">Metric:</span>
                <select className="input text-xs w-auto" value={perfMetric} onChange={e => setPerfMetric(e.target.value as PerfKey)}>
                  {PERF_METRICS.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
                </select>
              </div>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={perfData} margin={{ top: 8, right: 12, bottom: 16, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                  <XAxis dataKey="conc" tick={{ fill: '#6B7280', fontSize: 11 }}>
                    <Label value="Concurrency" position="insideBottom" offset={-10} fill="#9CA3AF" fontSize={11} />
                  </XAxis>
                  <YAxis tick={{ fill: '#6B7280', fontSize: 11 }} unit={perfCfg.unit} width={56} />
                  <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }}
                    formatter={(v: number) => [fmt(v), perfCfg.label]} labelFormatter={(l) => `Concurrency ${l}`} />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                    {perfData.map((d) => <Cell key={d.conc} fill={BLUE} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </>
          )}

          {tab === 'tvl' && (
            <>
              <div className="flex items-center gap-3 mb-2 flex-wrap">
                <div className="flex items-center gap-1">
                  <span className="text-[11px] text-gray-500">Throughput:</span>
                  <select className="input text-xs w-auto" value={tvlTput} onChange={e => setTvlTput(e.target.value as 'total' | 'outTps')}>
                    <option value="total">Total tok/s</option>
                    <option value="outTps">Output tok/s</option>
                  </select>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[11px] text-gray-500">Latency:</span>
                  <select className="input text-xs w-auto" value={tvlLat} onChange={e => setTvlLat(e.target.value as 'tpot' | 'ttft')}>
                    <option value="tpot">TPOT (ms)</option>
                    <option value="ttft">TTFT (ms)</option>
                  </select>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={tvlData} margin={{ top: 8, right: 16, bottom: 16, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']} tick={{ fill: '#6B7280', fontSize: 11 }}
                    tickFormatter={(v) => fmt(v)}>
                    <Label value={tvlLat === 'tpot' ? 'TPOT (ms)' : 'TTFT (ms)'} position="insideBottom" offset={-10} fill="#9CA3AF" fontSize={11} />
                  </XAxis>
                  <YAxis tick={{ fill: '#6B7280', fontSize: 11 }} width={64} tickFormatter={(v) => fmt(v)}>
                    <Label value={tvlTput === 'total' ? 'Total tok/s' : 'Output tok/s'} angle={-90} position="insideLeft" fill="#9CA3AF" fontSize={11} style={{ textAnchor: 'middle' }} />
                  </YAxis>
                  <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }}
                    formatter={(v: number, name) => [fmt(v), name === 'y' ? (tvlTput === 'total' ? 'Total tok/s' : 'Output tok/s') : name]}
                    labelFormatter={(l) => `${tvlLat === 'tpot' ? 'TPOT' : 'TTFT'} ${fmt(l as number)} ms`} />
                  <Line type="monotone" dataKey="y" stroke={BLUE} strokeWidth={2} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
              <p className="text-[10px] text-gray-400 mt-1">Each point is a concurrency level — up and to the left is better (more throughput at lower latency).</p>
            </>
          )}
        </div>
      )}

      {/* Detail table */}
      {tableRows.length > 0 && (
        <div className="card overflow-x-auto">
          <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Benchmark runs</p>
            <div className="flex items-center gap-2">
              {sel.size > 0 && (
                <button onClick={() => setHidden([...sel], true)} disabled={busy}
                  className="btn-secondary text-xs disabled:opacity-50">🗄 Archive {sel.size} selected</button>
              )}
              {failedIds.length > 0 && (
                <button onClick={() => setHidden(failedIds, true)} disabled={busy}
                  className="btn-secondary text-xs disabled:opacity-50" title="Archive failed runs in the current filter">
                  Archive {failedIds.length} failed</button>
              )}
            </div>
          </div>
          <table className="w-full text-xs whitespace-nowrap">
            <thead>
              <tr className="text-gray-500 text-left">
                <th className="py-1 pr-2 w-6"><input type="checkbox" checked={allSelected} onChange={toggleAll} disabled={!selectable.length} /></th>
                <th className="py-1 px-2 font-medium">Engine</th>
                <th className="py-1 px-2 font-medium">Model</th>
                <th className="py-1 px-2 font-medium">ISL/OSL</th>
                <th className="py-1 px-2 font-medium text-right">Conc</th>
                <th className="py-1 px-2 font-medium text-right">TP</th>
                <th className="py-1 px-2 font-medium">GPU</th>
                <th className="py-1 px-2 font-medium text-right">Total tok/s</th>
                <th className="py-1 px-2 font-medium text-right">Output tok/s</th>
                <th className="py-1 px-2 font-medium text-right" title="Tokens/sec per user (1000 / TPOT)">Interac.</th>
                <th className="py-1 px-2 font-medium text-right">TPOT (ms)</th>
                <th className="py-1 px-2 font-medium text-right">TTFT (ms)</th>
                <th className="py-1 px-2 font-medium">Date</th>
                <th className="py-1 pl-2 font-medium">Run</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map(row => (
                <tr key={row.r.id} className={`border-t border-do-grey-100 hover:bg-do-grey-100 ${sel.has(row.r.id) ? 'bg-blue-50' : ''}`}>
                  <td className="py-1.5 pr-2"><input type="checkbox" checked={sel.has(row.r.id)} onChange={() => toggleSel(row.r.id)} /></td>
                  <td className="py-1.5 px-2 text-gray-600">{row.engine}</td>
                  <td className="py-1.5 px-2 text-gray-800" title={row.model}>{shortModel(row.model)}</td>
                  <td className="py-1.5 px-2 text-gray-600">{row.isl !== undefined && row.osl !== undefined ? `${kfmt(row.isl)}/${kfmt(row.osl)}` : '—'}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-700">{row.conc ?? '—'}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-700">{row.tp ?? '—'}</td>
                  <td className="py-1.5 px-2 text-gray-600">{row.gpuLabel}</td>
                  <td className="py-1.5 px-2 text-right font-mono font-semibold text-gray-900">{fmt(row.total)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-700">{fmt(row.outTps)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-700">{fmt(row.interac)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-700">{fmt(row.tpot)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-700">{fmt(row.ttft)}</td>
                  <td className="py-1.5 px-2 text-gray-500">{row.date ? new Date(row.date).toLocaleDateString() : '—'}</td>
                  <td className="py-1.5 pl-2"><button onClick={() => navigate(`/benchmark/runs?run=${row.r.id}`)} className="text-do-blue hover:underline">view</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Archived runs */}
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
                      <th className="py-1 px-2 font-medium text-right">Conc</th>
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
                          <td className="py-1 pl-2">{r.status}</td>
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

import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceArea, ReferenceLine,
} from 'recharts'
import { api } from '../api'
import type { AiperfRun } from '../types'
import { summarize, shortModel, fmt, type RunSummary } from '../lib/aiperf'

// The four latency columns that can be gated against an SLA ceiling (ms). Every
// other column (throughput, counts) is the objective, shown but never gated.
type ThrKey = 'ttftP50' | 'ttftP90' | 'itlP50' | 'itlP90'
const LAT_COLS: Array<{ key: ThrKey; label: string }> = [
  { key: 'ttftP50', label: 'TTFT P50 (ms)' },
  { key: 'ttftP90', label: 'TTFT P90 (ms)' },
  { key: 'itlP50', label: 'ITL P50 (ms)' },
  { key: 'itlP90', label: 'ITL P90 (ms)' },
]
// Full column order — mirrors the run-detail Summary table, one run per row.
const TPUT_KEYS = ['reqPerSec', 'inPerGpu', 'outPerGpu', 'totalPerGpu'] as const
const COLS: Array<{ key: keyof RunSummary; label: string; kind: 'plain' | 'tput' | 'lat' }> = [
  { key: 'concurrency', label: 'Concurrency', kind: 'plain' },
  { key: 'requests', label: 'Requests', kind: 'plain' },
  { key: 'duration', label: 'Duration (s)', kind: 'plain' },
  { key: 'reqPerSec', label: 'Req/s', kind: 'tput' },
  { key: 'inPerGpu', label: 'Input tok/s/GPU', kind: 'tput' },
  { key: 'outPerGpu', label: 'Output tok/s/GPU', kind: 'tput' },
  { key: 'totalPerGpu', label: 'Total tok/s/GPU', kind: 'tput' },
  { key: 'ttftP50', label: 'TTFT P50 (ms)', kind: 'lat' },
  { key: 'ttftP90', label: 'TTFT P90 (ms)', kind: 'lat' },
  { key: 'itlP50', label: 'ITL P50 (ms)', kind: 'lat' },
  { key: 'itlP90', label: 'ITL P90 (ms)', kind: 'lat' },
]

const STORE_KEY = 'crest_sla_thresholds'
const emptyThr = (): Record<ThrKey, string> => ({ ttftP50: '', ttftP90: '', itlP50: '', itlP90: '' })
function loadThr(): Record<ThrKey, string> {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (raw) return { ...emptyThr(), ...JSON.parse(raw) }
  } catch { /* ignore */ }
  return emptyThr()
}

type CellStatus = 'pass' | 'fail' | 'missing' | 'na'
interface RowEval { checks: Record<ThrKey, CellStatus>; pass: boolean; incomplete: boolean; anyGated: boolean }

function evalRow(s: RunSummary, thr: Record<ThrKey, number | undefined>): RowEval {
  const checks = {} as Record<ThrKey, CellStatus>
  let anyGated = false, allPass = true, incomplete = false
  for (const { key } of LAT_COLS) {
    const t = thr[key]
    const v = s[key] as number | undefined
    if (t === undefined) { checks[key] = 'na'; continue }
    anyGated = true
    if (v === undefined) { checks[key] = 'missing'; incomplete = true; allPass = false; continue }
    if (v <= t) { checks[key] = 'pass' } else { checks[key] = 'fail'; allPass = false }
  }
  return { checks, pass: anyGated && allPass, incomplete, anyGated }
}

export default function BenchmarkSLA() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<AiperfRun[]>([])
  const [loading, setLoading] = useState(true)
  const [deploymentId, setDeploymentId] = useState('')
  const [thrStr, setThrStr] = useState<Record<ThrKey, string>>(loadThr)

  useEffect(() => { api.aiperf.history().then(setRuns).catch(() => {}).finally(() => setLoading(false)) }, [])
  useEffect(() => { try { localStorage.setItem(STORE_KEY, JSON.stringify(thrStr)) } catch { /* ignore */ } }, [thrStr])

  const thr = useMemo(() => {
    const out = {} as Record<ThrKey, number | undefined>
    for (const { key } of LAT_COLS) {
      const v = Number(thrStr[key])
      out[key] = thrStr[key].trim() && Number.isFinite(v) && v > 0 ? v : undefined
    }
    return out
  }, [thrStr])
  const anySla = LAT_COLS.some(c => thr[c.key] !== undefined)

  // Cohorts = one concurrency sweep = the completed runs against one deployment.
  const completed = useMemo(() => runs.filter(r => r.status === 'completed'), [runs])
  const cohorts = useMemo(() => {
    const m = new Map<string, AiperfRun[]>()
    completed.forEach(r => {
      const k = r.deployment_id || r.id
      if (!m.has(k)) m.set(k, [])
      m.get(k)!.push(r)
    })
    // Most-recent sweep first in the picker.
    return [...m.entries()]
      .map(([id, rs]) => {
        const rep = rs[0]
        const s = summarize(rep)
        // Droplet name + date disambiguate two deployments of the same model on
        // the same hardware (which are intentionally separate cohorts).
        const dropletName = rep.droplet_snapshot?.name
        const latest = rs.reduce((mx, r) => Math.max(mx, r.created_at ? Date.parse(r.created_at) : 0), 0)
        const dateStr = latest ? new Date(latest).toLocaleDateString() : ''
        const label = `${shortModel(rep.model)} · ${s.gpuLabel}${rep.droplet_snapshot?.region ? ' · ' + rep.droplet_snapshot.region : ''}`
          + (dropletName ? ` · ${dropletName}` : '') + (dateStr ? ` · ${dateStr}` : '')
        return { id, label, runs: rs, count: rs.length, latest }
      })
      .sort((a, b) => b.latest - a.latest)
  }, [completed])

  // Default to the most recent cohort once data loads.
  useEffect(() => {
    if (!deploymentId && cohorts.length) setDeploymentId(cohorts[0].id)
  }, [cohorts, deploymentId])

  const cohort = cohorts.find(c => c.id === deploymentId) || null

  // Rows: this cohort's runs that have a concurrency, sorted ascending (lowest
  // concurrency at top, highest at bottom).
  const rows = useMemo(() => {
    if (!cohort) return []
    return cohort.runs
      .map(r => ({ run: r, s: summarize(r) }))
      .filter(x => x.s.concurrency !== undefined)
      .sort((a, b) => (a.s.concurrency! - b.s.concurrency!)
        || ((a.run.created_at ? Date.parse(a.run.created_at) : 0) - (b.run.created_at ? Date.parse(b.run.created_at) : 0)))
      .map(x => ({ ...x, ev: evalRow(x.s, thr) }))
  }, [cohort, thr])

  const excluded = (cohort?.runs.length || 0) - rows.length
  const bestTput = useMemo(() => {
    const b = {} as Record<string, number>
    TPUT_KEYS.forEach(k => {
      const vals = rows.map(r => r.s[k]).filter((v): v is number => v !== undefined)
      if (vals.length) b[k] = Math.max(...vals)
    })
    return b
  }, [rows])

  // The answer: highest-concurrency row that passes every set SLA.
  const maxPass = useMemo(() => {
    const passing = rows.filter(r => r.ev.pass)
    return passing.length ? passing[passing.length - 1] : null
  }, [rows])

  // Why the next step up fails (the row just above the max-passing concurrency).
  const nextBreach = useMemo(() => {
    if (!maxPass) return null
    const idx = rows.findIndex(r => r.run.id === maxPass.run.id)
    const next = rows[idx + 1]
    if (!next) return null
    const reasons = LAT_COLS
      .filter(c => next.ev.checks[c.key] === 'fail')
      .map(c => `${c.label} (${fmt(next.s[c.key] as number)} > ${thr[c.key]}ms)`)
    const missing = LAT_COLS.filter(c => next.ev.checks[c.key] === 'missing').map(c => c.label)
    return { conc: next.s.concurrency, reasons, missing }
  }, [maxPass, rows, thr])

  // No row passes: describe what the lowest concurrency already breaches.
  const firstFailDesc = useMemo(() => {
    if (!anySla || maxPass || !rows.length) return null
    const r = rows[0]
    const reasons = LAT_COLS
      .filter(c => r.ev.checks[c.key] === 'fail')
      .map(c => `${c.label} (${fmt(r.s[c.key] as number)} > ${thr[c.key]}ms)`)
    const missing = LAT_COLS.filter(c => r.ev.checks[c.key] === 'missing').map(c => c.label)
    return { conc: r.s.concurrency, reasons, missing }
  }, [anySla, maxPass, rows, thr])

  const chartData = rows.map(r => ({
    concurrency: r.s.concurrency!, total: r.s.totalPerGpu, out: r.s.outPerGpu, pass: r.ev.pass,
  }))
  const minConc = chartData.length ? chartData[0].concurrency : 0
  const maxPassConc = maxPass?.s.concurrency

  const setThr = (k: ThrKey, v: string) => setThrStr(s => ({ ...s, [k]: v.replace(/[^0-9.]/g, '') }))

  const cellVal = (s: RunSummary, key: keyof RunSummary) => {
    const v = s[key]
    if (key === 'concurrency' || key === 'requests') return v === undefined ? '—' : String(v)
    return fmt(v as number | undefined)
  }
  const latClass: Record<CellStatus, string> = {
    pass: 'bg-green-50 text-green-700 font-semibold',
    fail: 'bg-red-50 text-red-700 font-semibold',
    missing: 'bg-amber-50 text-amber-600',
    na: 'text-gray-700',
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-bold text-gray-800">SLA Analysis</h1>
          <p className="text-xs text-gray-500">Find the highest concurrency that still meets your latency SLAs.</p>
        </div>
        {cohorts.length > 0 && (
          <select className="input max-w-md text-xs" value={deploymentId} onChange={e => setDeploymentId(e.target.value)}>
            {cohorts.map(c => <option key={c.id} value={c.id}>{c.label} · {c.count} run{c.count === 1 ? '' : 's'}</option>)}
          </select>
        )}
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {!loading && cohorts.length === 0 && (
        <p className="text-sm text-gray-600">
          No completed benchmark runs yet.{' '}
          <button onClick={() => navigate('/benchmark/runs')} className="text-do-blue hover:underline">Run a benchmark →</button>
        </p>
      )}

      {cohort && (
        <>
          {/* SLA ceilings */}
          <div className="card">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] text-gray-500 uppercase tracking-wider">SLA ceilings (ms) — leave blank to ignore a metric</p>
              {anySla && (
                <button onClick={() => setThrStr(emptyThr())} className="text-[11px] text-do-blue hover:underline">Clear</button>
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {LAT_COLS.map(c => (
                <label key={c.key} className="block">
                  <span className="text-[11px] text-gray-600">{c.label.replace(' (ms)', '')} ≤</span>
                  <input className="input text-xs mt-0.5" inputMode="decimal" value={thrStr[c.key]}
                    onChange={e => setThr(c.key, e.target.value)} placeholder="ms" />
                </label>
              ))}
            </div>
          </div>

          {/* Result card */}
          {!anySla ? (
            <div className="rounded-lg border border-do-grey-200 bg-do-grey-100 p-3 text-sm text-gray-600">
              Enter one or more SLA ceilings above to highlight passing/failing runs and find your max concurrency.
            </div>
          ) : maxPass ? (
            <div className="rounded-lg border border-green-300 bg-green-50 p-3">
              <p className="text-sm font-bold text-green-800">
                ✅ Max concurrency within SLA: {maxPass.s.concurrency}
              </p>
              <p className="text-xs text-green-700 mt-0.5">
                {fmt(maxPass.s.totalPerGpu)} total tok/s/GPU · {fmt(maxPass.s.outPerGpu)} output tok/s/GPU · {fmt(maxPass.s.reqPerSec)} req/s
              </p>
              {nextBreach && nextBreach.reasons.length > 0 && (
                <p className="text-[11px] text-green-700/80 mt-1">
                  Stepping up to {nextBreach.conc} breaches {nextBreach.reasons.join(', ')}.
                </p>
              )}
              {nextBreach && nextBreach.reasons.length === 0 && nextBreach.missing.length > 0 && (
                <p className="text-[11px] text-amber-600 mt-1">
                  Next step ({nextBreach.conc}) can't be evaluated — missing {nextBreach.missing.join(', ')}.
                </p>
              )}
              {!nextBreach && <p className="text-[11px] text-green-700/80 mt-1">This is the highest concurrency tested — try a higher one to find the ceiling.</p>}
            </div>
          ) : (
            <div className="rounded-lg border border-red-300 bg-red-50 p-3">
              <p className="text-sm font-bold text-red-700">✗ No run meets all SLAs</p>
              {firstFailDesc && firstFailDesc.reasons.length > 0 && (
                <p className="text-xs text-red-600 mt-0.5">
                  Even the lowest concurrency ({firstFailDesc.conc}) breaches {firstFailDesc.reasons.join(', ')}.
                </p>
              )}
              {firstFailDesc && firstFailDesc.reasons.length === 0 && firstFailDesc.missing.length > 0 && (
                <p className="text-xs text-amber-600 mt-0.5">
                  Runs are missing gated metrics ({firstFailDesc.missing.join(', ')}) — re-run with those percentiles.
                </p>
              )}
            </div>
          )}

          {/* Per-run table */}
          <div className="card overflow-x-auto">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">
              Runs by concurrency{excluded > 0 ? ` · ${excluded} run(s) without a concurrency hidden` : ''}
            </p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 text-left">
                  <th className="py-1 pr-2 font-medium">SLA</th>
                  {COLS.map(c => <th key={c.key} className="py-1 px-2 font-medium text-right whitespace-nowrap">{c.label}</th>)}
                  <th className="py-1 pl-2 font-medium">Run</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ run, s, ev }) => {
                  const isMax = maxPass?.run.id === run.id
                  return (
                    <tr key={run.id}
                      className={`border-t border-do-grey-100 ${isMax ? 'bg-green-50/60 border-l-2 border-l-green-500' : ''}`}>
                      <td className="py-1 pr-2">
                        {!ev.anyGated ? <span className="text-gray-300">—</span>
                          : ev.pass ? <span className="text-green-600 font-bold" title={isMax ? 'Highest passing concurrency' : 'Meets SLA'}>{isMax ? '✓ Max' : '✓'}</span>
                          : ev.incomplete && !LAT_COLS.some(c => ev.checks[c.key] === 'fail') ? <span className="text-amber-500" title="Missing a gated metric">?</span>
                          : <span className="text-red-500 font-bold" title="Breaches SLA">✗</span>}
                      </td>
                      {COLS.map(c => {
                        const cls = c.kind === 'lat'
                          ? latClass[ev.checks[c.key as ThrKey]]
                          : c.kind === 'tput' && s[c.key] !== undefined && s[c.key] === bestTput[c.key as string]
                            ? 'text-gray-900 font-bold' : 'text-gray-700'
                        return <td key={c.key} className={`py-1 px-2 text-right font-mono ${cls}`}>{cellVal(s, c.key)}</td>
                      })}
                      <td className="py-1 pl-2">
                        <button onClick={() => navigate(`/benchmark/runs?run=${run.id}`)} className="text-do-blue hover:underline">view</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Companion chart: throughput vs concurrency, SLA-passing region shaded */}
          {chartData.length > 1 && (
            <div className="card">
              <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Throughput vs concurrency</p>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  {maxPassConc !== undefined && (
                    <ReferenceArea x1={minConc} x2={maxPassConc} fill="#10b981" fillOpacity={0.08}
                      label={{ value: 'within SLA', position: 'insideTopLeft', fill: '#059669', fontSize: 10 }} />
                  )}
                  {maxPassConc !== undefined && (
                    <ReferenceLine x={maxPassConc} stroke="#10b981" strokeDasharray="4 2"
                      label={{ value: `max ${maxPassConc}`, position: 'top', fill: '#059669', fontSize: 10 }} />
                  )}
                  <XAxis dataKey="concurrency" type="number" tick={{ fill: '#6B7280', fontSize: 10 }}
                    domain={['dataMin', 'dataMax']}
                    label={{ value: 'Concurrency', position: 'insideBottom', offset: -3, fill: '#9CA3AF', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} width={52} />
                  <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }}
                    formatter={(v: number) => fmt(v)} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="total" name="Total tok/s/GPU" stroke="#0080FF" strokeWidth={2} dot connectNulls />
                  <Line type="monotone" dataKey="out" name="Output tok/s/GPU" stroke="#10b981" strokeWidth={2} dot connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  )
}

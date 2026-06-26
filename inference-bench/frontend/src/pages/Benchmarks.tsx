import { useState, useEffect, useRef, useMemo } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { api } from '../api'
import type { AiperfRun, AiperfArg, AiperfProgress, AiperfMetric, Deployment } from '../types'

const STATUS_COLOR: Record<string, string> = {
  queued: 'bg-yellow-500', running: 'bg-yellow-500', completed: 'bg-green-500', failed: 'bg-red-500',
}
const STATUS_TEXT: Record<string, string> = {
  queued: 'text-yellow-600', running: 'text-yellow-600', completed: 'text-green-600', failed: 'text-red-600',
}
const PENDING = ['queued', 'running']

// Sensible aiperf defaults — every one editable/removable, add-your-own for the
// full flag surface (goodput, trace mode, time-slicing, …). model/url/tokenizer
// are injected by the backend from the deployment, so they're not listed here.
const DEFAULT_ARGS: AiperfArg[] = [
  { flag: '--concurrency', value: '100' },
  { flag: '--request-count', value: '1000' },
  { flag: '--isl', value: '1000' },
  { flag: '--osl', value: '500' },
  { flag: '--streaming', value: '' },
  { flag: '--endpoint-type', value: 'chat' },
]

const prettyMetric = (k: string) => k.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
const fmt = (n: number | string | undefined) =>
  typeof n === 'number' ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'

export default function Benchmarks() {
  const [params, setParams] = useSearchParams()
  const [runs, setRuns] = useState<AiperfRun[]>([])
  const [deployments, setDeployments] = useState<Deployment[]>([])
  const [selected, setSelected] = useState<AiperfRun | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [progress, setProgress] = useState<AiperfProgress | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const load = () => Promise.all([api.aiperf.list(), api.deployments.list()])
    .then(([rs, deps]) => { setRuns(rs); setDeployments(deps) })

  useEffect(() => { load() }, [])

  // Deep-link from a deployment: /benchmark/runs?deployment=<id> opens the form.
  const preDeployment = params.get('deployment')
  useEffect(() => { if (preDeployment) { setShowNew(true); setSelected(null) } }, [preDeployment])

  // Deep-link to a specific run: /benchmark/runs?run=<id>
  const preRun = params.get('run')
  useEffect(() => {
    if (preRun) { setShowNew(false); api.aiperf.get(preRun).then(setSelected).catch(() => {}) }
  }, [preRun])

  // Stream progress while the selected run is in flight.
  useEffect(() => {
    esRef.current?.close()
    setProgress(null)
    if (!selected || !PENDING.includes(selected.status)) return
    const es = new EventSource(api.aiperf.streamUrl(selected.id))
    esRef.current = es
    es.onmessage = (e) => {
      try {
        const data: AiperfProgress = JSON.parse(e.data)
        setProgress(data)
        if (['completed', 'failed'].includes(data.status)) {
          es.close(); load()
          api.aiperf.get(selected.id).then(setSelected).catch(() => {})
        }
      } catch { /* ignore */ }
    }
    es.onerror = () => { /* auto-reconnects */ }
    return () => { es.close() }
  }, [selected?.id, selected?.status])

  const onCreated = (r: AiperfRun) => {
    setShowNew(false)
    if (preDeployment) { params.delete('deployment'); setParams(params, { replace: true }) }
    load(); setSelected(r)
  }

  return (
    <div className="flex h-full">
      <div className="w-72 border-r border-do-grey-200 flex flex-col shrink-0">
        <div className="p-4 border-b border-do-grey-200">
          <div className="flex items-center justify-between mb-0.5">
            <h1 className="text-sm font-bold text-gray-800">Benchmarks</h1>
            <button onClick={() => { setShowNew(true); setSelected(null) }} className="text-xs text-do-blue hover:underline">＋ New run</button>
          </div>
          <p className="text-xs text-gray-500">aiperf · against a serving deployment</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {runs.length === 0 && <p className="text-xs text-gray-600 px-4 py-3">No benchmark runs yet</p>}
          {runs.map(r => (
            <button key={r.id} onClick={() => { setSelected(r); setShowNew(false) }}
              className={`w-full text-left px-4 py-3 border-b border-do-grey-200 hover:bg-do-grey-100 ${selected?.id === r.id ? 'bg-do-grey-100' : ''}`}>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_COLOR[r.status] || 'bg-gray-400'} ${PENDING.includes(r.status) ? 'animate-pulse' : ''}`} />
                <p className="text-sm text-gray-700 truncate flex-1">{r.model}</p>
                <span className={`text-[10px] ${STATUS_TEXT[r.status] || 'text-gray-500'}`}>{r.status}</span>
              </div>
              <p className="text-xs text-gray-600 mt-0.5 pl-4">
                {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                {r.status === 'queued' && r.queue_position ? ` · ${r.queue_position} ahead` : ''}
              </p>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {showNew && (
          <NewBenchmark deployments={deployments} preDeploymentId={preDeployment}
            onCreated={onCreated} onCancel={() => setShowNew(false)} />
        )}
        {!showNew && !selected && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">Select a run, or start a new benchmark</div>
        )}
        {!showNew && selected && <RunDetail run={selected} progress={progress} />}
      </div>
    </div>
  )
}

// ── New benchmark: deployment → editable aiperf params → run ───────────────────
function NewBenchmark({ deployments, preDeploymentId, onCreated, onCancel }: {
  deployments: Deployment[]; preDeploymentId: string | null
  onCreated: (r: AiperfRun) => void; onCancel: () => void
}) {
  const navigate = useNavigate()
  const [deploymentId, setDeploymentId] = useState(preDeploymentId || '')
  const [args, setArgs] = useState<AiperfArg[]>(DEFAULT_ARGS.map(a => ({ ...a })))
  const [extraPct, setExtraPct] = useState('')
  const [hfToken, setHfToken] = useState('')
  const [pre, setPre] = useState<{ gated: boolean; has_token: boolean; port: number } | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const serving = useMemo(() => deployments.filter(d => d.status === 'serving'), [deployments])

  // Up-front: is the tokenizer gated, and is a token already on file?
  useEffect(() => {
    setPre(null)
    if (!deploymentId) return
    api.aiperf.preflight(deploymentId).then(setPre).catch(() => {})
  }, [deploymentId])

  const setArg = (i: number, patch: Partial<AiperfArg>) =>
    setArgs(a => a.map((x, idx) => idx === i ? { ...x, ...patch } : x))
  const removeArg = (i: number) => setArgs(a => a.filter((_, idx) => idx !== i))
  const addArg = () => setArgs(a => [...a, { flag: '', value: '' }])

  const tokenizerGatedNeedsToken = !!pre?.gated && !pre?.has_token && !hfToken.trim()
  const canRun = !running && !!deploymentId && !tokenizerGatedNeedsToken

  const run = async () => {
    if (!canRun) return
    setRunning(true); setError(null)
    try {
      const extra_percentiles = extraPct.split(',').map(s => parseInt(s.trim(), 10))
        .filter(n => Number.isFinite(n) && n > 0 && n < 100)
      const r = await api.aiperf.create({
        deployment_id: deploymentId,
        args: args.filter(a => a.flag.trim()),
        extra_percentiles,
        hf_token: hfToken || undefined,
      })
      onCreated(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start benchmark')
    } finally { setRunning(false) }
  }

  const sectionTitle = (n: number, title: string, sub?: string) => (
    <div className="flex items-baseline gap-2">
      <span className="w-5 h-5 rounded-full bg-do-blue text-white text-[11px] font-bold flex items-center justify-center shrink-0">{n}</span>
      <h3 className="text-sm font-bold text-gray-800">{title}</h3>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  )

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-gray-800">New benchmark run</h2>
        <button onClick={onCancel} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
      </div>

      {/* 1. Deployment */}
      <div className="space-y-2">
        {sectionTitle(1, 'Deployment', 'serving deployments only')}
        {serving.length === 0 && (
          <p className="text-xs text-gray-500">
            No serving deployments.{' '}
            <button onClick={() => navigate('/benchmark/deployments')} className="text-do-blue hover:underline">Deploy a model →</button>
          </p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {serving.map(d => (
            <button key={d.id} onClick={() => setDeploymentId(d.id)}
              className={`text-left p-2.5 rounded-lg border ${deploymentId === d.id ? 'border-do-blue ring-1 ring-do-blue bg-blue-50' : 'border-do-grey-200 hover:border-do-grey-400'}`}>
              <p className="text-sm font-semibold text-gray-800 truncate">{d.model}</p>
              <p className="text-[11px] text-gray-500">
                {d.engine} · {d.droplet_name || d.droplet_snapshot?.name || 'droplet'}
                {d.droplet_snapshot?.gpu_count && d.droplet_snapshot?.gpu_model ? ` · ${d.droplet_snapshot.gpu_count}× ${d.droplet_snapshot.gpu_model}` : ''}
              </p>
            </button>
          ))}
        </div>
      </div>

      {deploymentId && (
        <>
          {/* 2. aiperf parameters */}
          <div className="space-y-2">
            {sectionTitle(2, 'aiperf parameters', 'sensible defaults — edit freely')}
            <div className="space-y-1.5">
              {args.map((a, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <input className="input font-mono text-xs flex-1" value={a.flag} onChange={e => setArg(i, { flag: e.target.value })} placeholder="--flag" />
                  <input className="input font-mono text-xs flex-1" value={a.value} onChange={e => setArg(i, { value: e.target.value })} placeholder="value (blank for a bare flag)" />
                  <button onClick={() => removeArg(i)} className="text-gray-400 hover:text-red-500 text-sm px-1">✕</button>
                </div>
              ))}
              <button onClick={addArg} className="text-[11px] text-do-blue hover:underline">＋ Add parameter</button>
            </div>
            <p className="text-[11px] text-gray-400">
              <span className="font-mono">--model</span>, <span className="font-mono">--url</span> and <span className="font-mono">--tokenizer</span> are set automatically from the deployment.
            </p>
          </div>

          {/* 3. Extra percentiles (opt-in) */}
          <div className="space-y-2">
            {sectionTitle(3, 'Extra percentiles', 'optional')}
            <input className="input font-mono text-xs max-w-xs" value={extraPct} onChange={e => setExtraPct(e.target.value)}
              placeholder="e.g. 75, 95" />
            <p className="text-[11px] text-gray-400">
              Defaults report p50/p90/p99. Add any others (comma-separated) — computed for this run, no re-run needed.
            </p>
          </div>

          {/* 4. Tokenizer token — only when gated */}
          {pre?.gated && (
            <div className="space-y-2">
              {sectionTitle(4, 'Tokenizer access', 'gated model')}
              {pre.has_token ? (
                <p className="text-[11px] text-gray-600">
                  This model's tokenizer is gated. We'll reuse the HF token from the deployment automatically —
                  enter an alternate below only if you want to use a different token for the tokenizer.
                </p>
              ) : (
                <p className="text-[11px] text-do-red font-semibold">
                  This model's tokenizer is gated and no token is on file. Enter an HF token with access.
                </p>
              )}
              <input className={`input max-w-md ${tokenizerGatedNeedsToken ? 'border-do-red' : ''}`} type="password"
                value={hfToken} onChange={e => setHfToken(e.target.value)}
                placeholder={pre.has_token ? 'hf_… (optional alternate token)' : 'hf_… (required)'} />
            </div>
          )}
        </>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2 pt-1">
        <button onClick={run} disabled={!canRun} className="btn-primary text-sm disabled:opacity-50">
          {running ? 'Starting…' : 'Run benchmark'}
        </button>
        <button onClick={onCancel} className="btn-secondary text-sm">Cancel</button>
      </div>
    </div>
  )
}

// ── Run detail: status, profile, metrics, logs, activity ──────────────────────
function RunDetail({ run: r, progress }: { run: AiperfRun; progress: AiperfProgress | null }) {
  const status = progress?.status ?? r.status
  const metrics = (progress?.metrics && Object.keys(progress.metrics).length ? progress.metrics : r.metrics) || {}
  const logs = progress?.log_tail ?? r.log_tail ?? ''
  const events = progress?.events ?? r.events ?? []
  const detail = progress?.status_detail ?? r.status_detail

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center gap-3">
        <span className={`w-3 h-3 rounded-full ${STATUS_COLOR[status] || 'bg-gray-400'} ${PENDING.includes(status) ? 'animate-pulse' : ''}`} />
        <div>
          <h2 className="text-base font-bold text-gray-800">{r.model}</h2>
          <p className={`text-sm font-semibold ${STATUS_TEXT[status] || 'text-gray-600'}`}>
            {status}{detail ? ` — ${detail}` : ''}
            {status === 'queued' && r.queue_position ? ` · ${r.queue_position} run(s) ahead` : ''}
          </p>
        </div>
      </div>

      {status === 'failed' && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3">
          <p className="text-sm font-semibold text-red-700">✗ Benchmark failed</p>
          <p className="text-xs text-red-600 mt-1 whitespace-pre-wrap break-words">{detail || 'No error detail.'}</p>
        </div>
      )}

      {/* Context */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Engine</p><p className="text-sm font-semibold text-gray-800 mt-0.5">{r.engine}</p></div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">Deployment</p>
          <Link to={`/benchmark/deployments?deployment=${r.deployment_id}`} className="text-sm font-semibold text-do-blue hover:underline mt-0.5 block truncate">{r.deployment_name || r.model}</Link>
        </div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">GPU</p>
          <p className="text-sm font-semibold text-gray-800 mt-0.5">{r.droplet_snapshot?.gpu_count && r.droplet_snapshot?.gpu_model ? `${r.droplet_snapshot.gpu_count}× ${r.droplet_snapshot.gpu_model}` : '—'}</p>
        </div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">Region</p>
          <p className="text-sm font-semibold text-gray-800 mt-0.5">{r.droplet_snapshot?.region || '—'}</p>
        </div>
      </div>

      {/* Profile */}
      {!!(r.profile?.args?.length || r.profile?.extra_percentiles?.length) && (
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Profile</p>
          <code className="text-xs text-gray-700 break-words">
            {(r.profile.args || []).map(a => `${a.flag}${a.value ? ' ' + a.value : ''}`).join('  ')}
          </code>
          {!!r.profile.extra_percentiles?.length && (
            <p className="text-[11px] text-gray-500 mt-1">Extra percentiles: {r.profile.extra_percentiles.join(', ')}</p>
          )}
        </div>
      )}

      {/* Metrics */}
      {Object.keys(metrics).length > 0 && <MetricsTable metrics={metrics} />}

      {logs && (
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">aiperf logs</p>
          <pre className="text-[11px] text-gray-700 bg-do-grey-100 rounded p-2 max-h-72 overflow-auto whitespace-pre-wrap break-words">{logs}</pre>
        </div>
      )}

      {events.length > 0 && (
        <div className="card">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">Activity</p>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {[...events].reverse().map((ev, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-gray-500 shrink-0 font-mono">{new Date(ev.ts).toLocaleTimeString()}</span>
                <span className={`${ev.event === 'benchmark_failed' ? 'text-red-600' : ev.event === 'benchmark_completed' ? 'text-green-600' : 'text-gray-600'}`}>
                  {ev.event}{ev.error ? `: ${String(ev.error)}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MetricsTable({ metrics }: { metrics: Record<string, AiperfMetric> }) {
  // Per-request metrics have avg/min/max/percentiles; aggregates have a single value.
  const entries = Object.entries(metrics)
  const perReq = entries.filter(([, m]) => m.avg !== undefined)
  const aggregates = entries.filter(([, m]) => m.avg === undefined && m.value !== undefined)

  const pctCols = useMemo(() => {
    const set = new Set<string>()
    perReq.forEach(([, m]) => Object.keys(m).forEach(k => { if (/^p\d+$/.test(k)) set.add(k) }))
    return [...set].sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)))
  }, [metrics])

  return (
    <div className="space-y-3">
      {perReq.length > 0 && (
        <div className="card overflow-x-auto">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Latency metrics</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 text-left">
                <th className="py-1 pr-3 font-medium">Metric</th>
                <th className="py-1 px-2 font-medium text-right">avg</th>
                <th className="py-1 px-2 font-medium text-right">min</th>
                <th className="py-1 px-2 font-medium text-right">max</th>
                {pctCols.map(p => <th key={p} className="py-1 px-2 font-medium text-right">{p}</th>)}
                <th className="py-1 px-2 font-medium text-right">std</th>
              </tr>
            </thead>
            <tbody>
              {perReq.map(([key, m]) => (
                <tr key={key} className="border-t border-do-grey-100">
                  <td className="py-1 pr-3 text-gray-700">{prettyMetric(key)} <span className="text-gray-400">({m.unit})</span></td>
                  <td className="py-1 px-2 text-right font-mono text-gray-800">{fmt(m.avg)}</td>
                  <td className="py-1 px-2 text-right font-mono text-gray-600">{fmt(m.min)}</td>
                  <td className="py-1 px-2 text-right font-mono text-gray-600">{fmt(m.max)}</td>
                  {pctCols.map(p => <td key={p} className="py-1 px-2 text-right font-mono text-gray-800">{fmt(m[p])}</td>)}
                  <td className="py-1 px-2 text-right font-mono text-gray-500">{fmt(m.std)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {aggregates.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {aggregates.map(([key, m]) => (
            <div key={key} className="card">
              <p className="text-[10px] text-gray-500 uppercase tracking-wider">{prettyMetric(key)}</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{fmt(m.value)} <span className="text-[11px] text-gray-400 font-normal">{m.unit}</span></p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

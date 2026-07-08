import { useState, useEffect, useRef, useMemo } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { api } from '../api'
import type {
  AiperfRun, AiperfArg, AiperfProgress, AiperfMetric, AiperfConfig, AiperfTrends, Deployment,
} from '../types'

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

  // Batch queue: surface the first run, refresh the list (the rest sit queued).
  const onQueued = (rs: AiperfRun[]) => {
    if (!rs.length) return
    setShowNew(false)
    if (preDeployment) { params.delete('deployment'); setParams(params, { replace: true }) }
    load(); setSelected(rs[0])
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
            onCreated={onCreated} onQueued={onQueued} onCancel={() => setShowNew(false)} />
        )}
        {!showNew && !selected && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">Select a run, or start a new benchmark</div>
        )}
        {!showNew && selected && <RunDetail run={selected} progress={progress} />}
      </div>
    </div>
  )
}

// Parse a comma-separated percentile string into valid ints (1–99).
const parsePercentiles = (s: string): number[] =>
  s.split(',').map(x => parseInt(x.trim(), 10)).filter(n => Number.isFinite(n) && n > 0 && n < 100)

// One-line summary of a saved config's profile, concurrency first (the swept knob).
const configSummary = (c: AiperfConfig): string => {
  const conc = c.args.find(a => a.flag === '--concurrency')?.value
  const rest = c.args
    .filter(a => a.flag.trim() && a.flag !== '--concurrency')
    .map(a => `${a.flag}${a.value ? ' ' + a.value : ''}`)
  return [conc ? `concurrency ${conc}` : null, ...rest].filter(Boolean).join(' · ')
}

// ── New benchmark: deployment → editable aiperf params → run / save / queue ────
function NewBenchmark({ deployments, preDeploymentId, onCreated, onQueued, onCancel }: {
  deployments: Deployment[]; preDeploymentId: string | null
  onCreated: (r: AiperfRun) => void; onQueued: (rs: AiperfRun[]) => void; onCancel: () => void
}) {
  const navigate = useNavigate()
  const [deploymentId, setDeploymentId] = useState(preDeploymentId || '')
  const [args, setArgs] = useState<AiperfArg[]>(DEFAULT_ARGS.map(a => ({ ...a })))
  const [extraPct, setExtraPct] = useState('')
  const [hfToken, setHfToken] = useState('')
  const [pre, setPre] = useState<{ gated: boolean; has_token: boolean; port: number } | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Saved configurations (named aiperf profiles) — select several and queue at once.
  const [configs, setConfigs] = useState<AiperfConfig[]>([])
  const [selectedCfg, setSelectedCfg] = useState<Set<string>>(new Set())
  const [saveName, setSaveName] = useState('')
  const [savingCfg, setSavingCfg] = useState(false)
  const [queueing, setQueueing] = useState(false)

  const serving = useMemo(() => deployments.filter(d => d.status === 'serving'), [deployments])
  const loadConfigs = () => api.aiperf.configs.list().then(setConfigs).catch(() => {})
  useEffect(() => { loadConfigs() }, [])

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
      const r = await api.aiperf.create({
        deployment_id: deploymentId,
        args: args.filter(a => a.flag.trim()),
        extra_percentiles: parsePercentiles(extraPct),
        hf_token: hfToken || undefined,
      })
      onCreated(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start benchmark')
    } finally { setRunning(false) }
  }

  // Save the current parameter grid (+ extra percentiles) as a reusable config.
  const saveConfig = async () => {
    const name = saveName.trim()
    if (!name || savingCfg) return
    setSavingCfg(true); setError(null)
    try {
      await api.aiperf.configs.create({
        name,
        args: args.filter(a => a.flag.trim()),
        extra_percentiles: parsePercentiles(extraPct),
      })
      setSaveName('')
      await loadConfigs()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save configuration')
    } finally { setSavingCfg(false) }
  }

  // Load a saved config back into the editable grid (for tweaking or a single run).
  const loadConfig = (c: AiperfConfig) => {
    setArgs(c.args.length ? c.args.map(a => ({ ...a })) : [{ flag: '', value: '' }])
    setExtraPct((c.extra_percentiles || []).join(', '))
  }

  const deleteConfig = async (id: string) => {
    try {
      await api.aiperf.configs.remove(id)
      setSelectedCfg(s => { const n = new Set(s); n.delete(id); return n })
      await loadConfigs()
    } catch { /* ignore */ }
  }

  const toggleCfg = (id: string) =>
    setSelectedCfg(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allSelected = configs.length > 0 && selectedCfg.size === configs.length
  const toggleAll = () =>
    setSelectedCfg(allSelected ? new Set() : new Set(configs.map(c => c.id)))

  const canQueue = !queueing && !!deploymentId && selectedCfg.size > 0 && !tokenizerGatedNeedsToken

  // Queue every selected config against the deployment in one click — they run
  // serially on the droplet (a concurrency sweep).
  const queueSelected = async () => {
    if (!canQueue) return
    setQueueing(true); setError(null)
    try {
      const rs = await api.aiperf.batch({
        deployment_id: deploymentId,
        config_ids: configs.filter(c => selectedCfg.has(c.id)).map(c => c.id),
        hf_token: hfToken || undefined,
      })
      onQueued(rs)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to queue benchmarks')
    } finally { setQueueing(false) }
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
            {/* Save the current grid as a reusable config (for sweeps). */}
            <div className="flex gap-2 items-center pt-1">
              <input className="input text-xs max-w-[14rem]" value={saveName}
                onChange={e => setSaveName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') saveConfig() }}
                placeholder="Name this config (e.g. conc-256)" />
              <button onClick={saveConfig} disabled={!saveName.trim() || savingCfg}
                className="btn-secondary text-xs disabled:opacity-50">
                {savingCfg ? 'Saving…' : '💾 Save as config'}
              </button>
            </div>
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

          {/* Saved configurations — select several and queue together (a sweep).
              Numbered after the gated-only tokenizer section so the steps stay
              sequential whether or not that section is shown. */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              {sectionTitle(pre?.gated ? 5 : 4, 'Saved configurations', 'select and queue together')}
              {configs.length > 0 && (
                <button onClick={queueSelected} disabled={!canQueue}
                  className="btn-primary text-xs disabled:opacity-50">
                  {queueing ? 'Queueing…' : `Queue selected (${selectedCfg.size}) →`}
                </button>
              )}
            </div>
            {configs.length === 0 ? (
              <p className="text-[11px] text-gray-500">
                No saved configs yet. Set the parameters above and <span className="font-medium">Save as config</span> to
                build a sweep (e.g. one config per concurrency), then select and queue them here.
              </p>
            ) : (
              <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-[11px] text-gray-500 cursor-pointer select-none">
                  <input type="checkbox" checked={allSelected} onChange={toggleAll} />
                  Select all ({configs.length})
                </label>
                {configs.map(c => (
                  <div key={c.id}
                    className={`flex items-center gap-2 p-2 rounded-lg border ${selectedCfg.has(c.id) ? 'border-do-blue bg-blue-50' : 'border-do-grey-200'}`}>
                    <input type="checkbox" checked={selectedCfg.has(c.id)} onChange={() => toggleCfg(c.id)} className="shrink-0" />
                    <button onClick={() => toggleCfg(c.id)} className="flex-1 min-w-0 text-left">
                      <p className="text-sm font-semibold text-gray-800 truncate">{c.name}</p>
                      <p className="text-[11px] text-gray-500 font-mono truncate">
                        {configSummary(c)}
                        {c.extra_percentiles?.length ? ` · +p${c.extra_percentiles.join('/p')}` : ''}
                      </p>
                    </button>
                    <button onClick={() => loadConfig(c)} className="text-[11px] text-do-blue hover:underline shrink-0">Load</button>
                    <button onClick={() => deleteConfig(c.id)} className="text-gray-400 hover:text-red-500 text-sm px-1 shrink-0">✕</button>
                  </div>
                ))}
                {tokenizerGatedNeedsToken && (
                  <p className="text-[11px] text-do-red">Enter the gated tokenizer token above before queueing.</p>
                )}
              </div>
            )}
          </div>
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
  const [copied, setCopied] = useState(false)
  const status = progress?.status ?? r.status
  const metrics = (progress?.metrics && Object.keys(progress.metrics).length ? progress.metrics : r.metrics) || {}
  const trends = (progress?.trends && (progress.trends.latency?.length || progress.trends.serving?.length))
    ? progress.trends : r.trends
  const logs = progress?.log_tail ?? r.log_tail ?? ''
  const events = progress?.events ?? r.events ?? []
  const detail = progress?.status_detail ?? r.status_detail

  const copyResults = () => {
    const payload = {
      model: r.model,
      engine: r.engine,
      gpu: r.droplet_snapshot?.gpu_count && r.droplet_snapshot?.gpu_model
        ? `${r.droplet_snapshot.gpu_count}× ${r.droplet_snapshot.gpu_model}` : undefined,
      region: r.droplet_snapshot?.region,
      profile: r.profile,
      metrics,
    }
    navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
      .catch(() => {})
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center justify-between">
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
        {status === 'completed' && Object.keys(metrics).length > 0 && (
          <button onClick={copyResults} className="btn-secondary text-xs">{copied ? '✓ Copied' : '⧉ Copy results'}</button>
        )}
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

      {/* Metrics: summary (shown) + full table (collapsed) */}
      {Object.keys(metrics).length > 0 && (
        <>
          <SummaryTable run={r} metrics={metrics} />
          <CollapsibleMetrics metrics={metrics} />
        </>
      )}

      {/* Trends over the run — latency (from aiperf) + serving/caching (from vLLM) */}
      {trends && (trends.latency?.length || trends.serving?.length) ? (
        <TrendCharts trends={trends} />
      ) : null}

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

// Headline summary — the row you'd compare across a concurrency sweep. Throughput
// is normalized per-GPU using the droplet's GPU count.
function SummaryTable({ run: r, metrics }: { run: AiperfRun; metrics: Record<string, AiperfMetric> }) {
  const gpu = r.droplet_snapshot?.gpu_count || 1
  const concurrency = r.profile?.args?.find(a => a.flag === '--concurrency')?.value || '—'
  const num = (v: number | string | undefined) => (typeof v === 'number' ? v : undefined)
  const perGpu = (v: number | string | undefined) => { const n = num(v); return n === undefined ? undefined : n / gpu }
  const inTps = num(metrics.input_token_throughput?.value)
  const outTps = num(metrics.output_token_throughput?.value)
  const totalTps = inTps !== undefined && outTps !== undefined ? inTps + outTps : undefined

  const rows: Array<[string, number | string | undefined]> = [
    ['Concurrency', concurrency],
    ['Requests', metrics.request_count?.value],
    ['Duration (s)', metrics.benchmark_duration?.value],
    ['Req/s', metrics.request_throughput?.value],
    ['Input tok/s/GPU', perGpu(inTps)],
    ['Output tok/s/GPU', perGpu(outTps)],
    ['Total tok/s/GPU', perGpu(totalTps)],
    ['TTFT P50 (ms)', metrics.time_to_first_token?.p50],
    ['TTFT P90 (ms)', metrics.time_to_first_token?.p90],
    ['ITL P50 (ms)', metrics.inter_token_latency?.p50],
    ['ITL P90 (ms)', metrics.inter_token_latency?.p90],
  ]

  return (
    <div className="card">
      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Summary <span className="text-gray-400 normal-case">· {gpu} GPU{gpu > 1 ? 's' : ''}</span></p>
      <table className="w-full text-xs">
        <tbody>
          {rows.map(([label, val]) => (
            <tr key={label} className="border-t border-do-grey-100 first:border-t-0">
              <td className="py-1 pr-3 text-gray-600">{label}</td>
              <td className="py-1 text-right font-mono text-gray-800">{typeof val === 'string' ? val : fmt(val)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CollapsibleMetrics({ metrics }: { metrics: Record<string, AiperfMetric> }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between text-left">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">All metrics</span>
        <span className="text-xs text-do-blue">{open ? '▾ Hide' : '▸ Show full table'}</span>
      </button>
      {open && <div className="mt-3"><MetricsTable metrics={metrics} /></div>}
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

// ── Trends over the run: latency (from aiperf, exact) + serving/caching (vLLM) ──
function TrendChart({ title, data, series, unit }: {
  title: string; data: Array<Record<string, number | undefined>>
  series: Array<{ key: string; name: string; color: string }>; unit?: string
}) {
  const has = series.some(s => data.some(d => typeof d[s.key] === 'number'))
  if (!has) return null
  return (
    <div className="card">
      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">{title}</p>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="t" type="number" tick={{ fill: '#6B7280', fontSize: 10 }} unit="s"
            domain={['dataMin', 'dataMax']} tickFormatter={(v) => `${Math.round(v)}`} />
          <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} unit={unit} width={46} />
          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }}
            labelFormatter={(l) => `t = ${fmt(l as number)}s`} formatter={(v: number, n) => [fmt(v), n]} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 9 }} />}
          {series.map(s => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color}
              strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function TrendCharts({ trends }: { trends: AiperfTrends }) {
  const lat = trends.latency || []
  const srv = trends.serving || []
  // Caching headline (from the vLLM serving samples).
  const avg = (key: 'kv_cache_pct' | 'prefix_hit_pct') => {
    const v = srv.map(p => p[key]).filter((x): x is number => typeof x === 'number')
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : undefined
  }
  const peakKv = (() => {
    const v = srv.map(p => p.kv_cache_pct).filter((x): x is number => typeof x === 'number')
    return v.length ? Math.max(...v) : undefined
  })()
  const avgPrefix = avg('prefix_hit_pct')
  const avgKv = avg('kv_cache_pct')

  return (
    <div className="space-y-3">
      <p className="text-[10px] text-gray-500 uppercase tracking-wider">Trends over the run</p>

      {/* Caching headline */}
      {(avgKv !== undefined || avgPrefix !== undefined) && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {avgKv !== undefined && (
            <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Avg KV-cache</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{fmt(avgKv)}% <span className="text-[11px] text-gray-400 font-normal">peak {fmt(peakKv)}%</span></p></div>
          )}
          {avgPrefix !== undefined && (
            <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Avg prefix-cache hit</p>
              <p className="text-sm font-semibold text-gray-800 mt-0.5">{fmt(avgPrefix)}%</p></div>
          )}
        </div>
      )}

      {/* Latency — exact, from aiperf's per-request export */}
      {lat.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <TrendChart title="TTFT over time (ms)" data={lat} unit="ms" series={[
            { key: 'ttft_p50', name: 'p50', color: '#0080FF' },
            { key: 'ttft_p90', name: 'p90', color: '#f59e0b' },
          ]} />
          <TrendChart title="TPOT over time (ms)" data={lat} unit="ms" series={[
            { key: 'tpot_p50', name: 'p50', color: '#0080FF' },
            { key: 'tpot_p90', name: 'p90', color: '#f59e0b' },
          ]} />
        </div>
      )}

      {/* Serving state — from vLLM /metrics */}
      {srv.length > 0 ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <TrendChart title="Cache utilization (%)" data={srv} unit="%" series={[
            { key: 'kv_cache_pct', name: 'KV cache', color: '#10b981' },
            { key: 'prefix_hit_pct', name: 'Prefix hit', color: '#8b5cf6' },
          ]} />
          <TrendChart title="Requests in flight" data={srv} series={[
            { key: 'running', name: 'Running', color: '#0080FF' },
            { key: 'waiting', name: 'Waiting', color: '#ef4444' },
          ]} />
          <TrendChart title="Output tok/s (server)" data={srv} series={[
            { key: 'out_tok_s', name: 'Output tok/s', color: '#10b981' },
          ]} />
        </div>
      ) : (
        <p className="text-[11px] text-gray-400">
          Server-side cache/queue trends unavailable — vLLM metrics weren't reachable for this run
          (e.g. <span className="font-mono">--disable-log-stats</span>).
        </p>
      )}
    </div>
  )
}

import { useState, useEffect, useRef, useMemo } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { api } from '../api'
import type {
  Deployment, DeploymentArg, DeploymentProgress, GpuDroplet,
  EngineInfo, RecipeModel, ResolvedRecipe, RecipeFeature,
} from '../types'

const STATUS_COLOR: Record<string, string> = {
  pulling: 'bg-yellow-500', starting: 'bg-yellow-500', serving: 'bg-green-500',
  failed: 'bg-red-500', droplet_destroyed: 'bg-gray-400',
}
const STATUS_TEXT: Record<string, string> = {
  pulling: 'text-yellow-600', starting: 'text-yellow-600', serving: 'text-green-600',
  failed: 'text-red-600', droplet_destroyed: 'text-gray-500',
}
const ACTIVE_STATUSES = ['pulling', 'starting', 'serving']

// vLLM/recipe feature args come as a flat token list — parse to {flag,value} pairs.
function tokensToArgs(tokens: string[]): DeploymentArg[] {
  const out: DeploymentArg[] = []
  for (let i = 0; i < tokens.length;) {
    const t = tokens[i]
    if (t.startsWith('-')) {
      if (i + 1 < tokens.length && !tokens[i + 1].startsWith('-')) { out.push({ flag: t, value: tokens[i + 1] }); i += 2 }
      else { out.push({ flag: t, value: '' }); i += 1 }
    } else i += 1
  }
  return out
}
const featureFlags = (f: RecipeFeature) => f.args.filter(a => a.startsWith('-'))
function isFeatureOn(args: DeploymentArg[], f: RecipeFeature): boolean {
  const have = new Set(args.map(a => a.flag))
  const ff = featureFlags(f)
  return ff.length > 0 && ff.every(fl => have.has(fl))
}
function toggleFeature(args: DeploymentArg[], f: RecipeFeature, on: boolean): DeploymentArg[] {
  const ff = new Set(featureFlags(f))
  if (!on) return args.filter(a => !ff.has(a.flag))
  const have = new Set(args.map(a => a.flag))
  return [...args, ...tokensToArgs(f.args).filter(p => !have.has(p.flag))]
}

// ── Paste a launch command and fill the form from it ──────────────────────────
// Handles three shapes (plus leading `export KEY=VAL` env lines and `# comments`):
//   docker run [OPTIONS] IMAGE MODEL [--flags…]
//   vllm serve MODEL [--flags…]            (no image → default vLLM image)
//   a bare block of --flags               (model taken from --model; default image)
// The model + flags + env extraction is shared; the only difference is how we
// locate the start of the model.
const DEFAULT_VLLM_IMAGE = 'vllm/vllm-openai:latest'
const DOCKER_VALUE_FLAGS = new Set([
  '-p', '--publish', '-v', '--volume', '--mount', '-e', '--env', '--env-file', '--name',
  '--gpus', '--shm-size', '--device', '--group-add', '--security-opt', '--restart',
  '--entrypoint', '-w', '--workdir', '--network', '--net', '--add-host', '-u', '--user',
  '-l', '--label', '-m', '--memory', '--cpus', '--ulimit', '--ipc', '--pid', '--runtime',
  '--hostname', '-h', '--cpuset-cpus', '--platform',
])

// Quote-aware split (keeps quoted JSON like --compilation-config '{"mode": 0}' intact).
function shellSplit(s: string): string[] {
  const out: string[] = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) out.push(m[1] ?? m[2] ?? m[3])
  return out
}
const stripQuotes = (s: string) =>
  s.length >= 2 && ((s[0] === '"' && s.endsWith('"')) || (s[0] === "'" && s.endsWith("'"))) ? s.slice(1, -1) : s

function parseLaunchCommand(raw: string): { image: string; model: string; args: DeploymentArg[]; env: Record<string, string>; port?: number } | null {
  const joined = raw.replace(/\\\r?\n/g, ' ')         // fold line continuations
  const env: Record<string, string> = {}
  const cmdLines: string[] = []
  for (const line of joined.split('\n')) {
    // Drop trailing/whole-line `# comments` (only when # starts a token, so
    // URLs like http://h#frag survive).
    const t = line.replace(/(^|\s)#.*$/, '$1').trim()
    if (!t) continue
    const exp = t.match(/^export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$/)   // export KEY=VAL → env
    if (exp) { env[exp[1]] = stripQuotes(exp[2].trim()); continue }
    cmdLines.push(t)
  }
  const tokens = shellSplit(cmdLines.join(' '))
  if (!tokens.length) return null

  let i = 0, image = DEFAULT_VLLM_IMAGE, port: number | undefined
  if (tokens[0] === 'docker' && tokens[1] === 'run') {
    i = 2
    while (i < tokens.length) {                        // skip docker options → image
      const t = tokens[i]
      if (!t.startsWith('-')) break
      let val: string | undefined
      if (t.includes('=')) { i++ }
      else if (DOCKER_VALUE_FLAGS.has(t)) { val = tokens[i + 1]; i += 2 }
      else { i++ }
      if ((t === '-p' || t === '--publish') && val) {
        const n = parseInt((val.split(':').pop() || '').split('/')[0], 10)   // container side
        if (Number.isFinite(n)) port = n
      } else if ((t === '-e' || t === '--env') && val && val.includes('=')) {
        env[val.slice(0, val.indexOf('='))] = val.slice(val.indexOf('=') + 1)
      }
    }
    image = tokens[i++] || ''
  }
  // Skip an explicit `vllm serve` container command — it appears both as a bare
  // `vllm serve MODEL …` and spelled out AFTER the image in docker commands for
  // images whose entrypoint is bare `vllm` (e.g. rocm/vllm). Without this, the
  // `vllm` token gets misread as the model.
  if (tokens[i] === 'vllm') i++
  if (tokens[i] === 'serve') i++

  // Positional model (docker … IMAGE MODEL, or `vllm serve MODEL`), else pull it
  // from a --model flag — which covers a bare `--flag` block and `vllm serve --model`.
  let model = tokens[i] && !tokens[i].startsWith('-') ? tokens[i++] : ''
  let args = tokensToArgs(tokens.slice(i))
  if (!model) {
    const mi = args.findIndex(a => a.flag === '--model' || a.flag === '-m')
    if (mi >= 0) { model = args[mi].value; args = args.filter((_, idx) => idx !== mi) }
  }
  if (!image || !model) return null
  return { image, model, args, env, port }
}

export default function Deployments() {
  const [params, setParams] = useSearchParams()
  const [deployments, setDeployments] = useState<Deployment[]>([])
  const [droplets, setDroplets] = useState<GpuDroplet[]>([])
  const [selected, setSelected] = useState<Deployment | null>(null)
  const [showDeploy, setShowDeploy] = useState(false)
  const [progress, setProgress] = useState<DeploymentProgress | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const load = () => Promise.all([api.deployments.list(), api.droplets.list()])
    .then(([deps, drs]) => { setDeployments(deps); setDroplets(drs) })

  useEffect(() => { load() }, [])

  // Deep-link from a droplet: /benchmark/deployments?droplet=<id> opens the deploy form.
  const preDroplet = params.get('droplet')
  useEffect(() => {
    if (preDroplet) { setShowDeploy(true); setSelected(null) }
  }, [preDroplet])

  // Deep-link to a specific deployment: /benchmark/deployments?deployment=<id>
  const preDeployment = params.get('deployment')
  useEffect(() => {
    if (preDeployment) {
      setShowDeploy(false)
      api.deployments.get(preDeployment).then(setSelected).catch(() => {})
    }
  }, [preDeployment])

  // Stream deploy progress for the selected deployment while it's in flight.
  useEffect(() => {
    esRef.current?.close()
    setProgress(null)
    if (!selected || (selected.status !== 'pulling' && selected.status !== 'starting')) return
    const es = new EventSource(api.deployments.streamUrl(selected.id))
    esRef.current = es
    es.onmessage = (e) => {
      try {
        const data: DeploymentProgress = JSON.parse(e.data)
        setProgress(data)
        if (['serving', 'failed', 'droplet_destroyed'].includes(data.status)) {
          es.close(); load()
          api.deployments.get(selected.id).then(setSelected).catch(() => {})
        }
      } catch { /* ignore */ }
    }
    es.onerror = () => { /* auto-reconnects */ }
    return () => { es.close() }
  }, [selected?.id, selected?.status])

  const onDeployed = (d: Deployment) => {
    setShowDeploy(false)
    if (preDroplet) { params.delete('droplet'); setParams(params, { replace: true }) }
    load(); setSelected(d)
  }

  // Active deployments (live state on a live droplet) float to the top; then
  // stale/other; newest first within each group.
  const depRank = (d: Deployment) =>
    ['pulling', 'starting', 'serving'].includes(d.status) && d.droplet_status === 'active' ? 0 : 1
  const sortedDeployments = [...deployments].sort((a, b) =>
    (depRank(a) - depRank(b)) ||
    (new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()))

  return (
    <div className="flex h-full">
      <div className="w-72 border-r border-do-grey-200 flex flex-col shrink-0">
        <div className="p-4 border-b border-do-grey-200">
          <div className="flex items-center justify-between mb-0.5">
            <h1 className="text-sm font-bold text-gray-800">Deployments</h1>
            <button onClick={() => { setShowDeploy(true); setSelected(null) }} className="text-xs text-do-blue hover:underline">＋ Deploy</button>
          </div>
          <p className="text-xs text-gray-500">vLLM · one model per droplet</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {deployments.length === 0 && <p className="text-xs text-gray-600 px-4 py-3">No deployments yet</p>}
          {sortedDeployments.map(d => (
            <button key={d.id} onClick={() => { setSelected(d); setShowDeploy(false) }}
              className={`w-full text-left px-4 py-3 border-b border-do-grey-200 hover:bg-do-grey-100 ${selected?.id === d.id ? 'bg-do-grey-100' : ''}`}>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_COLOR[d.status] || 'bg-gray-400'} ${d.status === 'pulling' || d.status === 'starting' ? 'animate-pulse' : ''}`} />
                <p className="text-sm text-gray-700 truncate flex-1">{d.model}</p>
                <span className={`text-[10px] ${STATUS_TEXT[d.status] || 'text-gray-500'}`}>{d.status}</span>
              </div>
              <p className="text-xs text-gray-600 mt-0.5 pl-4">{d.engine} · {d.droplet_name || d.droplet_snapshot?.name || 'droplet'}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {showDeploy && (
          <DeployPanel droplets={droplets} deployments={deployments} preDropletId={preDroplet}
            onDeployed={onDeployed} onCancel={() => setShowDeploy(false)} />
        )}
        {!showDeploy && !selected && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">Select a deployment, or deploy a model</div>
        )}
        {!showDeploy && selected && <DeploymentDetail deployment={selected} progress={progress} onChanged={load} />}
      </div>
    </div>
  )
}

// ── Deploy panel: engine → model → droplet → recipe-seeded editable form ──────
function DeployPanel({ droplets, deployments, preDropletId, onDeployed, onCancel }: {
  droplets: GpuDroplet[]; deployments: Deployment[]; preDropletId: string | null
  onDeployed: (d: Deployment) => void; onCancel: () => void
}) {
  const navigate = useNavigate()
  const [engines, setEngines] = useState<EngineInfo[]>([])
  const [engine, setEngine] = useState('vllm')
  const [models, setModels] = useState<RecipeModel[]>([])
  const [modelQuery, setModelQuery] = useState('')
  const [model, setModel] = useState('')
  const [dropletId, setDropletId] = useState(preDropletId || '')

  const [recipe, setRecipe] = useState<ResolvedRecipe | null>(null)
  const [resolving, setResolving] = useState(false)
  const [resolveErr, setResolveErr] = useState<string | null>(null)

  // Editable form state (seeded from the recipe, then user-tinkerable).
  const [image, setImage] = useState('')
  const [args, setArgs] = useState<DeploymentArg[]>([])
  const [env, setEnv] = useState<Array<{ key: string; value: string }>>([])
  const [port, setPort] = useState(8000)
  const [startupMin, setStartupMin] = useState('60')   // free-text; sanitized on deploy
  const [hfToken, setHfToken] = useState('')

  // Optional: filled from a pasted `docker run` command instead of a recipe.
  const [pasted, setPasted] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteErr, setPasteErr] = useState<string | null>(null)

  const [deploying, setDeploying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Droplets that can accept a deployment: active + not already taken.
  const takenIds = useMemo(
    () => new Set(deployments.filter(d => ACTIVE_STATUSES.includes(d.status)).map(d => d.droplet_id)),
    [deployments])
  const availableDroplets = droplets.filter(d => d.status === 'active' && !takenIds.has(d.id))

  useEffect(() => { api.recipes.engines().then(setEngines).catch(() => {}) }, [])
  useEffect(() => {
    setModels([]); setModel('')
    api.recipes.models(engine).then(setModels).catch(() => {})
  }, [engine])

  const filteredModels = useMemo(() => {
    const q = modelQuery.trim().toLowerCase()
    const list = q ? models.filter(m => m.hf_id.toLowerCase().includes(q) || m.title.toLowerCase().includes(q) || m.provider.toLowerCase().includes(q)) : models
    return list.slice(0, 60)
  }, [models, modelQuery])

  // Resolve the recipe once model + droplet are chosen — unless the form was
  // filled from a pasted command, in which case we leave those values alone.
  useEffect(() => {
    if (pasted) return
    if (!model || !dropletId) { setRecipe(null); return }
    setResolving(true); setResolveErr(null)
    api.recipes.resolve(engine, model, dropletId)
      .then(r => {
        setRecipe(r)
        setImage(r.docker_image)
        setArgs(r.server_args)
        setEnv(Object.entries(r.env || {}).map(([key, value]) => ({ key, value })))
        setPort(r.port || 8000)
      })
      .catch(e => { setRecipe(null); setResolveErr(e instanceof Error ? e.message : 'Failed to resolve recipe') })
      .finally(() => setResolving(false))
  }, [engine, model, dropletId, pasted])

  // Fill the form from a pasted `docker run …` command (replaces recipe values).
  const applyPaste = () => {
    setPasteErr(null)
    const parsed = parseLaunchCommand(pasteText)
    if (!parsed) {
      setPasteErr('Could not parse that — paste a `docker run …`, a `vllm serve <model> …`, or a block of --flags including --model.')
      return
    }
    setRecipe(null); setResolveErr(null); setPasted(true)
    setModel(parsed.model); setModelQuery('')
    setImage(parsed.image)
    setArgs(parsed.args)
    setEnv(Object.entries(parsed.env).map(([key, value]) => ({ key, value })))
    if (parsed.port) setPort(parsed.port)
  }

  const setArg = (i: number, patch: Partial<DeploymentArg>) =>
    setArgs(a => a.map((x, idx) => idx === i ? { ...x, ...patch } : x))
  const removeArg = (i: number) => setArgs(a => a.filter((_, idx) => idx !== i))
  const addArg = () => setArgs(a => [...a, { flag: '', value: '' }])

  const setEnvRow = (i: number, patch: Partial<{ key: string; value: string }>) =>
    setEnv(e => e.map((x, idx) => idx === i ? { ...x, ...patch } : x))
  const removeEnv = (i: number) => setEnv(e => e.filter((_, idx) => idx !== i))
  const addEnv = () => setEnv(e => [...e, { key: '', value: '' }])

  const selectedDroplet = droplets.find(d => d.id === dropletId)
  const needsToken = !!recipe?.gated && !hfToken.trim()
  const canDeploy = !deploying && !!model && !!dropletId && !!image && (!!recipe || pasted) && !needsToken

  const deploy = async () => {
    if (!canDeploy) { setError('Pick a model and a droplet first'); return }
    setDeploying(true); setError(null)
    try {
      const d = await api.deployments.create({
        droplet_id: dropletId, engine, model: recipe ? recipe.model_id : model, docker_image: image,
        server_args: args.filter(a => a.flag.trim()),
        env: Object.fromEntries(env.filter(e => e.key.trim()).map(e => [e.key.trim(), e.value])),
        port, hf_token: hfToken || undefined,
        recipe_source_url: recipe?.recipe_source_url ?? null, hardware_key: recipe?.hardware_key ?? null,
        startup_timeout_min: Number(startupMin) || 60,
      })
      onDeployed(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to deploy')
    } finally { setDeploying(false) }
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
        <h2 className="text-base font-bold text-gray-800">Deploy a model</h2>
        <button onClick={onCancel} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
      </div>

      {/* 1. Engine */}
      <div className="space-y-2">
        {sectionTitle(1, 'Inference engine')}
        <div className="flex gap-2">
          {engines.map(e => (
            <button key={e.name} onClick={() => e.available && setEngine(e.name)} disabled={!e.available}
              title={e.available ? '' : 'Not available yet'}
              className={`px-3 py-1.5 rounded-md border text-xs ${engine === e.name ? 'border-do-blue bg-blue-50 text-do-blue font-semibold' : 'border-do-grey-200 text-gray-700 hover:border-do-grey-400'} ${!e.available ? 'opacity-40 cursor-not-allowed' : ''}`}>
              {e.display_name}{!e.available && ' (soon)'}
            </button>
          ))}
          {engines.length === 0 && <span className="text-xs text-gray-500">Loading engines…</span>}
        </div>
      </div>

      {/* 2. Model */}
      <div className="space-y-2">
        {sectionTitle(2, 'Model', `${models.length} recipes`)}
        <input className="input" value={modelQuery} onChange={e => setModelQuery(e.target.value)}
          placeholder="Search models (e.g. Qwen, Llama, DeepSeek)…" />
        {model && <p className="text-[11px] text-gray-600">Selected: <span className="font-mono">{model}</span></p>}
        {modelQuery && (
          <div className="max-h-52 overflow-y-auto border border-do-grey-200 rounded-md divide-y divide-do-grey-100">
            {filteredModels.length === 0 && <p className="text-xs text-gray-500 px-3 py-2">No matches</p>}
            {filteredModels.map(m => (
              <button key={m.hf_id} onClick={() => { setModel(m.hf_id); setModelQuery(''); setPasted(false) }}
                className="w-full text-left px-3 py-1.5 hover:bg-do-grey-100">
                <p className="text-sm text-gray-800">{m.title}</p>
                <p className="text-[11px] text-gray-500 font-mono">{m.hf_id} · {m.provider}</p>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Optional: paste a launch command (docker run … or vllm serve …) */}
      <details className="border border-do-grey-200 rounded-md">
        <summary className="px-3 py-2 text-xs text-do-blue cursor-pointer select-none">⎘ Paste a launch command (optional)</summary>
        <div className="p-3 space-y-2 border-t border-do-grey-200">
          <textarea className="input font-mono text-xs h-32" value={pasteText} onChange={e => setPasteText(e.target.value)}
            placeholder={"docker run --gpus all … vllm/vllm-openai:tag org/Model --flag value …\n\n— or —\n\nvllm serve org/Model --flag value --bare-flag …\n\n— or just a block of flags —\n\n--model org/Model\n--tensor-parallel-size 1   # comments ok\n--enable-chunked-prefill"} />
          <div className="flex items-center gap-2">
            <button type="button" onClick={applyPaste} disabled={!pasteText.trim()} className="btn-secondary text-xs disabled:opacity-50">Fill form from command</button>
            {pasted && <span className="text-[11px] text-green-600">✓ Filled from pasted command — edit below or deploy</span>}
          </div>
          <p className="text-[11px] text-gray-500">
            Accepts a <span className="font-mono">docker run …</span>, a <span className="font-mono">vllm serve …</span>, or a bare block of
            <span className="font-mono"> --flags</span> (with <span className="font-mono">--model</span>; <span className="font-mono">#comments</span> and <span className="font-mono">export KEY=VAL</span> ok).
            Fills the form below, <span className="font-medium">replacing</span> the recipe defaults (not merged).
            With no image given, the default <span className="font-mono">{DEFAULT_VLLM_IMAGE}</span> is used — edit it if needed.
          </p>
          {pasteErr && <p className="text-[11px] text-red-600">{pasteErr}</p>}
        </div>
      </details>

      {/* 3. Droplet */}
      <div className="space-y-2">
        {sectionTitle(3, 'Target droplet', 'active droplets without a deployment')}
        {availableDroplets.length === 0 && (
          <p className="text-xs text-gray-500">
            No available droplets.{' '}
            <button onClick={() => navigate('/benchmark/droplets')} className="text-do-blue hover:underline">Create a GPU droplet →</button>
          </p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {availableDroplets.map(d => (
            <button key={d.id} onClick={() => setDropletId(d.id)}
              className={`text-left p-2.5 rounded-lg border ${dropletId === d.id ? 'border-do-blue ring-1 ring-do-blue bg-blue-50' : 'border-do-grey-200 hover:border-do-grey-400'}`}>
              <p className="text-sm font-semibold text-gray-800">{d.name}</p>
              <p className="text-[11px] text-gray-500">
                {d.gpu_count && d.gpu_model ? `${d.gpu_count}× ${d.gpu_model}` : d.size_slug} · {d.region}
              </p>
            </button>
          ))}
        </div>
        {availableDroplets.length > 0 && (
          <button onClick={() => navigate('/benchmark/droplets')} className="text-[11px] text-do-blue hover:underline">＋ Create a new droplet instead</button>
        )}
      </div>

      {/* 4. Recipe-seeded, editable launch config */}
      {model && dropletId && (
        <div className="space-y-3">
          {sectionTitle(4, 'Launch configuration', pasted ? 'from pasted command' : (recipe?.hardware_key ? `recipe · ${recipe.hardware_key}` : 'recipe defaults'))}
          {!pasted && resolving && <p className="text-xs text-gray-500">Fetching recipe for {selectedDroplet?.gpu_model || 'this GPU'}…</p>}
          {!pasted && resolveErr && <p className="text-xs text-red-600">{resolveErr}</p>}
          {(recipe || pasted) && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-[11px] text-gray-500">Docker image</span>
                  <input className="input mt-0.5 font-mono text-xs" value={image} onChange={e => setImage(e.target.value)} />
                </label>
                <label className="block">
                  <span className="text-[11px] text-gray-500">Served port</span>
                  <input className="input mt-0.5" type="number" value={port} onChange={e => setPort(Number(e.target.value) || 8000)} />
                </label>
                <label className="block">
                  <span className="text-[11px] text-gray-500">Startup timeout (min)</span>
                  <input className="input mt-0.5" type="text" inputMode="numeric" value={startupMin}
                    onChange={e => setStartupMin(e.target.value.replace(/[^0-9]/g, ''))} placeholder="60" />
                  <span className="text-[10px] text-gray-400">How long to wait for the model to come up. Big FP4/MoE models can need 60–90+.</span>
                </label>
              </div>

              {/* Feature toggles from the recipe (e.g. tool_calling, reasoning, spec_decoding) */}
              {recipe && recipe.features.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wider">Features</p>
                  <div className="flex flex-wrap gap-2">
                    {recipe.features.map(f => {
                      const on = isFeatureOn(args, f)
                      return (
                        <button key={f.name} title={f.description}
                          onClick={() => setArgs(a => toggleFeature(a, f, !on))}
                          className={`px-2.5 py-1 rounded-full border text-[11px] ${on ? 'border-do-green bg-green-50 text-green-700 font-semibold' : 'border-do-grey-200 text-gray-600 hover:border-do-grey-400'}`}>
                          {on ? '✓ ' : '+ '}{f.name}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Editable server args */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wider">Server arguments</p>
                  <button onClick={addArg} className="text-[11px] text-do-blue hover:underline">＋ Add argument</button>
                </div>
                {args.length === 0 && <p className="text-[11px] text-gray-400">No extra arguments.</p>}
                {args.map((a, i) => (
                  <div key={i} className="flex gap-2 items-center">
                    <input className="input font-mono text-xs flex-1" value={a.flag} onChange={e => setArg(i, { flag: e.target.value })} placeholder="--flag" />
                    <input className="input font-mono text-xs flex-1" value={a.value} onChange={e => setArg(i, { value: e.target.value })} placeholder="value (blank for a bare flag)" />
                    <button onClick={() => removeArg(i)} className="text-gray-400 hover:text-red-500 text-sm px-1">✕</button>
                  </div>
                ))}
              </div>

              {/* Environment variables */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wider">Environment</p>
                  <button onClick={addEnv} className="text-[11px] text-do-blue hover:underline">＋ Add variable</button>
                </div>
                {env.map((e, i) => (
                  <div key={i} className="flex gap-2 items-center">
                    <input className="input font-mono text-xs flex-1" value={e.key} onChange={ev => setEnvRow(i, { key: ev.target.value })} placeholder="KEY" />
                    <input className="input font-mono text-xs flex-1" value={e.value} onChange={ev => setEnvRow(i, { value: ev.target.value })} placeholder="value" />
                    <button onClick={() => removeEnv(i)} className="text-gray-400 hover:text-red-500 text-sm px-1">✕</button>
                  </div>
                ))}
              </div>

              {/* HF token */}
              <label className="block">
                <span className="text-[11px] text-gray-500">
                  HuggingFace token{' '}
                  {recipe?.gated
                    ? <span className="text-do-red font-semibold">— required, this model is gated</span>
                    : <span className="text-gray-400">(optional — required for gated models)</span>}
                </span>
                <input className={`input mt-0.5 ${needsToken ? 'border-do-red' : ''}`} type="password" value={hfToken} onChange={e => setHfToken(e.target.value)} placeholder="hf_…" />
                {recipe?.gated && (
                  <p className="text-[11px] text-gray-500 mt-1">
                    This model is gated on HuggingFace. Request access on its model page, then paste a token with read access.
                  </p>
                )}
              </label>
            </>
          )}
        </div>
      )}

      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="flex gap-2 pt-1">
        <button onClick={deploy} disabled={!canDeploy} className="btn-primary text-sm disabled:opacity-50">
          {deploying ? 'Deploying…' : 'Deploy model'}
        </button>
        <button onClick={onCancel} className="btn-secondary text-sm">Cancel</button>
      </div>
    </div>
  )
}

function DeploymentDetail({ deployment: d, progress, onChanged }: {
  deployment: Deployment; progress: DeploymentProgress | null; onChanged: () => void
}) {
  const [logs, setLogs] = useState(d.log_tail || '')
  const [health, setHealth] = useState(d.health || '')
  const [busy, setBusy] = useState(false)
  const events = progress?.events ?? d.events ?? []

  useEffect(() => { setLogs(d.log_tail || ''); setHealth(d.health || '') }, [d.id])
  useEffect(() => { if (progress?.log_tail) setLogs(progress.log_tail) }, [progress?.log_tail])

  const live = d.status === 'serving' || d.status === 'starting'
  const refreshLogs = async () => { setBusy(true); try { const r = await api.deployments.logs(d.id); setLogs(r.log_tail) } finally { setBusy(false) } }
  const checkHealth = async () => { setBusy(true); try { const r = await api.deployments.health(d.id); setHealth(r.health); onChanged() } finally { setBusy(false) } }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`w-3 h-3 rounded-full ${STATUS_COLOR[d.status] || 'bg-gray-400'} ${d.status === 'pulling' || d.status === 'starting' ? 'animate-pulse' : ''}`} />
          <div>
            <h2 className="text-base font-bold text-gray-800">{d.model}</h2>
            <p className={`text-sm font-semibold ${STATUS_TEXT[d.status] || 'text-gray-600'}`}>
              {d.status}{d.status_detail ? ` — ${d.status_detail}` : ''}
            </p>
          </div>
        </div>
        {d.status === 'serving' && d.droplet_status === 'active' && (
          <Link to={`/benchmark/runs?deployment=${d.id}`} className="btn-primary text-xs">◔ Run benchmark →</Link>
        )}
      </div>

      {d.status === 'failed' && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3">
          <p className="text-sm font-semibold text-red-700">✗ Deployment failed</p>
          <p className="text-xs text-red-600 mt-1 whitespace-pre-wrap break-words">{d.status_detail || progress?.status_detail || 'No error detail.'}</p>
          <p className="text-[11px] text-gray-500 mt-2">The droplet is still running — destroy it from the Droplets tab when done (1 droplet = 1 deployment).</p>
        </div>
      )}
      {d.status === 'droplet_destroyed' && (
        <div className="rounded-lg border border-do-grey-200 bg-do-grey-100 p-3">
          <p className="text-xs text-gray-600">This deployment's droplet was destroyed{d.droplet_destroyed_at ? ` on ${new Date(d.droplet_destroyed_at).toLocaleString()}` : ''}. Kept for history.</p>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-[10px] text-gray-500 uppercase tracking-wider">Engine</p><p className="text-sm font-semibold text-gray-800 mt-0.5">{d.engine}</p></div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">Droplet</p>
          <Link to={`/benchmark/droplets?droplet=${d.droplet_id}`} className="text-sm font-semibold text-do-blue hover:underline mt-0.5 block truncate">{d.droplet_name || d.droplet_snapshot?.name || '—'}</Link>
        </div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">GPU</p>
          <p className="text-sm font-semibold text-gray-800 mt-0.5">{d.droplet_snapshot?.gpu_count && d.droplet_snapshot?.gpu_model ? `${d.droplet_snapshot.gpu_count}× ${d.droplet_snapshot.gpu_model}` : '—'}</p>
        </div>
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">Health</p>
          <p className={`text-sm font-semibold mt-0.5 ${health === 'ok' ? 'text-green-600' : health === 'down' ? 'text-red-600' : 'text-gray-600'}`}>{health || '—'}</p>
        </div>
      </div>

      <div className="card">
        <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Endpoint (on droplet)</p>
        <p className="text-sm font-mono text-gray-800">localhost:{d.port}/v1 · image {d.docker_image}</p>
        {d.recipe_source_url && <a href={d.recipe_source_url} target="_blank" rel="noreferrer" className="text-[11px] text-do-blue hover:underline">recipe source ↗</a>}
      </div>

      {d.server_args.length > 0 && (
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Server arguments</p>
          <code className="text-xs text-gray-700 break-words">{d.server_args.map(a => `${a.flag}${a.value ? ' ' + a.value : ''}`).join('  ')}</code>
        </div>
      )}

      {live && (
        <div className="flex gap-2">
          <button onClick={refreshLogs} disabled={busy} className="btn-secondary text-xs">↻ Refresh logs</button>
          <button onClick={checkHealth} disabled={busy} className="btn-secondary text-xs">♥ Check health</button>
        </div>
      )}

      {logs && (
        <div className="card">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Container logs</p>
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
                <span className={`${ev.event === 'deployment_failed' ? 'text-red-600' : ev.event === 'deployment_serving' || ev.event === 'health_ok' ? 'text-green-600' : 'text-gray-600'}`}>
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

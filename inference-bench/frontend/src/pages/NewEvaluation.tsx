import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Model, BenchmarkSuite, EvaluationCreate } from '../types'
import ModelCard from '../components/ModelCard'
import BenchmarkCard from '../components/BenchmarkCard'

const CATEGORIES = ['All', 'math', 'coding', 'vision', 'general', 'science', 'reasoning', 'tool_calling', 'compliance']

const STEP_META = [
  {
    title: 'Select Model',
    desc: 'Choose the inference endpoint you want to evaluate. All OpenAI-compatible models are supported.',
  },
  {
    title: 'Configure Endpoint',
    desc: 'Set reasoning/thinking mode options for models that support extended thinking.',
  },
  {
    title: 'Select Benchmarks',
    desc: 'Pick one or more benchmark suites. Recommended suites cover the most important capability areas. Greyed-out suites require model capabilities your selected model does not support.',
  },
  {
    title: 'Configure Execution',
    desc: 'Choose between a quick sample run (faster, lower cost) or a full benchmark (complete dataset). Adjust batch size and generation parameters as needed.',
  },
  {
    title: 'Review & Launch',
    desc: 'Confirm your configuration before submitting. The evaluation runs in the background — you can track progress live or come back later.',
  },
]

export default function NewEvaluation() {
  const nav = useNavigate()
  const [step, setStep] = useState(1)

  const [models, setModels] = useState<Model[]>([])
  const [modelSearch, setModelSearch] = useState('')
  const [selectedModel, setSelectedModel] = useState<Model | null>(null)

  const [thinkingMode, setThinkingMode] = useState<'enabled' | 'disabled' | ''>('')
  const [reasoningEffort, setReasoningEffort] = useState<'low' | 'medium' | 'high'>('medium')

  const [benchmarks, setBenchmarks] = useState<BenchmarkSuite[]>([])
  const [selectedBenchmarks, setSelectedBenchmarks] = useState<Set<string>>(new Set())
  const [benchCat, setBenchCat] = useState('All')
  const [benchSearch, setBenchSearch] = useState('')

  const [displayName, setDisplayName] = useState('')
  const [evalScope, setEvalScope] = useState<'sample' | 'full'>('sample')
  const [sampleCount, setSampleCount] = useState(50)
  const [batchSize, setBatchSize] = useState(8)
  const [temperature, setTemperature] = useState('')
  const [maxTokens, setMaxTokens] = useState('')
  const [timeout, setTimeout_] = useState(120)

  const [creating, setCreating] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)

  useEffect(() => {
    api.models.list({ search: modelSearch }).then(setModels)
  }, [modelSearch])

  useEffect(() => {
    if (step === 3) {
      const params: Record<string, unknown> = {}
      if (benchCat !== 'All') params['category'] = benchCat
      if (benchSearch) params['search'] = benchSearch
      api.benchmarks.list(params as never).then(setBenchmarks)
    }
  }, [step, benchCat, benchSearch])

  const toggleBenchmark = (id: string) => {
    setSelectedBenchmarks(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const handleTestConnection = async () => {
    if (!selectedModel) return
    setTestResult('Testing…')
    const r = await api.models.test(selectedModel.id)
    setTestResult(r.ok ? `✓ Connected (${r.latency_ms?.toFixed(0)}ms)` : `✗ ${r.error}`)
  }

  const handleLaunch = async () => {
    if (!selectedModel || selectedBenchmarks.size === 0) return
    setCreating(true)
    try {
      const body: EvaluationCreate = {
        model_id: selectedModel.id,
        display_name: displayName || undefined,
        benchmark_ids: [...selectedBenchmarks],
        eval_scope: evalScope,
        sample_count: evalScope === 'sample' ? sampleCount : undefined,
        eval_batch_size: batchSize,
        timeout_seconds: timeout,
        temperature: temperature ? parseFloat(temperature) : undefined,
        max_tokens: maxTokens ? parseInt(maxTokens) : undefined,
        thinking_mode: thinkingMode || undefined,
        reasoning_effort: thinkingMode === 'enabled' ? reasoningEffort : undefined,
      }
      const run = await api.evaluations.create(body)
      await api.evaluations.start(run.id)
      nav(`/progress/${run.id}`)
    } catch (e) {
      alert(`Error: ${e}`)
    } finally {
      setCreating(false)
    }
  }

  const canNext: Record<number, boolean> = {
    1: !!selectedModel,
    2: true,
    3: selectedBenchmarks.size > 0,
    4: true,
    5: true,
  }

  const nextLabel: Record<number, string> = {
    1: 'Next: Configure →',
    2: 'Next: Benchmarks →',
    3: 'Next: Execution →',
    4: 'Review →',
    5: '⚡ Launch Evaluation',
  }

  const steps = STEP_META.map(s => s.title)
  const meta = STEP_META[step - 1]

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-6 overflow-x-auto pb-1">
        {steps.map((label, i) => (
          <div key={i} className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => i + 1 < step && setStep(i + 1)}
              className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center transition-colors
                ${step === i + 1 ? 'bg-do-blue text-white' :
                  step > i + 1 ? 'bg-green-600 text-white cursor-pointer' :
                  'bg-gray-200 text-gray-500'}`}
            >
              {step > i + 1 ? '✓' : i + 1}
            </button>
            <span className={`text-xs hidden sm:block ${step === i + 1 ? 'text-gray-800 font-medium' : 'text-gray-500'}`}>{label}</span>
            {i < steps.length - 1 && <div className={`h-px w-4 ${step > i + 1 ? 'bg-green-600' : 'bg-gray-300'}`} />}
          </div>
        ))}
      </div>

      {/* Step header with description */}
      <div className="mb-5 pb-4 border-b border-do-grey-200">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-gray-800">{meta.title}</h2>
            <p className="text-sm text-gray-600 mt-0.5 max-w-xl">{meta.desc}</p>
          </div>
          {/* Top nav buttons */}
          <div className="flex gap-2 shrink-0">
            {step > 1 && (
              <button className="btn-secondary text-sm" onClick={() => setStep(step - 1)}>← Back</button>
            )}
            {step < 5 && (
              <button
                className="btn-primary text-sm"
                disabled={!canNext[step]}
                onClick={() => setStep(step + 1)}
              >
                {nextLabel[step]}
              </button>
            )}
            {step === 5 && (
              <button className="btn-primary text-sm px-5" onClick={handleLaunch} disabled={creating}>
                {creating ? 'Launching…' : '⚡ Launch'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── STEP 1: SELECT MODEL ─────────────────────────────────────────── */}
      {step === 1 && (
        <div className="space-y-4">
          <input className="input max-w-sm" placeholder="Search models…" value={modelSearch} onChange={e => setModelSearch(e.target.value)} />
          {models.length === 0 && (
            <div className="card text-center py-10">
              <p className="text-3xl mb-3">◈</p>
              <p className="font-semibold text-gray-700">No models configured</p>
              <p className="text-sm text-gray-600 mt-1">Add an OpenAI-compatible endpoint to get started.</p>
              <a href="/models" className="btn-primary mt-4 inline-flex">Add a Model →</a>
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {models.map(m => (
              <ModelCard key={m.id} model={m} onSelect={setSelectedModel} selected={selectedModel?.id === m.id} />
            ))}
          </div>
          <div className="flex justify-end pt-2">
            <button className="btn-primary" disabled={!selectedModel} onClick={() => setStep(2)}>
              Next: Configure →
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 2: CONFIGURE ENDPOINT ───────────────────────────────────── */}
      {step === 2 && selectedModel && (
        <div className="space-y-4">
          <div className="card flex items-center gap-4 py-3">
            <div className="w-9 h-9 rounded-lg bg-do-blue/10 flex items-center justify-center text-do-blue font-bold text-lg shrink-0">
              {selectedModel.name[0]}
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800">{selectedModel.name}</p>
              <p className="text-xs text-gray-600 font-mono">{selectedModel.endpoint_url} · {selectedModel.model_id}</p>
            </div>
          </div>

          {selectedModel.supports_reasoning ? (
            <div className="card space-y-4">
              <h3 className="text-sm font-semibold text-gray-700">Reasoning / Thinking</h3>
              <div>
                <label className="label">Thinking Mode</label>
                <div className="flex gap-2">
                  {(['', 'enabled', 'disabled'] as const).map(v => (
                    <button key={v} onClick={() => setThinkingMode(v)}
                      className={`px-3 py-1.5 rounded text-xs border transition-colors
                        ${thinkingMode === v ? 'bg-do-blue border-do-blue text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                      {v || 'Default'}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-gray-500 mt-1">Default uses the model's standard behavior. Enable to activate extended thinking tokens.</p>
              </div>
              {thinkingMode === 'enabled' && (
                <div>
                  <label className="label">Reasoning Effort</label>
                  <div className="flex gap-2">
                    {(['low', 'medium', 'high'] as const).map(v => (
                      <button key={v} onClick={() => setReasoningEffort(v)}
                        className={`px-3 py-1.5 rounded text-xs border transition-colors
                          ${reasoningEffort === v ? 'bg-do-blue border-do-blue text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                        {v}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="card bg-gray-50 border-gray-200">
              <p className="text-sm text-gray-600">This model does not have reasoning/thinking capabilities. No additional configuration needed.</p>
            </div>
          )}

          <div className="flex items-center gap-3">
            <button className="btn-secondary text-xs" onClick={handleTestConnection}>Test Connection</button>
            {testResult && (
              <span className={`text-xs font-medium ${testResult.startsWith('✓') ? 'text-green-600' : 'text-red-600'}`}>{testResult}</span>
            )}
          </div>

          <div className="flex justify-between pt-2">
            <button className="btn-secondary" onClick={() => setStep(1)}>← Back</button>
            <button className="btn-primary" onClick={() => setStep(3)}>Next: Benchmarks →</button>
          </div>
        </div>
      )}

      {/* ── STEP 3: SELECT BENCHMARKS ────────────────────────────────────── */}
      {step === 3 && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            {/* Category tabs */}
            {CATEGORIES.map(cat => (
              <button key={cat} onClick={() => setBenchCat(cat)}
                className={`px-3 py-1 rounded text-xs border transition-colors
                  ${benchCat === cat ? 'bg-do-blue border-do-blue text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                {cat}
              </button>
            ))}
            <input className="input max-w-xs text-xs" placeholder="Search…" value={benchSearch} onChange={e => setBenchSearch(e.target.value)} />
            <span className="text-xs text-gray-500 ml-auto">{selectedBenchmarks.size} selected</span>
          </div>

          {benchmarks.length === 0 && (
            <div className="card text-center py-8">
              <p className="text-gray-600 text-sm">No benchmarks found for this filter.</p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {benchmarks.map(b => {
              const visionBlocked = b.is_vision && !selectedModel?.supports_vision
              const toolBlocked   = b.requires_tools && !selectedModel?.supports_tool_calling
              const disabled = visionBlocked || toolBlocked
              return (
                <BenchmarkCard
                  key={b.id}
                  bench={b}
                  selected={selectedBenchmarks.has(b.id)}
                  onToggle={toggleBenchmark}
                  disabled={disabled}
                  disabledReason={visionBlocked ? 'Model does not support vision' : 'Model does not support tool calling'}
                />
              )
            })}
          </div>

          <div className="flex justify-between pt-2">
            <button className="btn-secondary" onClick={() => setStep(2)}>← Back</button>
            <button className="btn-primary" disabled={selectedBenchmarks.size === 0} onClick={() => setStep(4)}>
              Next: Execution →
            </button>
          </div>
        </div>
      )}

      {/* ── STEP 4: CONFIGURE EXECUTION ──────────────────────────────────── */}
      {step === 4 && (
        <div className="space-y-4">
          <div>
            <label className="label">Run Name (optional)</label>
            <input className="input" placeholder="e.g. Kimi K2.6 Think Mode — AIME+OCR" value={displayName} onChange={e => setDisplayName(e.target.value)} />
          </div>

          <div>
            <label className="label">Evaluation Scope</label>
            <div className="flex gap-2">
              {(['sample', 'full'] as const).map(v => (
                <button key={v} onClick={() => setEvalScope(v)}
                  className={`px-4 py-2 rounded text-sm border transition-colors
                    ${evalScope === v ? 'bg-do-blue border-do-blue text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                  {v === 'sample' ? 'Sample Run' : 'Full Benchmark'}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-500 mt-1">
              {evalScope === 'sample'
                ? 'Runs a random subset of each benchmark. Faster and cheaper, good for iteration.'
                : 'Runs the full dataset for each benchmark. Takes longer but gives definitive scores.'}
            </p>
          </div>

          {evalScope === 'sample' && (
            <div>
              <label className="label">Sample Count per Benchmark</label>
              <div className="flex gap-2 flex-wrap">
                {[10, 25, 50, 100].map(n => (
                  <button key={n} onClick={() => setSampleCount(n)}
                    className={`px-3 py-1.5 rounded text-xs border transition-colors
                      ${sampleCount === n ? 'bg-do-blue border-do-blue text-white' : 'bg-white border-gray-300 text-gray-600'}`}>
                    {n}
                  </button>
                ))}
                <input
                  type="number"
                  className="input w-24 text-xs"
                  value={sampleCount}
                  onChange={e => setSampleCount(parseInt(e.target.value) || 50)}
                  min={1}
                />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Batch Size</label>
              <input type="number" className="input" value={batchSize} onChange={e => setBatchSize(parseInt(e.target.value) || 8)} min={1} max={32} />
              <p className="text-xs text-gray-500 mt-1">Concurrent requests per benchmark. Higher = faster but may hit rate limits.</p>
            </div>
            <div>
              <label className="label">Timeout per Request (s)</label>
              <input type="number" className="input" value={timeout} onChange={e => setTimeout_(parseInt(e.target.value) || 120)} min={10} />
            </div>
            <div>
              <label className="label">Temperature</label>
              <input type="number" className="input" placeholder="model default" value={temperature} onChange={e => setTemperature(e.target.value)} step={0.1} min={0} max={2} />
            </div>
            <div>
              <label className="label">Max Tokens</label>
              <input type="number" className="input" placeholder="model default" value={maxTokens} onChange={e => setMaxTokens(e.target.value)} />
            </div>
          </div>

          <div className="flex justify-between pt-2">
            <button className="btn-secondary" onClick={() => setStep(3)}>← Back</button>
            <button className="btn-primary" onClick={() => setStep(5)}>Review →</button>
          </div>
        </div>
      )}

      {/* ── STEP 5: REVIEW & LAUNCH ──────────────────────────────────────── */}
      {step === 5 && (
        <div className="space-y-4">
          <div className="card space-y-3">
            <Row label="Model" value={`${selectedModel?.name} (${selectedModel?.model_id})`} />
            <Row label="Benchmarks" value={`${selectedBenchmarks.size} selected`} />
            <Row label="Scope" value={evalScope === 'full' ? 'Full Benchmark' : `${sampleCount} samples per benchmark`} />
            <Row label="Batch Size" value={batchSize} />
            {thinkingMode && <Row label="Thinking" value={`${thinkingMode}${thinkingMode === 'enabled' ? ` (${reasoningEffort})` : ''}`} />}
            {temperature && <Row label="Temperature" value={temperature} />}
            {displayName && <Row label="Run Name" value={displayName} />}
          </div>

          <div className="card border-amber-200 bg-amber-50">
            <div className="flex gap-2">
              <span className="text-amber-500 shrink-0">ℹ</span>
              <p className="text-xs text-amber-800">
                The evaluation runs in the background. You'll be taken to a live progress view immediately after launch and can cancel at any time.
              </p>
            </div>
          </div>

          <div className="flex justify-between pt-2">
            <button className="btn-secondary" onClick={() => setStep(4)}>← Back</button>
            <button className="btn-primary text-base px-6 py-2.5" onClick={handleLaunch} disabled={creating}>
              {creating ? 'Launching…' : '⚡ Launch Evaluation'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-baseline justify-between text-sm border-b border-gray-100 pb-2 last:border-0 last:pb-0">
      <span className="text-gray-600">{label}</span>
      <span className="text-gray-800 font-medium text-right">{String(value)}</span>
    </div>
  )
}

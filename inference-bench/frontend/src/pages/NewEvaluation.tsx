/**
 * 6-step evaluation wizard — all steps in one file.
 * State: `step` drives which section renders.
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Model, BenchmarkSuite, EvaluationCreate } from '../types'
import ModelCard from '../components/ModelCard'
import BenchmarkCard from '../components/BenchmarkCard'

const CATEGORIES = ['All', 'math', 'coding', 'vision', 'general', 'science', 'reasoning', 'tool_calling', 'compliance']

export default function NewEvaluation() {
  const nav = useNavigate()
  const [step, setStep] = useState(1)

  // Step 1 — model selection
  const [models, setModels] = useState<Model[]>([])
  const [modelSearch, setModelSearch] = useState('')
  const [selectedModel, setSelectedModel] = useState<Model | null>(null)

  // Step 2 — endpoint config
  const [thinkingMode, setThinkingMode] = useState<'enabled' | 'disabled' | ''>('')
  const [reasoningEffort, setReasoningEffort] = useState<'low' | 'medium' | 'high'>('medium')

  // Step 3 — benchmark selection
  const [benchmarks, setBenchmarks] = useState<BenchmarkSuite[]>([])
  const [selectedBenchmarks, setSelectedBenchmarks] = useState<Set<string>>(new Set())
  const [benchCat, setBenchCat] = useState('All')
  const [benchSearch, setBenchSearch] = useState('')

  // Step 4 — execution config
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

  const steps = ['Select Model', 'Configure', 'Benchmarks', 'Execution', 'Review & Launch']

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {steps.map((label, i) => (
          <div key={i} className="flex items-center gap-2">
            <button
              onClick={() => i + 1 < step && setStep(i + 1)}
              className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center transition-colors
                ${step === i + 1 ? 'bg-brand-600 text-white' :
                  step > i + 1 ? 'bg-green-700 text-white cursor-pointer' :
                  'bg-gray-200 text-gray-600'}`}
            >
              {step > i + 1 ? '✓' : i + 1}
            </button>
            <span className={`text-xs hidden sm:block ${step === i + 1 ? 'text-gray-800 font-medium' : 'text-gray-600'}`}>{label}</span>
            {i < steps.length - 1 && <div className={`h-px w-4 ${step > i + 1 ? 'bg-green-700' : 'bg-gray-300'}`} />}
          </div>
        ))}
      </div>

      {/* ── STEP 1: SELECT MODEL ─────────────────────────────────────────── */}
      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-lg font-bold text-gray-800">Select Model</h2>
          <input className="input max-w-sm" placeholder="Search models…" value={modelSearch} onChange={e => setModelSearch(e.target.value)} />
          {models.length === 0 && (
            <div className="card text-center py-10">
              <p className="text-gray-600 text-sm">No models configured.</p>
              <a href="/models" className="text-brand-400 text-sm hover:underline mt-1 block">Add a model →</a>
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
          <h2 className="text-lg font-bold text-gray-800">Configure Endpoint</h2>

          <div className="card space-y-2">
            <p className="text-sm font-semibold text-gray-800">{selectedModel.name}</p>
            <p className="text-xs text-gray-600 font-mono">{selectedModel.endpoint_url}</p>
            <p className="text-xs text-gray-600">{selectedModel.model_id}</p>
          </div>

          {selectedModel.supports_reasoning && (
            <div className="card space-y-4">
              <h3 className="text-sm font-semibold text-gray-700">Reasoning / Thinking</h3>
              <div>
                <label className="label">Thinking Mode</label>
                <div className="flex gap-2">
                  {(['', 'enabled', 'disabled'] as const).map(v => (
                    <button key={v} onClick={() => setThinkingMode(v)}
                      className={`px-3 py-1.5 rounded-lg text-xs border transition-colors
                        ${thinkingMode === v ? 'bg-brand-600 border-brand-600 text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                      {v || 'Default'}
                    </button>
                  ))}
                </div>
              </div>
              {thinkingMode === 'enabled' && (
                <div>
                  <label className="label">Reasoning Effort</label>
                  <div className="flex gap-2">
                    {(['low', 'medium', 'high'] as const).map(v => (
                      <button key={v} onClick={() => setReasoningEffort(v)}
                        className={`px-3 py-1.5 rounded-lg text-xs border transition-colors
                          ${reasoningEffort === v ? 'bg-brand-600 border-brand-600 text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                        {v}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <button className="btn-secondary text-xs" onClick={handleTestConnection}>Test Connection</button>
            {testResult && (
              <span className={`text-xs ${testResult.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>{testResult}</span>
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
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-800">Select Benchmarks</h2>
            <span className="badge-blue">{selectedBenchmarks.size} selected</span>
          </div>

          {/* Category tabs */}
          <div className="flex gap-1 flex-wrap">
            {CATEGORIES.map(cat => (
              <button key={cat} onClick={() => setBenchCat(cat)}
                className={`px-3 py-1 rounded-lg text-xs border transition-colors
                  ${benchCat === cat ? 'bg-brand-600 border-brand-600 text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                {cat}
              </button>
            ))}
          </div>

          <input className="input max-w-sm" placeholder="Search benchmarks…" value={benchSearch} onChange={e => setBenchSearch(e.target.value)} />

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
          <h2 className="text-lg font-bold text-gray-800">Configure Execution</h2>

          <div>
            <label className="label">Run Name (optional)</label>
            <input className="input" placeholder="e.g. Kimi K2.6 Think Mode — AIME+OCR" value={displayName} onChange={e => setDisplayName(e.target.value)} />
          </div>

          <div>
            <label className="label">Evaluation Scope</label>
            <div className="flex gap-2">
              {(['sample', 'full'] as const).map(v => (
                <button key={v} onClick={() => setEvalScope(v)}
                  className={`px-4 py-2 rounded-lg text-sm border transition-colors
                    ${evalScope === v ? 'bg-brand-600 border-brand-600 text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'}`}>
                  {v === 'sample' ? 'Sample Run' : 'Full Benchmark'}
                </button>
              ))}
            </div>
          </div>

          {evalScope === 'sample' && (
            <div>
              <label className="label">Sample Count</label>
              <div className="flex gap-2 flex-wrap">
                {[10, 25, 50, 100].map(n => (
                  <button key={n} onClick={() => setSampleCount(n)}
                    className={`px-3 py-1.5 rounded-lg text-xs border transition-colors
                      ${sampleCount === n ? 'bg-brand-600 border-brand-600 text-white' : 'bg-white border-gray-300 text-gray-600'}`}>
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
            </div>
            <div>
              <label className="label">Timeout (s)</label>
              <input type="number" className="input" value={timeout} onChange={e => setTimeout_(parseInt(e.target.value) || 120)} min={10} />
            </div>
            <div>
              <label className="label">Temperature</label>
              <input type="number" className="input" placeholder="default" value={temperature} onChange={e => setTemperature(e.target.value)} step={0.1} min={0} max={2} />
            </div>
            <div>
              <label className="label">Max Tokens</label>
              <input type="number" className="input" placeholder="default" value={maxTokens} onChange={e => setMaxTokens(e.target.value)} />
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
          <h2 className="text-lg font-bold text-gray-800">Review & Launch</h2>

          <div className="card space-y-3">
            <Row label="Model" value={`${selectedModel?.name} (${selectedModel?.model_id})`} />
            <Row label="Benchmarks" value={`${selectedBenchmarks.size} selected`} />
            <Row label="Scope" value={evalScope === 'full' ? 'Full Benchmark' : `${sampleCount} samples`} />
            <Row label="Batch Size" value={batchSize} />
            {thinkingMode && <Row label="Thinking" value={`${thinkingMode}${thinkingMode === 'enabled' ? ` (${reasoningEffort})` : ''}`} />}
            {temperature && <Row label="Temperature" value={temperature} />}
            {displayName && <Row label="Run Name" value={displayName} />}
          </div>

          <div className="card bg-yellow-900/10 border-yellow-800/40">
            <p className="text-xs text-yellow-400">
              This will start a background evaluation. You can monitor progress and cancel at any time.
            </p>
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
    <div className="flex items-baseline justify-between text-sm">
      <span className="text-gray-600">{label}</span>
      <span className="text-gray-800 font-medium text-right">{String(value)}</span>
    </div>
  )
}

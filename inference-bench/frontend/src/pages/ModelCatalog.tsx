import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Model, ModelCreate, ConnectionTestResult, ValidationRun } from '../types'
import ModelCard from '../components/ModelCard'

const BLANK: ModelCreate = {
  name: '', provider: '', endpoint_url: '', model_id: '', api_key: '',
  supports_vision: false, supports_tool_calling: false,
  supports_structured_output: false, supports_reasoning: false, supports_multimodal: false,
  reasoning_format: '', custom_headers: '{}', is_custom: true,
}

const HEALTH_COLOR = (pct: number | null) =>
  pct === null ? 'text-gray-600' :
  pct >= 90 ? 'text-green-400' :
  pct >= 70 ? 'text-yellow-400' : 'text-red-400'

export default function ModelCatalog() {
  const [models, setModels] = useState<Model[]>([])
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState<ModelCreate>(BLANK)
  const [saving, setSaving] = useState(false)
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({})
  const [latestValidations, setLatestValidations] = useState<Record<string, ValidationRun>>({})

  // Quick probe state (in Add Model modal)
  const [probeRunning, setProbeRunning] = useState(false)
  const [probeResults, setProbeResults] = useState<Array<{ check_id: string; name: string; status: string }> | null>(null)

  const refresh = () => api.models.list({ search }).then(setModels)

  useEffect(() => { refresh() }, [search])

  // Fetch latest validation badge for each model
  useEffect(() => {
    models.forEach(m => {
      api.validation.latest(m.id)
        .then(vr => setLatestValidations(prev => ({ ...prev, [m.id]: vr })))
        .catch(() => {}) // no validation yet — fine
    })
  }, [models.map(m => m.id).join(',')])

  const handleCreate = async () => {
    setSaving(true)
    try {
      await api.models.create(form)
      setShowAdd(false)
      setForm(BLANK)
      setProbeResults(null)
      refresh()
    } catch (e) {
      alert(`Error: ${e}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this model?')) return
    await api.models.delete(id)
    refresh()
  }

  const handleTest = async (id: string) => {
    const r = await api.models.test(id)
    setTestResults(prev => ({ ...prev, [id]: r }))
  }

  const handleQuickProbe = async () => {
    if (!form.endpoint_url || !form.api_key || !form.model_id) return
    setProbeRunning(true)
    setProbeResults(null)
    try {
      const res = await api.probe({
        endpoint_url: form.endpoint_url,
        api_key: form.api_key,
        model_id: form.model_id,
        checks: ['connectivity', 'basic_completion', 'usage_object', 'streaming_basic', 'function_calling'],
      })
      setProbeResults(res as Array<{ check_id: string; name: string; status: string }>)
    } catch (e) {
      alert(String(e))
    } finally {
      setProbeRunning(false)
    }
  }

  const field = (k: keyof ModelCreate) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value }))

  const validationBadge = (m: Model) => {
    const vr = latestValidations[m.id]
    if (!vr) return null
    const pct = vr.total_checks > 0
      ? Math.round((vr.passed / Math.max(vr.total_checks - vr.skipped, 1)) * 100)
      : null
    return (
      <div className={`text-xs font-mono ${HEALTH_COLOR(pct)}`}>
        {pct !== null ? `${pct}% health` : ''}
        <span className="text-gray-600 ml-1">{vr.passed}✓ {vr.warned}⚠ {vr.failed}✗</span>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Models</h1>
          <p className="text-sm text-gray-500 mt-0.5">{models.length} models configured</p>
        </div>
        <div className="flex gap-2">
          <Link to="/probe" className="btn-secondary text-sm">⚡ Quick Probe</Link>
          <button className="btn-primary" onClick={() => setShowAdd(true)}>＋ Add Model</button>
        </div>
      </div>

      <input
        className="input max-w-sm"
        placeholder="Search models…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      {models.length === 0 && !showAdd && (
        <div className="card text-center py-12">
          <p className="text-gray-500">No models yet. Add your first endpoint.</p>
          <button className="btn-primary mt-4" onClick={() => setShowAdd(true)}>＋ Add Model</button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {models.map(m => (
          <div key={m.id} className="relative">
            <ModelCard model={m} onTest={handleTest} />

            {/* Validation health badge */}
            {latestValidations[m.id] && (
              <div className="mt-1 px-2">{validationBadge(m)}</div>
            )}

            {/* Test result */}
            {testResults[m.id] && (
              <div className={`mt-1 text-xs px-2 py-1 rounded ${testResults[m.id].ok ? 'text-green-400 bg-green-900/20' : 'text-red-400 bg-red-900/20'}`}>
                {testResults[m.id].ok
                  ? `✓ Connected (${testResults[m.id].latency_ms?.toFixed(0)}ms)`
                  : `✗ ${testResults[m.id].error}`}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-1 mt-2">
              <Link
                to={`/validate/${m.id}`}
                className="btn-secondary text-xs py-1 flex-1 text-center"
              >
                ✓ Validate
              </Link>
              <Link
                to={`/validate/${m.id}?tab=stress`}
                className="btn-secondary text-xs py-1 flex-1 text-center"
              >
                ⚡ Stress
              </Link>
            </div>

            <button
              className="absolute top-3 right-3 text-gray-600 hover:text-red-400 text-xs"
              onClick={() => handleDelete(m.id)}
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      {/* Add modal */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg p-6 overflow-y-auto max-h-[90vh]">
            <h2 className="text-lg font-bold text-gray-100 mb-4">Add Custom Model</h2>

            {/* Quick Probe section */}
            <div className="bg-gray-800/50 rounded-xl p-3 mb-4 space-y-2">
              <p className="text-xs font-semibold text-gray-400">Quick Probe (optional)</p>
              <p className="text-xs text-gray-500">Enter URL, key, and model ID below, then test before saving.</p>
              <button
                className="btn-secondary text-xs py-1 w-full"
                onClick={handleQuickProbe}
                disabled={probeRunning || !form.endpoint_url || !form.api_key || !form.model_id}
              >
                {probeRunning ? (
                  <span className="flex items-center justify-center gap-1">
                    <span className="animate-spin inline-block w-2.5 h-2.5 border-2 border-white/20 border-t-white rounded-full" />
                    Probing 5 checks…
                  </span>
                ) : '⚡ Quick Probe (5 checks)'}
              </button>
              {probeResults && (
                <div className="space-y-1">
                  {probeResults.map(r => (
                    <div key={r.check_id} className="flex items-center gap-2 text-xs">
                      <span className={
                        r.status === 'pass' ? 'text-green-400' :
                        r.status === 'warn' ? 'text-yellow-400' :
                        r.status === 'skip' ? 'text-gray-500' : 'text-red-400'
                      }>
                        {r.status === 'pass' ? '✓' : r.status === 'warn' ? '⚠' : r.status === 'skip' ? '—' : '✗'}
                      </span>
                      <span className="text-gray-300">{r.name}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-3">
              {([['name','Name *'],['provider','Provider *'],['endpoint_url','Endpoint URL *'],['model_id','Model ID *'],['api_key','API Key']] as const).map(([k, lbl]) => (
                <div key={k}>
                  <label className="label">{lbl}</label>
                  <input
                    className="input"
                    type={k === 'api_key' ? 'password' : 'text'}
                    value={String(form[k] ?? '')}
                    onChange={field(k)}
                    placeholder={k === 'endpoint_url' ? 'https://inference.do-ai.run/v1' : k === 'model_id' ? 'moonshotai/Kimi-K2.6' : ''}
                  />
                </div>
              ))}

              <div>
                <label className="label">Reasoning Format</label>
                <select className="input" value={form.reasoning_format ?? ''} onChange={field('reasoning_format')}>
                  <option value="">None</option>
                  <option value="chat_template_kwargs">chat_template_kwargs (Kimi K2)</option>
                  <option value="thinking_type">thinking_type (Claude)</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-1">
                {(['supports_vision','supports_tool_calling','supports_reasoning','supports_multimodal','supports_structured_output'] as const).map(k => (
                  <label key={k} className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                    <input type="checkbox" checked={!!form[k]} onChange={field(k)} />
                    {k.replace('supports_', '')}
                  </label>
                ))}
              </div>
            </div>

            <div className="flex gap-2 mt-5">
              <button className="btn-primary flex-1" onClick={handleCreate} disabled={saving || !form.name || !form.endpoint_url}>
                {saving ? 'Saving…' : 'Add Model'}
              </button>
              <button className="btn-secondary" onClick={() => { setShowAdd(false); setProbeResults(null) }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

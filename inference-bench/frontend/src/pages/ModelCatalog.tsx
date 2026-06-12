import { useState, useEffect } from 'react'
import { api } from '../api'
import type { Model, ModelCreate, ConnectionTestResult } from '../types'
import ModelCard from '../components/ModelCard'

const BLANK: ModelCreate = {
  name: '', provider: '', endpoint_url: '', model_id: '', api_key: '',
  supports_vision: false, supports_tool_calling: false,
  supports_structured_output: false, supports_reasoning: false, supports_multimodal: false,
  reasoning_format: '', custom_headers: '{}', is_custom: true,
}

export default function ModelCatalog() {
  const [models, setModels] = useState<Model[]>([])
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState<ModelCreate>(BLANK)
  const [saving, setSaving] = useState(false)
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({})

  const refresh = () => api.models.list({ search }).then(setModels)

  useEffect(() => { refresh() }, [search])

  const handleCreate = async () => {
    setSaving(true)
    try {
      await api.models.create(form)
      setShowAdd(false)
      setForm(BLANK)
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

  const field = (k: keyof ModelCreate) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({ ...f, [k]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value }))

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Models</h1>
          <p className="text-sm text-gray-500 mt-0.5">{models.length} models configured</p>
        </div>
        <button className="btn-primary" onClick={() => setShowAdd(true)}>＋ Add Model</button>
      </div>

      <input
        className="input max-w-sm"
        placeholder="Search models…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      {/* Model grid */}
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
            {testResults[m.id] && (
              <div className={`mt-1 text-xs px-2 py-1 rounded ${testResults[m.id].ok ? 'text-green-400 bg-green-900/20' : 'text-red-400 bg-red-900/20'}`}>
                {testResults[m.id].ok
                  ? `✓ Connected (${testResults[m.id].latency_ms?.toFixed(0)}ms)`
                  : `✗ ${testResults[m.id].error}`}
              </div>
            )}
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
              <button className="btn-secondary" onClick={() => setShowAdd(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

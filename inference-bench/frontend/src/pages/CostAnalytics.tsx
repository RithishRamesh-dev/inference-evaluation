import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts'
import { api } from '../api'
import type { CostSummary, ModelPricing, Model } from '../types'

export default function CostAnalytics() {
  const [summary, setSummary] = useState<CostSummary | null>(null)
  const [days, setDays] = useState(30)
  const [pricing, setPricing] = useState<ModelPricing[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [showAddPricing, setShowAddPricing] = useState(false)
  const [pricingForm, setPricingForm] = useState({ model_id: '', input: '', output: '' })
  const [saving, setSaving] = useState(false)

  const load = () => {
    api.cost.summary(days).then(setSummary)
    api.cost.pricing().then(setPricing)
  }

  useEffect(() => {
    load()
    api.models.list().then(setModels)
  }, [days])

  const savePricing = async () => {
    if (!pricingForm.model_id || !pricingForm.input || !pricingForm.output) return
    setSaving(true)
    try {
      await api.cost.addPricing({
        model_id: pricingForm.model_id,
        price_per_1k_input_tokens: parseFloat(pricingForm.input),
        price_per_1k_output_tokens: parseFloat(pricingForm.output),
      })
      setPricingForm({ model_id: '', input: '', output: '' })
      setShowAddPricing(false)
      load()
    } finally { setSaving(false) }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Cost Analytics</h1>
          <p className="text-sm text-gray-600 mt-0.5">Track and manage evaluation spending</p>
        </div>
        <div className="flex gap-2 items-center">
          {([7, 30, 90] as const).map(d => (
            <button key={d} onClick={() => setDays(d)}
              className={`text-xs px-2 py-1 rounded border transition-colors ${days === d ? 'bg-brand-600/20 border-brand-500 text-brand-400' : 'border-gray-300 text-gray-600 hover:text-gray-800'}`}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-800">${(summary?.total_cost_usd ?? 0).toFixed(4)}</p>
          <p className="text-xs text-gray-600 mt-1">Total Spend ({days}d)</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-800">{(summary?.by_model ?? []).length}</p>
          <p className="text-xs text-gray-600 mt-1">Models Evaluated</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-800">
            {summary && summary.by_model.length > 0
              ? `$${(summary.total_cost_usd / (summary.by_model.reduce((a, m) => a + m.run_count, 0) || 1)).toFixed(4)}`
              : '—'}
          </p>
          <p className="text-xs text-gray-600 mt-1">Avg per Run</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-800">{pricing.length}</p>
          <p className="text-xs text-gray-600 mt-1">Pricing Configs</p>
        </div>
      </div>

      {/* No pricing configured notice */}
      {pricing.length === 0 && (
        <div className="card border-yellow-800/40 bg-yellow-950/10 text-sm text-yellow-400 flex items-center gap-2">
          <span>⚠</span>
          <span>No pricing configured. Add model pricing below to track costs.</span>
        </div>
      )}

      {/* Daily spend chart */}
      {summary && summary.by_day.length > 0 && (
        <div className="card">
          <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-3">Daily Spend</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={summary.by_day}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={{ fill: '#6B7280', fontSize: 10 }} />
              <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} tickFormatter={(v: number) => `$${v.toFixed(3)}`} />
              <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                formatter={(v: number) => [`$${v.toFixed(4)}`, 'Cost']} />
              <Line type="monotone" dataKey="cost_usd" stroke="#0ea5e9" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Per-model breakdown */}
      {summary && summary.by_model.length > 0 && (
        <div className="card">
          <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-3">Cost by Model</h2>
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={summary.by_model}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="model_name" tick={{ fill: '#6B7280', fontSize: 10 }} />
              <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} tickFormatter={(v: number) => `$${v.toFixed(3)}`} />
              <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                formatter={(v: number) => [`$${v.toFixed(4)}`, 'Cost']} />
              <Bar dataKey="total_cost_usd" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Pricing management */}
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Model Pricing</h2>
          <button onClick={() => setShowAddPricing(p => !p)} className="btn-secondary text-xs py-1">＋ Add Pricing</button>
        </div>
        {showAddPricing && (
          <div className="grid grid-cols-3 gap-2 p-3 bg-gray-800/30 rounded-lg">
            <div>
              <label className="label">Model</label>
              <select className="input text-xs" value={pricingForm.model_id} onChange={e => setPricingForm(f => ({ ...f, model_id: e.target.value }))}>
                <option value="">Select model…</option>
                {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Input ($/1K tokens)</label>
              <input className="input text-xs" type="number" step="0.00001" placeholder="0.00059" value={pricingForm.input} onChange={e => setPricingForm(f => ({ ...f, input: e.target.value }))} />
            </div>
            <div>
              <label className="label">Output ($/1K tokens)</label>
              <input className="input text-xs" type="number" step="0.00001" placeholder="0.00079" value={pricingForm.output} onChange={e => setPricingForm(f => ({ ...f, output: e.target.value }))} />
            </div>
            <div className="col-span-3 flex gap-2">
              <button onClick={savePricing} disabled={saving} className="btn-primary text-xs py-1 flex-1">{saving ? 'Saving…' : 'Save'}</button>
              <button onClick={() => setShowAddPricing(false)} className="btn-secondary text-xs py-1">Cancel</button>
            </div>
          </div>
        )}
        <div className="space-y-2">
          {pricing.length === 0 && <p className="text-xs text-gray-600">No pricing configured</p>}
          {pricing.map(p => {
            const m = models.find(x => x.id === p.model_id)
            return (
              <div key={p.id} className="flex items-center gap-3 text-xs text-gray-600">
                <span className="flex-1 text-gray-700">{m?.name || p.model_id}</span>
                <span>In: ${p.price_per_1k_input_tokens}/1K</span>
                <span>Out: ${p.price_per_1k_output_tokens}/1K</span>
                <button onClick={() => api.cost.deletePricing(p.id).then(load)} className="text-red-600 hover:text-red-400">✕</button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { api } from '../api'
import type { ABTest, Model, BenchmarkSuite } from '../types'

export default function AbTests() {
  const [tests, setTests] = useState<ABTest[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [benchmarks, setBenchmarks] = useState<BenchmarkSuite[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: '', model_ids: [] as string[], benchmark_ids: [] as string[], sample_count: 50 })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      api.abTests.list().catch(() => [] as ABTest[]),
      api.models.list(),
      api.benchmarks.list(),
    ]).then(([t, m, b]) => {
      setTests(t)
      setModels(m)
      setBenchmarks(b)
    }).finally(() => setLoading(false))
  }, [])

  const toggleModel = (id: string) => {
    setForm(f => ({
      ...f,
      model_ids: f.model_ids.includes(id) ? f.model_ids.filter(x => x !== id) : [...f.model_ids, id],
    }))
  }

  const toggleBenchmark = (id: string) => {
    setForm(f => ({
      ...f,
      benchmark_ids: f.benchmark_ids.includes(id) ? f.benchmark_ids.filter(x => x !== id) : [...f.benchmark_ids, id],
    }))
  }

  const handleCreate = async () => {
    if (form.model_ids.length < 2 || form.benchmark_ids.length === 0 || !form.name) return
    setCreating(true)
    setError(null)
    try {
      const test = await api.abTests.create({
        name: form.name,
        model_ids: form.model_ids,
        benchmark_ids: form.benchmark_ids,
        sample_count: form.sample_count,
        eval_scope: 'sample',
      })
      setTests(prev => [test, ...prev])
      setShowCreate(false)
      setForm({ name: '', model_ids: [], benchmark_ids: [], sample_count: 50 })
    } catch (e) {
      setError(String(e))
    } finally {
      setCreating(false)
    }
  }

  const statusColor: Record<string, string> = {
    completed: 'badge-green',
    running: 'badge-blue',
    failed: 'badge-red',
    queued: 'badge-gray',
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">A/B Tests</h1>
          <p className="text-sm text-gray-600 mt-0.5">Run the same benchmarks against multiple models simultaneously</p>
        </div>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>+ New A/B Test</button>
      </div>

      {showCreate && (
        <div className="card space-y-4">
          <h2 className="text-sm font-semibold text-gray-700">Create A/B Test</h2>

          <div>
            <label className="label">Test Name</label>
            <input className="input" placeholder="e.g. GPT-4o vs Claude 3.5" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>

          <div>
            <label className="label">Select Models (2–4)</label>
            <div className="flex flex-wrap gap-2 mt-1">
              {models.map(m => (
                <button
                  key={m.id}
                  onClick={() => toggleModel(m.id)}
                  className={`px-3 py-1 rounded text-xs border transition-colors ${
                    form.model_ids.includes(m.id)
                      ? 'bg-do-blue text-white border-do-blue'
                      : 'bg-white text-gray-600 border-do-grey-200 hover:border-do-blue'
                  }`}
                >
                  {m.name}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="label">Select Benchmarks</label>
            <div className="flex flex-wrap gap-2 mt-1">
              {benchmarks.filter(b => b.is_recommended).slice(0, 12).map(b => (
                <button
                  key={b.id}
                  onClick={() => toggleBenchmark(b.id)}
                  className={`px-3 py-1 rounded text-xs border transition-colors ${
                    form.benchmark_ids.includes(b.id)
                      ? 'bg-do-blue text-white border-do-blue'
                      : 'bg-white text-gray-600 border-do-grey-200 hover:border-do-blue'
                  }`}
                >
                  {b.display_name}
                </button>
              ))}
            </div>
          </div>

          <div className="w-48">
            <label className="label">Samples per benchmark</label>
            <input type="number" className="input" value={form.sample_count} min={10} max={200}
              onChange={e => setForm(f => ({ ...f, sample_count: Number(e.target.value) }))} />
          </div>

          {error && <p className="text-sm text-do-red">{error}</p>}

          <div className="flex gap-2">
            <button
              className="btn-primary"
              onClick={handleCreate}
              disabled={creating || form.model_ids.length < 2 || form.benchmark_ids.length === 0 || !form.name}
            >
              {creating ? 'Creating…' : 'Start A/B Test'}
            </button>
            <button className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-600">Loading…</p>
      ) : tests.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-3xl mb-3">⚖</p>
          <p className="font-semibold text-gray-700">No A/B tests yet</p>
          <p className="text-sm text-gray-600 mt-1">Compare multiple models head-to-head on the same benchmarks</p>
          <button className="btn-primary mt-4" onClick={() => setShowCreate(true)}>Create First A/B Test</button>
        </div>
      ) : (
        <div className="space-y-3">
          {tests.map(t => (
            <div key={t.id} className="card">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-800">{t.name}</p>
                  <p className="text-xs text-gray-600 mt-0.5">
                    {t.model_ids.length} models · {t.benchmark_ids.length} benchmarks · {t.sample_count} samples
                  </p>
                </div>
                <span className={`badge ${statusColor[t.status] ?? 'badge-gray'}`}>{t.status}</span>
              </div>
              {t.run_ids.length > 0 && (
                <div className="mt-3 flex gap-2">
                  {t.run_ids.map(rid => (
                    <a key={rid} href={`/results/${rid}`} className="text-xs text-do-blue hover:underline">
                      Run {rid.slice(-6)}
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

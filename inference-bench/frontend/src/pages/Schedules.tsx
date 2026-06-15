import { useState, useEffect } from 'react'
import { api } from '../api'
import type { Model, ScheduledEval } from '../types'

const PRESETS = [
  { label: 'Daily (9am)', cron: '0 9 * * *' },
  { label: 'Weekly (Mon)', cron: '0 9 * * 1' },
  { label: 'Biweekly', cron: '0 9 * * 1/2' },
  { label: 'Monthly (1st)', cron: '0 9 1 * *' },
]

export default function Schedules() {
  const [schedules, setSchedules] = useState<ScheduledEval[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [benchmarks, setBenchmarks] = useState<Array<{ id: string; display_name: string }>>([])
  const [showCreate, setShowCreate] = useState(false)
  const [cronDesc, setCronDesc] = useState('')
  const [form, setForm] = useState({ model_id: '', cron: '0 9 * * 1', benchmark_ids: [] as string[], email: '' })
  const [creating, setCreating] = useState(false)

  const load = () => api.schedules.list().then(setSchedules)

  useEffect(() => {
    load()
    api.models.list().then(setModels)
    api.benchmarks.list({}).then(b => setBenchmarks(b.map(x => ({ id: x.id, display_name: x.display_name }))))
  }, [])

  useEffect(() => {
    if (form.cron) {
      api.schedules.previewCron(form.cron).then(r => setCronDesc(r.description)).catch(() => setCronDesc('Invalid cron'))
    }
  }, [form.cron])

  const createSchedule = async () => {
    if (!form.model_id || !form.cron || form.benchmark_ids.length === 0) return
    setCreating(true)
    try {
      await api.schedules.create({ model_id: form.model_id, benchmark_ids: form.benchmark_ids, schedule_cron: form.cron, notification_email: form.email || undefined })
      setShowCreate(false)
      load()
    } catch (e) { alert(String(e)) }
    finally { setCreating(false) }
  }

  const toggle = async (id: string) => { await api.schedules.toggle(id); load() }
  const del = async (id: string) => { if (!confirm('Delete this schedule?')) return; await api.schedules.delete(id); load() }

  const toggleBenchmark = (id: string) => setForm(f => ({
    ...f, benchmark_ids: f.benchmark_ids.includes(id) ? f.benchmark_ids.filter(b => b !== id) : [...f.benchmark_ids, id]
  }))

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Scheduled Evaluations</h1>
          <p className="text-sm text-gray-600 mt-0.5">Run benchmarks automatically on a schedule</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">＋ Add Schedule</button>
      </div>

      {schedules.length === 0 && !showCreate && (
        <div className="card text-center py-12">
          <p className="text-3xl mb-3">🕐</p>
          <p className="text-gray-600 text-sm">No schedules yet</p>
        </div>
      )}

      <div className="space-y-3">
        {schedules.map(s => (
          <div key={s.id} className="card">
            <div className="flex items-start gap-3">
              <div className={`w-2 h-2 rounded-full mt-2 shrink-0 ${s.enabled ? 'bg-green-500' : 'bg-gray-600'}`} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-800">{s.model_name || s.model_id}</p>
                <p className="text-xs text-gray-600 mt-0.5">{s.schedule_cron} · {s.benchmark_ids.length} benchmark{s.benchmark_ids.length !== 1 ? 's' : ''}</p>
                {s.next_run_at && <p className="text-xs text-gray-600 mt-0.5">Next: {new Date(s.next_run_at).toLocaleString()}</p>}
                {s.last_run_at && <p className="text-xs text-gray-700 mt-0.5">Last: {new Date(s.last_run_at).toLocaleString()}</p>}
              </div>
              <div className="flex gap-2 shrink-0">
                <button onClick={() => toggle(s.id)} className="btn-secondary text-xs py-1">{s.enabled ? 'Pause' : 'Resume'}</button>
                <button onClick={() => del(s.id)} className="text-xs text-red-500 hover:text-red-400 px-2">✕</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="card space-y-4">
          <h2 className="text-sm font-bold text-gray-800">New Schedule</h2>
          <div>
            <label className="label">Model</label>
            <select className="input" value={form.model_id} onChange={e => setForm(f => ({ ...f, model_id: e.target.value }))}>
              <option value="">Select model…</option>
              {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Schedule</label>
            <div className="flex flex-wrap gap-1 mb-2">
              {PRESETS.map(p => (
                <button key={p.cron} onClick={() => setForm(f => ({ ...f, cron: p.cron }))}
                  className={`text-xs px-2 py-1 rounded border transition-colors ${form.cron === p.cron ? 'bg-brand-600/20 border-brand-500 text-brand-400' : 'border-gray-300 text-gray-600 hover:text-gray-800'}`}>
                  {p.label}
                </button>
              ))}
            </div>
            <input className="input font-mono text-xs" value={form.cron} onChange={e => setForm(f => ({ ...f, cron: e.target.value }))} placeholder="0 9 * * 1" />
            {cronDesc && <p className="text-xs text-brand-400 mt-1">{cronDesc}</p>}
          </div>
          <div>
            <label className="label">Benchmarks ({form.benchmark_ids.length} selected)</label>
            <div className="max-h-36 overflow-y-auto space-y-1 border border-gray-200 rounded p-2">
              {benchmarks.slice(0, 30).map(b => (
                <label key={b.id} className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer hover:text-gray-800">
                  <input type="checkbox" checked={form.benchmark_ids.includes(b.id)} onChange={() => toggleBenchmark(b.id)} />
                  {b.display_name}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label className="label">Notification Email (optional)</label>
            <input className="input" type="email" placeholder="you@example.com" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
          </div>
          <div className="flex gap-2">
            <button onClick={createSchedule} disabled={creating || !form.model_id || form.benchmark_ids.length === 0} className="btn-primary flex-1">
              {creating ? 'Creating…' : 'Create Schedule'}
            </button>
            <button onClick={() => setShowCreate(false)} className="btn-secondary">Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}

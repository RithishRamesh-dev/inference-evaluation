import { useState, useEffect } from 'react'
import { api } from '../api'
import type { Model, MonitorConfig, MonitorResult } from '../types'

const STATUS_COLOR: Record<string, string> = {
  healthy: 'bg-green-500',
  degraded: 'bg-yellow-500',
  down: 'bg-red-500',
}

const STATUS_TEXT: Record<string, string> = {
  healthy: 'text-green-600',
  degraded: 'text-yellow-600',
  down: 'text-red-600',
}

export default function Monitor() {
  const [models, setModels] = useState<Model[]>([])
  const [monitors, setMonitors] = useState<MonitorConfig[]>([])
  const [selectedMonitor, setSelectedMonitor] = useState<MonitorConfig | null>(null)
  const [results, setResults] = useState<MonitorResult[]>([])
  const [uptime, setUptime] = useState<{ uptime_24h: number; uptime_7d: number; uptime_30d: number } | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newModelId, setNewModelId] = useState('')
  const [newInterval, setNewInterval] = useState(15)
  const [creating, setCreating] = useState(false)

  const load = () => api.monitors.list().then(setMonitors)

  useEffect(() => {
    api.models.list().then(setModels)
    load()
  }, [])

  const selectMonitor = (m: MonitorConfig) => {
    setSelectedMonitor(m)
    api.monitors.results(m.id, 24).then(setResults)
    api.monitors.uptime(m.id).then(setUptime)
  }

  const createMonitor = async () => {
    if (!newModelId) return
    setCreating(true)
    try {
      const m = await api.monitors.create({ model_id: newModelId, check_interval_minutes: newInterval, enabled: true })
      setShowCreate(false)
      load()
      selectMonitor(m)
    } finally { setCreating(false) }
  }

  const toggleMonitor = async (id: string) => {
    await api.monitors.toggle(id)
    load()
    if (selectedMonitor?.id === id) {
      const updated = monitors.find(m => m.id === id)
      if (updated) setSelectedMonitor({ ...updated, enabled: !updated.enabled })
    }
  }

  const deleteMonitor = async (id: string) => {
    if (!confirm('Delete this monitor?')) return
    await api.monitors.delete(id)
    if (selectedMonitor?.id === id) { setSelectedMonitor(null); setResults([]) }
    load()
  }

  // Build 24h timeline from results (last 48 buckets of 30 min each)
  const timeline = (() => {
    const buckets: Array<{ status: string; time: string }> = []
    const now = Date.now()
    for (let i = 47; i >= 0; i--) {
      const bucketTime = now - i * 30 * 60 * 1000
      const match = results.find(r => {
        const t = r.run_at ? new Date(r.run_at).getTime() : 0
        return Math.abs(t - bucketTime) < 15 * 60 * 1000
      })
      buckets.push({ status: match?.status || 'unknown', time: new Date(bucketTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) })
    }
    return buckets
  })()

  return (
    <div className="flex h-full">
      {/* Left: monitor list */}
      <div className="w-64 border-r border-do-grey-200 flex flex-col shrink-0">
        <div className="p-4 border-b border-do-grey-200">
          <div className="flex items-center justify-between mb-0.5">
            <h1 className="text-sm font-bold text-gray-800">Live Monitor</h1>
            <button onClick={() => setShowCreate(true)} className="text-xs text-do-blue hover:underline">＋ Add</button>
          </div>
          <p className="text-xs text-gray-500">Continuous health checks per model</p>
        </div>
        <div className="flex-1 overflow-y-auto">
          {monitors.length === 0 && <p className="text-xs text-gray-600 px-4 py-3">No monitors configured</p>}
          {monitors.map(m => (
            <button key={m.id} onClick={() => selectMonitor(m)}
              className={`w-full text-left px-4 py-3 border-b border-do-grey-200 hover:bg-do-grey-100 ${selectedMonitor?.id === m.id ? 'bg-do-grey-100' : ''}`}>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full shrink-0 ${m.latest_status ? STATUS_COLOR[m.latest_status] || 'bg-gray-600' : 'bg-gray-700'}`} />
                <p className="text-sm text-gray-700 truncate flex-1">{m.model_name || m.model_id}</p>
                {!m.enabled && <span className="text-[10px] text-gray-600">paused</span>}
              </div>
              <p className="text-xs text-gray-600 mt-0.5 pl-4">Every {m.check_interval_minutes}min</p>
            </button>
          ))}
        </div>
        {showCreate && (
          <div className="p-3 border-t border-do-grey-200 space-y-2">
            <select className="input text-xs" value={newModelId} onChange={e => setNewModelId(e.target.value)}>
              <option value="">Select model…</option>
              {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            <select className="input text-xs" value={newInterval} onChange={e => setNewInterval(parseInt(e.target.value))}>
              <option value={5}>Every 5 minutes</option>
              <option value={15}>Every 15 minutes</option>
              <option value={30}>Every 30 minutes</option>
              <option value={60}>Every hour</option>
            </select>
            <div className="flex gap-1">
              <button onClick={createMonitor} disabled={creating || !newModelId} className="btn-primary text-xs py-1 flex-1">{creating ? 'Creating…' : 'Create'}</button>
              <button onClick={() => setShowCreate(false)} className="btn-secondary text-xs py-1">✕</button>
            </div>
          </div>
        )}
      </div>

      {/* Right: detail */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {!selectedMonitor && (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">Select a monitor</div>
        )}
        {selectedMonitor && (
          <>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`w-3 h-3 rounded-full ${selectedMonitor.latest_status ? STATUS_COLOR[selectedMonitor.latest_status] || 'bg-gray-600' : 'bg-gray-700'}`} />
                <div>
                  <h2 className="text-base font-bold text-gray-800">{selectedMonitor.model_name}</h2>
                  <p className={`text-sm font-semibold ${selectedMonitor.latest_status ? STATUS_TEXT[selectedMonitor.latest_status] || 'text-gray-600' : 'text-gray-600'}`}>
                    {selectedMonitor.latest_status ? selectedMonitor.latest_status.charAt(0).toUpperCase() + selectedMonitor.latest_status.slice(1) : 'No data yet'}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => toggleMonitor(selectedMonitor.id)} className="btn-secondary text-xs py-1">
                  {selectedMonitor.enabled ? '⏸ Pause' : '▶ Resume'}
                </button>
                <button onClick={() => deleteMonitor(selectedMonitor.id)} className="text-xs text-red-500 hover:text-red-400 px-2">Delete</button>
              </div>
            </div>

            {/* Uptime stats */}
            {uptime && (
              <div className="grid grid-cols-3 gap-3">
                {([['24h', uptime.uptime_24h], ['7d', uptime.uptime_7d], ['30d', uptime.uptime_30d]] as [string, number][]).map(([label, val]) => (
                  <div key={label} className="card text-center">
                    <p className={`text-xl font-bold ${val >= 99 ? 'text-green-600' : val >= 95 ? 'text-yellow-600' : 'text-red-600'}`}>
                      {val.toFixed(1)}%
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">Uptime {label}</p>
                  </div>
                ))}
              </div>
            )}

            {/* Timeline */}
            <div className="card">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">24h Status Timeline</p>
              <div className="flex gap-0.5">
                {timeline.map((b, i) => (
                  <div key={i} title={`${b.time}: ${b.status}`}
                    className={`flex-1 h-8 rounded-sm ${b.status === 'healthy' ? 'bg-green-400' : b.status === 'degraded' ? 'bg-yellow-400' : b.status === 'down' ? 'bg-red-400' : 'bg-gray-200'}`} />
                ))}
              </div>
              <div className="flex justify-between text-[10px] text-gray-500 mt-1">
                <span>24h ago</span><span>Now</span>
              </div>
            </div>

            {/* Recent results */}
            <div className="card overflow-x-auto">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">Recent Checks</p>
              <table className="w-full text-xs">
                <thead><tr className="text-gray-600 border-b border-gray-200">
                  <th className="text-left py-1">Time</th>
                  <th className="text-left py-1">Status</th>
                  <th className="text-right py-1">Passed</th>
                  <th className="text-right py-1">Failed</th>
                  <th className="text-right py-1">Avg Latency</th>
                </tr></thead>
                <tbody>
                  {results.slice(0, 20).map(r => (
                    <tr key={r.id} className="border-b border-gray-100">
                      <td className="py-1 text-gray-600">{r.run_at ? new Date(r.run_at).toLocaleTimeString() : '—'}</td>
                      <td className={`py-1 font-semibold ${STATUS_TEXT[r.status] || 'text-gray-600'}`}>{r.status}</td>
                      <td className="py-1 text-right text-green-400">{r.checks_passed}</td>
                      <td className={`py-1 text-right ${r.checks_failed > 0 ? 'text-red-400' : 'text-gray-600'}`}>{r.checks_failed}</td>
                      <td className="py-1 text-right text-gray-600">{r.avg_latency_ms ? `${r.avg_latency_ms.toFixed(0)}ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {results.length === 0 && <p className="text-xs text-gray-600 py-2 text-center">No results yet — monitor will run on its next interval</p>}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

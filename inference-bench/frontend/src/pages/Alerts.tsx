import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { RegressionAlert } from '../types'

export default function Alerts() {
  const [alerts, setAlerts] = useState<RegressionAlert[]>([])
  const [showAck, setShowAck] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = () => {
    api.regressionAlerts.list(showAck ? undefined : false)
      .then(setAlerts).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [showAck])

  const ack = async (id: string) => {
    await api.regressionAlerts.acknowledge(id)
    load()
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Regression Alerts</h1>
          <p className="text-sm text-gray-600 mt-0.5">{alerts.length} {showAck ? 'total' : 'unacknowledged'} alerts</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input type="checkbox" checked={showAck} onChange={e => setShowAck(e.target.checked)} />
          Show acknowledged
        </label>
      </div>

      {loading && <p className="text-sm text-gray-600">Loading…</p>}

      {!loading && alerts.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-4xl mb-3">✅</p>
          <p className="text-gray-600 text-sm">No regression alerts</p>
          <p className="text-gray-600 text-xs mt-1">Regressions are detected automatically when benchmark scores drop &gt;5%</p>
        </div>
      )}

      <div className="space-y-3">
        {alerts.map(a => (
          <div key={a.id} className={`card ${a.acknowledged ? 'opacity-50' : 'border-red-800/40 bg-red-950/10'}`}>
            <div className="flex items-start gap-3">
              <div className={`text-2xl font-bold shrink-0 ${a.delta < -0.1 ? 'text-red-400' : 'text-yellow-400'}`}>
                {(a.delta * 100).toFixed(1)}%
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-800">
                  {a.benchmark_name || a.benchmark_suite_id}
                </p>
                <p className="text-xs text-gray-600 mt-0.5">
                  Score dropped: {(a.prev_score * 100).toFixed(1)}% → {(a.curr_score * 100).toFixed(1)}%
                </p>
                <Link to={`/results/${a.run_id}`} className="text-xs text-brand-400 hover:underline mt-1 inline-block">
                  View run →
                </Link>
              </div>
              {!a.acknowledged && (
                <button onClick={() => ack(a.id)} className="btn-secondary text-xs py-1 shrink-0">
                  Dismiss
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

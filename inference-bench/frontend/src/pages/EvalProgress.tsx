import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { ProgressData } from '../types'
import ProgressBar from '../components/ProgressBar'

export default function EvalProgress() {
  const { runId } = useParams<{ runId: string }>()
  const nav = useNavigate()
  const [progress, setProgress] = useState<ProgressData>({ status: 'queued', percent: 0, current_benchmark: null, samples_done: 0, samples_total: 0, eta_seconds: null, elapsed_seconds: 0 })
  const [cancelling, setCancelling] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!runId) return

    const es = new EventSource(api.streamUrl(runId))
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const data: ProgressData = JSON.parse(e.data)
        setProgress(data)
        if (data.status === 'completed') {
          es.close()
          setTimeout(() => nav(`/results/${runId}`), 800)
        } else if (data.status === 'failed' || data.status === 'cancelled') {
          es.close()
        }
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      // SSE reconnects automatically on network errors; ignore
    }

    return () => { es.close() }
  }, [runId])

  const handleCancel = async () => {
    if (!runId || !confirm('Cancel this evaluation?')) return
    setCancelling(true)
    try {
      await api.evaluations.cancel(runId)
    } finally {
      setCancelling(false)
    }
  }

  const elapsed = progress.elapsed_seconds
  const elapsedStr = elapsed != null ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s` : '—'
  const etaStr = progress.eta_seconds != null ? `~${Math.ceil(progress.eta_seconds / 60)}m remaining` : null

  const statusColor = {
    running: 'text-blue-400',
    completed: 'text-green-400',
    failed: 'text-red-400',
    cancelled: 'text-gray-400',
    queued: 'text-yellow-400',
  }[progress.status] ?? 'text-gray-400'

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Evaluation #{runId}</h1>
          <p className={`text-sm font-medium mt-0.5 ${statusColor}`}>{progress.status.toUpperCase()}</p>
        </div>
        {(progress.status === 'running' || progress.status === 'queued') && (
          <button className="btn-danger text-xs" onClick={handleCancel} disabled={cancelling}>
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        )}
      </div>

      {/* Overall progress */}
      <div className="card space-y-4">
        <ProgressBar
          percent={progress.percent}
          label={`Overall Progress`}
          color={progress.status === 'completed' ? 'green' : progress.status === 'failed' ? 'red' : 'blue'}
          size="lg"
        />

        {progress.current_benchmark && (
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
            <span className="text-sm text-gray-300">Running: <strong>{progress.current_benchmark}</strong></span>
          </div>
        )}

        {progress.samples_total > 0 && (
          <div>
            <ProgressBar
              percent={(progress.samples_done / progress.samples_total) * 100}
              label={`Samples: ${progress.samples_done} / ${progress.samples_total}`}
              color="blue"
              size="sm"
            />
          </div>
        )}

        <div className="flex gap-6 text-xs text-gray-500">
          <span>Elapsed: {elapsedStr}</span>
          {etaStr && <span>{etaStr}</span>}
        </div>
      </div>

      {/* Event log */}
      {progress.events && progress.events.length > 0 && (
        <div className="card">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Event Log</h3>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {[...progress.events].reverse().map((ev, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-gray-600 shrink-0 font-mono">{new Date(ev.ts as string).toLocaleTimeString()}</span>
                <span className={`${
                  ev.event === 'benchmark_complete' ? 'text-green-400' :
                  ev.event === 'benchmark_failed'   ? 'text-red-400' :
                  ev.event === 'run_complete'        ? 'text-green-300 font-semibold' :
                  'text-gray-400'
                }`}>
                  {ev.event}
                  {ev.benchmark ? ` — ${ev.benchmark}` : ''}
                  {ev.score != null ? ` (${(Number(ev.score) * 100).toFixed(1)}%)` : ''}
                  {ev.error ? `: ${ev.error}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Terminal states */}
      {progress.status === 'completed' && (
        <div className="card border-green-800/50 bg-green-900/10 text-center py-4">
          <p className="text-green-400 font-semibold">✓ Evaluation complete!</p>
          <p className="text-sm text-gray-400 mt-1">Redirecting to results…</p>
        </div>
      )}
      {progress.status === 'failed' && (
        <div className="card border-red-800/50 bg-red-900/10">
          <p className="text-red-400 font-semibold">✗ Evaluation failed</p>
          <button className="btn-secondary text-xs mt-3" onClick={() => nav(`/dashboard`)}>← Back to Dashboard</button>
        </div>
      )}
      {progress.status === 'cancelled' && (
        <div className="card border-gray-700">
          <p className="text-gray-400">Evaluation cancelled.</p>
          <button className="btn-secondary text-xs mt-3" onClick={() => nav(`/dashboard`)}>← Dashboard</button>
        </div>
      )}
    </div>
  )
}

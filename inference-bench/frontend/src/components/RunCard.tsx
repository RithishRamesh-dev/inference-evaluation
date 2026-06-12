import { Link } from 'react-router-dom'
import type { EvaluationRun } from '../types'

function statusBadge(status: string) {
  const cls: Record<string, string> = {
    completed: 'badge-green',
    running: 'badge-blue',
    failed: 'badge-red',
    cancelled: 'badge-gray',
    queued: 'badge-yellow',
  }
  return <span className={cls[status] ?? 'badge-gray'}>{status}</span>
}

interface Props {
  run: EvaluationRun
  onCompare?: (id: number) => void
  selected?: boolean
}

export default function RunCard({ run, onCompare, selected }: Props) {
  const score = run.overall_score != null ? `${(run.overall_score * 100).toFixed(1)}%` : '—'
  const created = new Date(run.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  return (
    <div className={`card hover:border-gray-700 transition-colors ${selected ? 'border-brand-600' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {statusBadge(run.status)}
            <span className="text-xs text-gray-500">{created}</span>
          </div>
          <Link
            to={run.status === 'running' ? `/progress/${run.id}` : `/results/${run.id}`}
            className="block mt-1.5 text-sm font-medium text-gray-100 hover:text-brand-400 truncate"
          >
            {run.display_name || `Run #${run.id}`}
          </Link>
          <p className="text-xs text-gray-500 mt-0.5">
            {run.model_provider} · {run.model_name}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xl font-bold text-gray-100">{score}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {run.passed_benchmarks}/{run.total_benchmarks} benchmarks
          </p>
        </div>
      </div>

      {/* Benchmark mini-bar */}
      <div className="mt-3 flex gap-1 flex-wrap">
        {run.run_benchmarks.slice(0, 8).map(rb => (
          <span
            key={rb.id}
            title={`${rb.suite_display_name ?? rb.suite_name}: ${rb.primary_score != null ? (rb.primary_score * 100).toFixed(1) + '%' : rb.status}`}
            className={`text-xs px-1.5 py-0.5 rounded ${
              rb.status === 'completed' ? 'bg-green-900/40 text-green-400' :
              rb.status === 'running'   ? 'bg-blue-900/40 text-blue-400' :
              rb.status === 'failed'    ? 'bg-red-900/40 text-red-400' :
              'bg-gray-800 text-gray-500'
            }`}
          >
            {rb.suite_name ?? `#${rb.benchmark_suite_id}`}
          </span>
        ))}
      </div>

      <div className="mt-3 flex items-center gap-2">
        {(run.status === 'running' || run.status === 'queued') && (
          <Link to={`/progress/${run.id}`} className="btn-primary text-xs py-1.5">
            View Progress
          </Link>
        )}
        {run.status === 'completed' && (
          <Link to={`/results/${run.id}`} className="btn-primary text-xs py-1.5">
            View Results
          </Link>
        )}
        {onCompare && (
          <button
            onClick={() => onCompare(run.id)}
            className={`btn-secondary text-xs py-1.5 ${selected ? 'border-brand-600 text-brand-400' : ''}`}
          >
            {selected ? '✓ Selected' : 'Compare'}
          </button>
        )}
      </div>
    </div>
  )
}

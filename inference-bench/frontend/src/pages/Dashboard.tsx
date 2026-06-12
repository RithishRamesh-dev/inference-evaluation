import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { EvaluationRun } from '../types'
import RunCard from '../components/RunCard'

export default function Dashboard() {
  const [runs, setRuns] = useState<EvaluationRun[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.evaluations.list({ limit: 20 })
      .then(setRuns)
      .finally(() => setLoading(false))

    // Poll for status updates if any run is running
    const interval = setInterval(() => {
      api.evaluations.list({ limit: 20 }).then(setRuns)
    }, 5000)
    return () => clearInterval(interval)
  }, [])

  const completed = runs.filter(r => r.status === 'completed')
  const running   = runs.filter(r => r.status === 'running')

  // Best scores per benchmark across all completed runs
  const scoreMap: Record<string, { name: string; score: number; runId: number }> = {}
  for (const run of completed) {
    for (const rb of run.run_benchmarks) {
      const key = rb.suite_name ?? String(rb.benchmark_suite_id)
      const score = rb.primary_score ?? 0
      if (!scoreMap[key] || score > scoreMap[key].score) {
        scoreMap[key] = { name: rb.suite_display_name ?? key, score, runId: run.id }
      }
    }
  }
  const leaderboard = Object.entries(scoreMap).sort((a, b) => b[1].score - a[1].score).slice(0, 8)

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">Inference benchmarking & evaluation</p>
        </div>
        <Link to="/new" className="btn-primary">＋ New Evaluation</Link>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Total Runs', value: runs.length },
          { label: 'Completed', value: completed.length },
          { label: 'Running', value: running.length },
          { label: 'Avg Score', value: completed.length ? `${(completed.filter(r => r.overall_score != null).reduce((s, r) => s + (r.overall_score! * 100), 0) / (completed.filter(r => r.overall_score != null).length || 1)).toFixed(1)}%` : '—' },
        ].map(stat => (
          <div key={stat.label} className="card text-center">
            <p className="text-2xl font-bold text-gray-100">{stat.value}</p>
            <p className="text-xs text-gray-500 mt-1">{stat.label}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Recent runs */}
        <div className="col-span-2 space-y-3">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Recent Runs</h2>
          {loading && <p className="text-sm text-gray-600">Loading…</p>}
          {!loading && runs.length === 0 && (
            <div className="card text-center py-10">
              <p className="text-gray-500 text-sm">No evaluations yet.</p>
              <Link to="/new" className="btn-primary mt-4 inline-flex">Start your first evaluation →</Link>
            </div>
          )}
          {runs.slice(0, 8).map(run => (
            <RunCard key={run.id} run={run} />
          ))}
          {runs.length > 8 && (
            <Link to="/dashboard" className="text-xs text-brand-400 hover:underline">View all {runs.length} runs →</Link>
          )}
        </div>

        {/* Leaderboard */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Best Scores</h2>
          {leaderboard.length === 0 && (
            <p className="text-xs text-gray-600">No completed runs yet.</p>
          )}
          {leaderboard.map(([key, { name, score, runId }]) => (
            <Link
              key={key}
              to={`/results/${runId}`}
              className="block card hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-300 font-medium truncate">{name}</span>
                <span className="text-sm font-bold text-green-400 ml-2 shrink-0">
                  {(score * 100).toFixed(1)}%
                </span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

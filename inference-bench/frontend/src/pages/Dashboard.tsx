import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { EvaluationRun, RegressionAlert, SystemInfo } from '../types'
import RunCard from '../components/RunCard'

export default function Dashboard() {
  const [runs, setRuns] = useState<EvaluationRun[]>([])
  const [alerts, setAlerts] = useState<RegressionAlert[]>([])
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null)
  const [loading, setLoading] = useState(true)

  const loadData = () => {
    api.evaluations.list({ limit: 20 }).then(setRuns).finally(() => setLoading(false))
    api.regressionAlerts.list(false).then(setAlerts).catch(() => {})
    api.system.info().then(setSysInfo).catch(() => {})
  }

  useEffect(() => {
    loadData()
    const interval = setInterval(() => {
      api.evaluations.list({ limit: 20 }).then(setRuns)
    }, 5000)
    return () => clearInterval(interval)
  }, [])

  const completed = runs.filter(r => r.status === 'completed')
  const running   = runs.filter(r => r.status === 'running')

  // Aggregate stats
  const totalSamples = completed.reduce((acc, r) =>
    acc + r.run_benchmarks.reduce((a, rb) => a + (rb.samples_scored ?? 0), 0), 0)
  const totalBenchmarksExecuted = completed.reduce((acc, r) => acc + r.passed_benchmarks, 0)

  // Best scores per benchmark across all completed runs
  const scoreMap: Record<string, { name: string; score: number; runId: string; modelName: string | null; date: string | null }> = {}
  for (const run of completed) {
    for (const rb of run.run_benchmarks) {
      if (rb.primary_score == null) continue
      const key = rb.suite_name ?? String(rb.benchmark_suite_id)
      if (!scoreMap[key] || rb.primary_score > scoreMap[key].score) {
        scoreMap[key] = {
          name: rb.suite_display_name ?? key,
          score: rb.primary_score,
          runId: run.id,
          modelName: run.model_name,
          date: run.completed_at,
        }
      }
    }
  }
  const leaderboard = Object.entries(scoreMap).sort((a, b) => b[1].score - a[1].score).slice(0, 10)

  const handleAcknowledge = async (id: string) => {
    await api.regressionAlerts.acknowledge(id)
    setAlerts(prev => prev.filter(a => a.id !== id))
  }

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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Total Runs', value: runs.length },
          { label: 'Benchmarks Executed', value: totalBenchmarksExecuted },
          { label: 'Samples Evaluated', value: totalSamples.toLocaleString() },
          {
            label: 'Avg Score',
            value: completed.length
              ? `${(completed.filter(r => r.overall_score != null).reduce((s, r) => s + (r.overall_score! * 100), 0) / (completed.filter(r => r.overall_score != null).length || 1)).toFixed(1)}%`
              : '—'
          },
        ].map(stat => (
          <div key={stat.label} className="card text-center">
            <p className="text-2xl font-bold text-gray-100">{stat.value}</p>
            <p className="text-xs text-gray-500 mt-1">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* System info footer strip */}
      {sysInfo && (
        <div className="flex flex-wrap gap-4 text-xs text-gray-600 bg-gray-800/30 rounded-lg px-4 py-2">
          <span>🐍 Python {sysInfo.python_version}</span>
          <span>🗄 {sysInfo.database}</span>
          <span>📊 {sysInfo.benchmarks_seeded} benchmarks</span>
          <span>🤖 {sysInfo.total_models} models</span>
          <span>⚙ EvalScope: {sysInfo.evalscope_available ? '✓ installed' : '✗ not installed (mock mode)'}</span>
        </div>
      )}

      {/* Regression alerts */}
      {alerts.length > 0 && (
        <div className="card border-red-800/40 bg-red-950/10">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-red-400 text-sm font-semibold">⚠ Regression Alerts</span>
            <span className="text-xs text-red-600">({alerts.length} unacknowledged)</span>
          </div>
          <div className="space-y-2">
            {alerts.slice(0, 5).map(a => (
              <div key={a.id} className="flex items-center gap-3 text-xs">
                <span className="text-red-400 font-semibold shrink-0">
                  {(a.delta * 100).toFixed(1)}%
                </span>
                <span className="text-gray-400 flex-1">
                  <Link to={`/results/${a.run_id}`} className="hover:underline text-gray-300">
                    {a.benchmark_name || a.benchmark_suite_id}
                  </Link>
                  {' '}dropped from {(a.prev_score * 100).toFixed(1)}% → {(a.curr_score * 100).toFixed(1)}%
                </span>
                <button
                  className="text-gray-600 hover:text-gray-400 shrink-0"
                  onClick={() => handleAcknowledge(a.id)}
                >
                  Dismiss
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

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
          {running.length > 0 && (
            <div className="text-xs text-brand-400 flex items-center gap-1.5">
              <span className="animate-pulse inline-block w-2 h-2 rounded-full bg-brand-400" />
              {running.length} run{running.length > 1 ? 's' : ''} in progress
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
          <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">Best Scores (All Time)</h2>
          {leaderboard.length === 0 && (
            <p className="text-xs text-gray-600">No completed runs yet.</p>
          )}
          {leaderboard.map(([key, { name, score, runId, modelName, date }]) => (
            <Link
              key={key}
              to={`/results/${runId}`}
              className="block card hover:border-gray-700 transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-300 font-medium truncate">{name}</span>
                <span className={`text-sm font-bold ml-2 shrink-0 ${score >= 0.9 ? 'text-green-400' : score >= 0.7 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {(score * 100).toFixed(1)}%
                </span>
              </div>
              {modelName && (
                <div className="text-xs text-gray-600 mt-0.5 truncate">{modelName}</div>
              )}
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

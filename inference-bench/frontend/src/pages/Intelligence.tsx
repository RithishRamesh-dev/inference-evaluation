import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Model, EvaluationRun } from '../types'

export default function Intelligence() {
  const [models, setModels] = useState<Model[]>([])
  const [runs, setRuns] = useState<EvaluationRun[]>([])
  const [latencies, setLatencies] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.models.list(),
      api.evaluations.list({ limit: 50 }),
    ]).then(([m, r]) => {
      setModels(m)
      setRuns(r.filter(r => r.status === 'completed'))
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (models.length === 0) return
    models.forEach(m => {
      api.models.test(m.id).then(res => {
        setLatencies(prev => ({ ...prev, [m.id]: res.latency_ms }))
      }).catch(() => {
        setLatencies(prev => ({ ...prev, [m.id]: null }))
      })
    })
  }, [models])

  const modelScores: Record<string, { score: number; runId: string }> = {}
  for (const run of runs) {
    if (run.overall_score == null) continue
    if (!modelScores[run.model_id] || run.overall_score > modelScores[run.model_id].score) {
      modelScores[run.model_id] = { score: run.overall_score, runId: run.id }
    }
  }

  const benchmarkNames: Record<string, string> = {}
  const matrixData: Record<string, Record<string, number>> = {}
  for (const run of runs) {
    for (const rb of run.run_benchmarks) {
      if (rb.primary_score == null) continue
      const bKey = rb.suite_name ?? rb.benchmark_suite_id
      benchmarkNames[bKey] = rb.suite_display_name ?? bKey
      if (!matrixData[bKey]) matrixData[bKey] = {}
      if (!matrixData[bKey][run.model_id] || rb.primary_score > matrixData[bKey][run.model_id]) {
        matrixData[bKey][run.model_id] = rb.primary_score
      }
    }
  }
  const topBenchmarks = Object.keys(matrixData).slice(0, 8)

  const onlineCount = models.filter(m => latencies[m.id] != null && latencies[m.id]! < 5000).length
  const latencyValues = Object.values(latencies).filter((v): v is number => v != null)
  const avgLatency = latencyValues.length ? Math.round(latencyValues.reduce((a, b) => a + b, 0) / latencyValues.length) : null

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Endpoint Intelligence</h1>
          <p className="text-sm text-do-grey-400 mt-0.5">Live status, performance, and quality scores across all models</p>
        </div>
        <Link to="/models" className="btn-secondary text-sm">Manage Models</Link>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Total Models', value: models.length },
          { label: 'Online Now', value: loading ? '…' : onlineCount },
          { label: 'Avg Latency', value: avgLatency != null ? `${avgLatency}ms` : '…' },
          { label: 'Evals Completed', value: runs.length },
        ].map(s => (
          <div key={s.label} className="card text-center">
            <p className="text-2xl font-bold text-gray-800">{s.value}</p>
            <p className="text-xs text-do-grey-400 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-do-grey-400">Loading models…</p>
      ) : models.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-3xl mb-3">◈</p>
          <p className="font-semibold text-gray-700">No models yet</p>
          <p className="text-sm text-do-grey-400 mt-1">Add models to see intelligence data</p>
          <Link to="/models" className="btn-primary mt-4 inline-flex">Add Model</Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {models.map(m => {
            const lat = latencies[m.id]
            const isOnline = lat != null && lat < 5000
            const isChecking = !(m.id in latencies)
            const bestScore = modelScores[m.id]
            return (
              <div key={m.id} className="card hover:border-do-blue/40 transition-colors">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-800 truncate">{m.name}</p>
                    <p className="text-xs text-do-grey-400">{m.provider}</p>
                  </div>
                  <span className={`ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                    isChecking ? 'bg-gray-100 text-gray-500' :
                    isOnline ? 'bg-green-50 text-green-700 border border-green-200' :
                    'bg-red-50 text-red-700 border border-red-200'
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${isChecking ? 'bg-gray-400 animate-pulse' : isOnline ? 'bg-green-500' : 'bg-red-500'}`} />
                    {isChecking ? 'Checking…' : isOnline ? 'Online' : 'Offline'}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <p className="text-do-grey-400">Latency</p>
                    <p className="font-semibold text-gray-700 mt-0.5">
                      {isChecking ? '—' : lat != null ? `${lat.toFixed(0)}ms` : 'Error'}
                    </p>
                  </div>
                  <div>
                    <p className="text-do-grey-400">Best Score</p>
                    <p className={`font-semibold mt-0.5 ${
                      bestScore == null ? 'text-gray-400' :
                      bestScore.score >= 0.9 ? 'text-green-600' :
                      bestScore.score >= 0.7 ? 'text-yellow-600' : 'text-red-600'
                    }`}>
                      {bestScore != null ? `${(bestScore.score * 100).toFixed(1)}%` : '—'}
                    </p>
                  </div>
                  <div>
                    <p className="text-do-grey-400">Context</p>
                    <p className="font-semibold text-gray-700 mt-0.5">{m.context_length ? `${(m.context_length / 1000).toFixed(0)}K` : '—'}</p>
                  </div>
                  <div>
                    <p className="text-do-grey-400">Caps</p>
                    <p className="font-semibold text-gray-700 mt-0.5">
                      {[m.supports_vision && 'Vision', m.supports_tool_calling && 'Tools', m.supports_reasoning && 'Reason'].filter(Boolean).join(' · ') || '—'}
                    </p>
                  </div>
                </div>

                <div className="mt-3 pt-3 border-t border-do-grey-200 flex gap-2">
                  <Link to={`/validate/${m.id}`} className="btn-secondary text-xs py-1 px-2 flex-1 justify-center">Validate</Link>
                  <Link to="/new" className="btn-primary text-xs py-1 px-2 flex-1 justify-center">Evaluate</Link>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {topBenchmarks.length > 0 && models.length > 0 && (
        <div className="card overflow-hidden p-0">
          <div className="px-5 py-4 border-b border-do-grey-200">
            <h2 className="text-sm font-semibold text-gray-700">Benchmark Comparison Matrix</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-do-grey-100">
                  <th className="text-left px-4 py-2 text-do-grey-700 font-medium min-w-[140px]">Benchmark</th>
                  {models.map(m => (
                    <th key={m.id} className="text-center px-3 py-2 text-do-grey-700 font-medium min-w-[80px] truncate max-w-[100px]">
                      {m.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-do-grey-200">
                {topBenchmarks.map(bKey => (
                  <tr key={bKey} className="hover:bg-do-grey-100/50">
                    <td className="px-4 py-2 text-gray-700 font-medium">{benchmarkNames[bKey]}</td>
                    {models.map(m => {
                      const score = matrixData[bKey]?.[m.id]
                      return (
                        <td key={m.id} className="text-center px-3 py-2">
                          {score != null ? (
                            <span className={`font-semibold ${
                              score >= 0.9 ? 'text-green-600' :
                              score >= 0.7 ? 'text-yellow-600' : 'text-red-600'
                            }`}>
                              {(score * 100).toFixed(0)}%
                            </span>
                          ) : (
                            <span className="text-do-grey-400">—</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

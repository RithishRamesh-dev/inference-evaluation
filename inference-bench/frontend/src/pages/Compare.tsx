import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { api } from '../api'
import type { EvaluationRun } from '../types'
import RadarChart from '../components/RadarChart'

const COLORS = ['#0ea5e9', '#10b981', '#f59e0b', '#ef4444']

export default function Compare() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [allRuns, setAllRuns] = useState<EvaluationRun[]>([])
  const [compareRuns, setCompareRuns] = useState<EvaluationRun[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    api.evaluations.list({ status: 'completed', limit: 50 }).then(setAllRuns)
  }, [])

  useEffect(() => {
    const idsParam = searchParams.get('ids')
    if (idsParam) {
      const ids = idsParam.split(',').map(s => s.trim()).filter(Boolean)
      ids.forEach(id => setSelectedIds(prev => new Set([...prev, id])))
    }
  }, [])

  useEffect(() => {
    if (selectedIds.size === 0) { setCompareRuns([]); return }
    api.evaluations.compare([...selectedIds]).then(setCompareRuns)
  }, [selectedIds])

  const toggleRun = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) } else if (next.size < 4) { next.add(id) }
      return next
    })
  }

  // Build grouped bar chart data: [{benchmark, run1: score, run2: score, ...}]
  const allBenchmarks = Array.from(new Set(
    compareRuns.flatMap(r => r.run_benchmarks.map(rb => rb.suite_name ?? String(rb.benchmark_suite_id)))
  ))

  const barData = allBenchmarks.map(bname => {
    const point: Record<string, string | number> = { benchmark: bname }
    compareRuns.forEach((run, i) => {
      const rb = run.run_benchmarks.find(rb => rb.suite_name === bname)
      point[`run${i}`] = rb?.primary_score != null ? parseFloat((rb.primary_score * 100).toFixed(1)) : 0
    })
    return point
  })

  // Radar series per run
  const radarSeries = compareRuns.map((run, i) => {
    const data: Record<string, number> = {}
    for (const rb of run.run_benchmarks) {
      if (rb.primary_score != null && rb.suite_category) {
        data[rb.suite_category] = Math.max(data[rb.suite_category] ?? 0, rb.primary_score)
      }
    }
    return { name: run.display_name || `Run #${run.id}`, color: COLORS[i], data }
  })

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-100">Compare Runs</h1>
        <p className="text-sm text-gray-500 mt-0.5">Select up to 4 completed runs</p>
      </div>

      {/* Run selector */}
      <div className="card">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
          Select Runs ({selectedIds.size}/4)
        </h3>
        <div className="space-y-1 max-h-56 overflow-y-auto">
          {allRuns.map((run, i) => (
            <label key={run.id} className="flex items-center gap-3 px-2 py-1.5 rounded hover:bg-gray-800 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedIds.has(run.id)}
                onChange={() => toggleRun(run.id)}
                disabled={!selectedIds.has(run.id) && selectedIds.size >= 4}
              />
              <span className="text-xs font-mono text-gray-600 w-6">{i + 1}</span>
              <span className="text-sm text-gray-300 flex-1 truncate">
                {run.display_name || `Run #${run.id}`}
              </span>
              <span className="text-xs text-gray-500">{run.model_name}</span>
              <span className="text-xs font-bold text-gray-400">
                {run.overall_score != null ? `${(run.overall_score * 100).toFixed(1)}%` : '—'}
              </span>
            </label>
          ))}
          {allRuns.length === 0 && <p className="text-xs text-gray-600 text-center py-4">No completed runs yet.</p>}
        </div>
      </div>

      {compareRuns.length < 2 && (
        <p className="text-sm text-gray-500 text-center py-4">Select at least 2 runs to compare.</p>
      )}

      {compareRuns.length >= 2 && (
        <>
          {/* Score delta table */}
          <div className="card overflow-x-auto">
            <h3 className="text-sm font-semibold text-gray-300 mb-3">Score Comparison</h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-1.5 pr-4">Benchmark</th>
                  {compareRuns.map((run, i) => (
                    <th key={run.id} className="text-right pr-4" style={{ color: COLORS[i] }}>
                      {run.display_name || `Run #${run.id}`}
                    </th>
                  ))}
                  {compareRuns.length === 2 && <th className="text-right">Δ</th>}
                </tr>
              </thead>
              <tbody>
                {allBenchmarks.map(bname => {
                  const scores = compareRuns.map(run => {
                    const rb = run.run_benchmarks.find(rb => rb.suite_name === bname)
                    return rb?.primary_score ?? null
                  })
                  const delta = scores.length === 2 && scores[0] != null && scores[1] != null
                    ? scores[0] - scores[1] : null
                  return (
                    <tr key={bname} className="border-b border-gray-800/50">
                      <td className="py-2 pr-4 text-gray-300">{bname}</td>
                      {scores.map((s, i) => (
                        <td key={i} className="text-right pr-4 font-medium" style={{ color: COLORS[i] }}>
                          {s != null ? `${(s * 100).toFixed(1)}%` : '—'}
                        </td>
                      ))}
                      {delta != null && (
                        <td className={`text-right font-semibold ${delta > 0 ? 'text-green-400' : delta < 0 ? 'text-red-400' : 'text-gray-500'}`}>
                          {delta > 0 ? '+' : ''}{(delta * 100).toFixed(1)}%
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Grouped bar chart */}
          {barData.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Benchmark Scores</h3>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={barData} margin={{ bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="benchmark" tick={{ fill: '#9CA3AF', fontSize: 10 }} angle={-30} textAnchor="end" />
                  <YAxis domain={[0, 100]} tick={{ fill: '#6B7280', fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                    formatter={(v: number) => `${v}%`}
                  />
                  <Legend />
                  {compareRuns.map((run, i) => (
                    <Bar key={run.id} dataKey={`run${i}`} name={run.display_name || `Run #${run.id}`} fill={COLORS[i]} radius={[3, 3, 0, 0]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Radar overlay */}
          {radarSeries.length >= 2 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">Category Overlay</h3>
              <RadarChart series={radarSeries} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

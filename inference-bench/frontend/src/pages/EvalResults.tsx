import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api'
import type { EvaluationRun, RunBenchmark } from '../types'
import ScoreCard from '../components/ScoreCard'
import RadarChart from '../components/RadarChart'
import SampleExplorer from '../components/SampleExplorer'
import NotesPanel from '../components/NotesPanel'
import ProgressBar from '../components/ProgressBar'

type Panel = 'overview' | 'samples' | 'notes'

export default function EvalResults() {
  const { runId } = useParams<{ runId: string }>()
  const [run, setRun] = useState<EvaluationRun | null>(null)
  const [panel, setPanel] = useState<Panel>('overview')
  const [selectedRb, setSelectedRb] = useState<RunBenchmark | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!runId) return
    api.evaluations.results(runId)
      .then(r => { setRun(r); setSelectedRb(r.run_benchmarks[0] ?? null) })
      .finally(() => setLoading(false))
  }, [runId])

  if (loading) return <div className="p-6 text-gray-500">Loading…</div>
  if (!run) return <div className="p-6 text-red-400">Run not found.</div>

  const overall = run.overall_score != null ? `${(run.overall_score * 100).toFixed(1)}%` : '—'
  const wallTime = run.wall_time_seconds != null
    ? `${Math.floor(run.wall_time_seconds / 60)}m ${run.wall_time_seconds % 60}s`
    : '—'

  // Build radar data — group by category
  const radarData: Record<string, number> = {}
  for (const rb of run.run_benchmarks) {
    if (rb.primary_score != null && rb.suite_category) {
      const prev = radarData[rb.suite_category] ?? 0
      radarData[rb.suite_category] = Math.max(prev, rb.primary_score)
    }
  }
  const radarSeries = Object.keys(radarData).length > 0
    ? [{ name: run.display_name || `Run #${run.id}`, color: '#0ea5e9', data: radarData }]
    : []

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">{run.display_name || `Run #${run.id}`}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {run.model_provider} · {run.model_name}
            {run.thinking_mode && ` · thinking ${run.thinking_mode}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to={`/compare?ids=${run.id}`} className="btn-secondary text-xs">Compare</Link>
          <Link to="/new" className="btn-primary text-xs">New Eval</Link>
        </div>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="card text-center">
          <p className="text-3xl font-bold text-gray-100">{overall}</p>
          <p className="text-xs text-gray-500 mt-1">Overall Score</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-100">{run.passed_benchmarks}/{run.total_benchmarks}</p>
          <p className="text-xs text-gray-500 mt-1">Benchmarks Passed</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-100">{wallTime}</p>
          <p className="text-xs text-gray-500 mt-1">Wall Time</p>
        </div>
        <div className="card text-center">
          <p className="text-2xl font-bold text-gray-100">
            {run.run_benchmarks.reduce((s, rb) => s + (rb.samples_scored ?? 0), 0).toLocaleString()}
          </p>
          <p className="text-xs text-gray-500 mt-1">Total Samples</p>
        </div>
      </div>

      {/* Score cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {run.run_benchmarks.map(rb => (
          <ScoreCard
            key={rb.id}
            title={rb.suite_display_name ?? rb.suite_name ?? `#${rb.benchmark_suite_id}`}
            score={rb.primary_score}
            sampleCount={rb.samples_scored}
            status={rb.status}
          />
        ))}
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Radar chart */}
        {radarSeries.length > 0 && (
          <div className="card lg:col-span-1">
            <h3 className="text-sm font-semibold text-gray-300 mb-3">Category Scores</h3>
            <RadarChart series={radarSeries} />
          </div>
        )}

        {/* Performance table */}
        <div className={`card ${radarSeries.length > 0 ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Performance Breakdown</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-1.5 pr-4">Benchmark</th>
                  <th className="text-right pr-4">Score</th>
                  <th className="text-right pr-4">Samples</th>
                  <th className="text-right pr-4">Avg Latency</th>
                  <th className="text-right pr-4">Avg In Tok</th>
                  <th className="text-right">Avg Out Tok</th>
                </tr>
              </thead>
              <tbody>
                {run.run_benchmarks.map(rb => (
                  <tr key={rb.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 pr-4 text-gray-300 font-medium">{rb.suite_display_name ?? rb.suite_name}</td>
                    <td className="text-right pr-4">
                      <span className={rb.status === 'completed' ? 'text-green-400 font-semibold' : 'text-gray-500'}>
                        {rb.primary_score != null ? `${(rb.primary_score * 100).toFixed(1)}%` : rb.status}
                      </span>
                    </td>
                    <td className="text-right pr-4 text-gray-400">{rb.samples_scored ?? '—'}</td>
                    <td className="text-right pr-4 text-gray-400">{rb.avg_latency_s?.toFixed(2) ?? '—'}s</td>
                    <td className="text-right pr-4 text-gray-400">{rb.avg_input_tokens?.toFixed(0) ?? '—'}</td>
                    <td className="text-right text-gray-400">{rb.avg_output_tokens?.toFixed(0) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Panel tabs */}
      <div className="border-b border-gray-800 flex gap-4">
        {(['overview', 'samples', 'notes'] as Panel[]).map(p => (
          <button key={p} onClick={() => setPanel(p)}
            className={`pb-2 text-sm font-medium border-b-2 transition-colors -mb-px capitalize ${
              panel === p ? 'border-brand-500 text-brand-400' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
            {p}
          </button>
        ))}
      </div>

      {/* Sample explorer */}
      {panel === 'samples' && (
        <div className="space-y-4">
          {/* Benchmark selector */}
          <div className="flex gap-2 flex-wrap">
            {run.run_benchmarks.map(rb => (
              <button key={rb.id} onClick={() => setSelectedRb(rb)}
                className={`px-3 py-1.5 rounded-lg text-xs border transition-colors
                  ${selectedRb?.id === rb.id ? 'bg-brand-600 border-brand-600 text-white' : 'bg-gray-800 border-gray-700 text-gray-400'}`}>
                {rb.suite_display_name ?? rb.suite_name}
              </button>
            ))}
          </div>
          {selectedRb && (
            <SampleExplorer
              runId={run.id}
              rbId={selectedRb.id}
              benchmarkName={selectedRb.suite_display_name ?? selectedRb.suite_name ?? undefined}
            />
          )}
        </div>
      )}

      {panel === 'notes' && <NotesPanel runId={run.id} />}
    </div>
  )
}

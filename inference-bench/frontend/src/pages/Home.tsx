import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { EvaluationRun, SystemInfo } from '../types'

const FEATURES = [
  { to: '/new',          icon: '＋', title: 'New Evaluation',  desc: 'Run benchmarks against any OpenAI-compatible model with 53+ test suites.' },
  { to: '/models',       icon: '◈',  title: 'Model Catalog',   desc: 'Manage models with connection testing, stress tests, and validation.' },
  { to: '/intelligence', icon: '◉',  title: 'Intelligence',    desc: 'Live latency status and cross-model benchmark comparison matrix.' },
  { to: '/ab-tests',     icon: '⚖',  title: 'A/B Tests',       desc: 'Compare multiple models head-to-head on identical benchmark sets.' },
  { to: '/probe',        icon: '⊙',  title: 'Probe Endpoint',  desc: 'Test any endpoint without adding it to the catalog first.' },
  { to: '/playground',   icon: '▷',  title: 'Playground',      desc: 'Interactive prompt testing with batch runs and saved templates.' },
  { to: '/monitor',      icon: '◎',  title: 'Live Monitor',    desc: 'Continuous health monitoring with uptime tracking and alerts.' },
  { to: '/cost',         icon: '◉',  title: 'Cost Analytics',  desc: 'Track token costs and spending across all evaluations by model.' },
]

export default function Home() {
  const [runs, setRuns] = useState<EvaluationRun[]>([])
  const [sysInfo, setSysInfo] = useState<SystemInfo | null>(null)

  useEffect(() => {
    api.evaluations.list({ limit: 3 }).then(setRuns).catch(() => {})
    api.system.info().then(setSysInfo).catch(() => {})
  }, [])

  const completed = runs.filter(r => r.status === 'completed')
  const avgScore = completed.length
    ? completed.filter(r => r.overall_score != null).reduce((s, r) => s + r.overall_score!, 0) /
      (completed.filter(r => r.overall_score != null).length || 1)
    : null

  const STATUS_BADGE: Record<string, string> = {
    completed: 'badge-green',
    running: 'badge-blue',
    failed: 'badge-red',
    queued: 'badge-gray',
    cancelled: 'badge-gray',
  }

  return (
    <div className="p-6 space-y-8 max-w-5xl mx-auto">
      {/* Hero */}
      <div className="card text-center py-10" style={{ background: 'linear-gradient(135deg, #1B2A4A 0%, #243556 100%)' }}>
        <div className="text-4xl mb-3">≋</div>
        <h1 className="text-2xl font-bold text-white mb-2">Welcome to Crest</h1>
        <p className="text-sm mb-6" style={{ color: 'rgba(255,255,255,0.65)' }}>
          DigitalOcean's inference benchmarking & evaluation platform
        </p>
        <div className="flex justify-center gap-3">
          <Link to="/new" className="btn-primary">Start Evaluation</Link>
          <Link to="/dashboard" className="btn" style={{ background: 'rgba(255,255,255,0.12)', color: 'white', border: '1px solid rgba(255,255,255,0.2)' }}>View History</Link>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Models', value: sysInfo?.total_models ?? '—' },
          { label: 'Evaluations', value: sysInfo?.total_runs ?? '—' },
          { label: 'Benchmarks', value: sysInfo?.benchmarks_seeded ?? '—' },
          { label: 'Avg Score', value: avgScore != null ? `${(avgScore * 100).toFixed(1)}%` : '—' },
        ].map(s => (
          <div key={s.label} className="card text-center">
            <p className="text-2xl font-bold text-gray-800">{s.value}</p>
            <p className="text-xs text-gray-600 mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Features */}
      <div>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Platform Features</h2>
        <div className="grid grid-cols-2 gap-3">
          {FEATURES.map(f => (
            <Link key={f.to} to={f.to} className="card hover:border-do-blue/50 hover:shadow-md transition-all group">
              <div className="flex items-start gap-3">
                <span className="text-xl text-do-blue mt-0.5">{f.icon}</span>
                <div>
                  <p className="text-sm font-semibold text-gray-800 group-hover:text-do-blue transition-colors">{f.title}</p>
                  <p className="text-xs text-gray-600 mt-0.5 leading-relaxed">{f.desc}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Recent runs */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Recent Evaluations</h2>
          <Link to="/dashboard" className="text-xs text-do-blue hover:underline">View all →</Link>
        </div>
        {runs.length === 0 ? (
          <div className="card text-center py-8">
            <p className="text-gray-600 text-sm">No evaluations yet.</p>
            <Link to="/new" className="btn-primary mt-3 inline-flex">Run your first evaluation →</Link>
          </div>
        ) : (
          <div className="space-y-2">
            {runs.map(r => (
              <Link key={r.id} to={`/results/${r.id}`} className="card flex items-center gap-4 py-3 hover:border-do-blue/40 transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{r.display_name ?? r.model_name ?? 'Evaluation'}</p>
                  <p className="text-xs text-gray-600 mt-0.5">{r.model_name} · {r.total_benchmarks} benchmarks</p>
                </div>
                <span className={`badge ${STATUS_BADGE[r.status] ?? 'badge-gray'}`}>{r.status}</span>
                {r.overall_score != null && (
                  <span className={`text-sm font-bold ${r.overall_score >= 0.9 ? 'text-green-600' : r.overall_score >= 0.7 ? 'text-yellow-600' : 'text-red-600'}`}>
                    {(r.overall_score * 100).toFixed(1)}%
                  </span>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

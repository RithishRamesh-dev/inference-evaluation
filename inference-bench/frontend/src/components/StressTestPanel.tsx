import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { api } from '../api'
import type { StressTestRun, StressLevelResult } from '../types'

const DEFAULT_CONCURRENCY = [1, 2, 4, 8]

interface Props {
  modelId: string
}

export default function StressTestPanel({ modelId }: Props) {
  const [concurrencyLevels, setConcurrencyLevels] = useState<number[]>(DEFAULT_CONCURRENCY)
  const [requestsPerLevel, setRequestsPerLevel] = useState(5)
  const [outputTokens, setOutputTokens] = useState(100)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<StressTestRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)

  const toggleLevel = (n: number) => {
    setConcurrencyLevels(prev =>
      prev.includes(n) ? prev.filter(x => x !== n) : [...prev, n].sort((a, b) => a - b)
    )
  }

  const handleRun = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    setProgress('Starting stress test…')
    try {
      const { test_id } = await api.stressTest.create(modelId, {
        concurrency_levels: concurrencyLevels,
        requests_per_level: requestsPerLevel,
        output_tokens: outputTokens,
      })
      setProgress('Running (may take several minutes)…')
      const res = await api.stressTest.get(modelId, test_id)
      setResult(res)
      setProgress(null)
    } catch (e) {
      setError(String(e))
      setProgress(null)
    } finally {
      setRunning(false)
    }
  }

  const chartData = (result?.results ?? [])
    .filter((r): r is StressLevelResult => 'p50_latency_ms' in r)
    .map(r => ({
      concurrency: r.concurrency,
      'P50 (ms)': r.p50_latency_ms,
      'P95 (ms)': r.p95_latency_ms,
      'P99 (ms)': r.p99_latency_ms,
    }))

  const tpsData = (result?.results ?? [])
    .filter((r): r is StressLevelResult => 'throughput_tokens_per_second' in r)
    .map(r => ({
      concurrency: r.concurrency,
      'tok/s': r.throughput_tokens_per_second,
      'req/s': r.throughput_requests_per_second,
    }))

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-gray-200">Performance Stress Test</h3>
        <p className="text-xs text-gray-500 mt-0.5">Measure latency and throughput at multiple concurrency levels</p>
      </div>

      {/* Config */}
      <div className="bg-gray-800/40 rounded-lg p-4 space-y-4">
        <div>
          <p className="text-xs text-gray-400 mb-2">Concurrency Levels</p>
          <div className="flex flex-wrap gap-2">
            {[1, 2, 4, 8, 16, 32].map(n => (
              <button
                key={n}
                onClick={() => toggleLevel(n)}
                className={`px-3 py-1 rounded text-xs font-mono border transition-colors ${
                  concurrencyLevels.includes(n)
                    ? 'bg-brand-600 border-brand-500 text-white'
                    : 'bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-500'
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Requests per level</label>
            <input
              type="number"
              className="input"
              value={requestsPerLevel}
              min={1} max={50}
              onChange={e => setRequestsPerLevel(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="label">Max output tokens</label>
            <input
              type="number"
              className="input"
              value={outputTokens}
              min={10} max={1000}
              onChange={e => setOutputTokens(Number(e.target.value))}
            />
          </div>
        </div>
      </div>

      <button
        className="btn-primary w-full"
        onClick={handleRun}
        disabled={running || concurrencyLevels.length === 0}
      >
        {running ? (
          <span className="flex items-center justify-center gap-2">
            <span className="animate-spin inline-block w-3 h-3 border-2 border-white/20 border-t-white rounded-full" />
            {progress || 'Running…'}
          </span>
        ) : '▶ Run Stress Test'}
      </button>

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2">{error}</div>
      )}

      {result && result.results.length > 0 && (
        <>
          {/* Latency chart */}
          {chartData.length > 0 && (
            <div className="card">
              <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Latency vs Concurrency
              </h4>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="concurrency" label={{ value: 'Concurrency', position: 'insideBottom', offset: -5, fill: '#6B7280', fontSize: 10 }} tick={{ fill: '#9CA3AF', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#6B7280', fontSize: 10 }} unit="ms" />
                  <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }} formatter={(v: number) => `${v.toFixed(0)}ms`} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="P50 (ms)" stroke="#0ea5e9" strokeWidth={2} dot />
                  <Line type="monotone" dataKey="P95 (ms)" stroke="#f59e0b" strokeWidth={2} dot />
                  <Line type="monotone" dataKey="P99 (ms)" stroke="#ef4444" strokeWidth={2} dot />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Throughput chart */}
          {tpsData.length > 0 && (
            <div className="card">
              <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                Throughput vs Concurrency
              </h4>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={tpsData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="concurrency" tick={{ fill: '#9CA3AF', fontSize: 10 }} />
                  <YAxis yAxisId="tps" tick={{ fill: '#6B7280', fontSize: 10 }} />
                  <YAxis yAxisId="rps" orientation="right" tick={{ fill: '#6B7280', fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line yAxisId="tps" type="monotone" dataKey="tok/s" stroke="#10b981" strokeWidth={2} dot />
                  <Line yAxisId="rps" type="monotone" dataKey="req/s" stroke="#8b5cf6" strokeWidth={2} dot />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Table */}
          <div className="card overflow-x-auto">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Results Table</h4>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-1.5 pr-3">Conc.</th>
                  <th className="text-right pr-3">Succeeded</th>
                  <th className="text-right pr-3">Failed</th>
                  <th className="text-right pr-3">P50</th>
                  <th className="text-right pr-3">P95</th>
                  <th className="text-right pr-3">P99</th>
                  <th className="text-right pr-3">tok/s</th>
                  <th className="text-right pr-3">req/s</th>
                  <th className="text-right">TTFT</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r, i) => {
                  if (!('p50_latency_ms' in r)) return null
                  const lr = r as StressLevelResult
                  const errRate = lr.error_rate * 100
                  return (
                    <tr key={i} className="border-b border-gray-800/50">
                      <td className="py-1.5 pr-3 font-mono font-bold text-gray-200">{lr.concurrency}</td>
                      <td className="text-right pr-3 text-green-400">{lr.requests_succeeded}</td>
                      <td className={`text-right pr-3 ${lr.requests_failed > 0 ? 'text-red-400' : 'text-gray-600'}`}>{lr.requests_failed}</td>
                      <td className="text-right pr-3 text-gray-300">{lr.p50_latency_ms.toFixed(0)}ms</td>
                      <td className="text-right pr-3 text-gray-400">{lr.p95_latency_ms.toFixed(0)}ms</td>
                      <td className="text-right pr-3 text-gray-500">{lr.p99_latency_ms.toFixed(0)}ms</td>
                      <td className="text-right pr-3 text-cyan-400">{lr.throughput_tokens_per_second.toFixed(1)}</td>
                      <td className="text-right pr-3 text-purple-400">{lr.throughput_requests_per_second.toFixed(2)}</td>
                      <td className="text-right text-gray-400">{lr.ttft_ms_avg ? `${lr.ttft_ms_avg.toFixed(0)}ms` : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

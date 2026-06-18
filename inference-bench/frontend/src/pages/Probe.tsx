import { useState } from 'react'
import { api } from '../api'
import type { ValidationCheckResult } from '../types'

const STATUS_COLOR: Record<string, string> = {
  pass: 'bg-green-900/40 text-green-400 border border-green-700/40',
  fail: 'bg-red-900/40 text-red-400 border border-red-700/40',
  warn: 'bg-yellow-900/40 text-yellow-400 border border-yellow-700/40',
  skip: 'bg-gray-800 text-gray-500 border border-gray-700/40',
}

const QUICK_CHECKS = ['connectivity', 'basic_completion', 'usage_object', 'streaming_basic', 'function_calling']

export default function Probe() {
  const [endpointUrl, setEndpointUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [modelId, setModelId] = useState('')
  const [mode, setMode] = useState<'all' | 'quick'>('quick')
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<ValidationCheckResult[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const handleRun = async () => {
    if (!endpointUrl || !apiKey || !modelId) return
    setRunning(true)
    setError(null)
    setResults(null)
    try {
      const checks = mode === 'quick' ? QUICK_CHECKS : undefined
      const res = await api.probe({ endpoint_url: endpointUrl, api_key: apiKey, model_id: modelId, checks })
      setResults(res as unknown as ValidationCheckResult[])
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning(false)
    }
  }

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const summary = results
    ? {
        passed: results.filter(r => r.status === 'pass').length,
        warned: results.filter(r => r.status === 'warn').length,
        failed: results.filter(r => r.status === 'fail').length,
        skipped: results.filter(r => r.status === 'skip').length,
      }
    : null

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Endpoint Probe</h1>
        <p className="text-sm text-gray-600 mt-0.5">
          Test any OpenAI-compatible endpoint without adding it to the catalog first
        </p>
      </div>

      {/* Config card */}
      <div className="card space-y-4">
        <div>
          <label className="label">Endpoint URL</label>
          <input
            className="input"
            placeholder="https://your-inference-endpoint/v1"
            value={endpointUrl}
            onChange={e => setEndpointUrl(e.target.value)}
          />
        </div>
        <div>
          <label className="label">API Key</label>
          <input
            className="input"
            type="password"
            placeholder="sk-..."
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
          />
        </div>
        <div>
          <label className="label">Model ID</label>
          <input
            className="input"
            placeholder="gpt-4o / moonshotai/Kimi-K2.6"
            value={modelId}
            onChange={e => setModelId(e.target.value)}
          />
        </div>

        {/* Mode selector */}
        <div>
          <p className="label mb-2">Check Mode</p>
          <div className="flex gap-2">
            {([['quick', 'Quick Probe (5 checks)'], ['all', 'Full Suite (35+ checks)']] as const).map(([m, lbl]) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-4 py-1.5 rounded text-sm border transition-colors ${
                  mode === m
                    ? 'bg-brand-600 border-brand-500 text-white'
                    : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'
                }`}
              >
                {lbl}
              </button>
            ))}
          </div>
          {mode === 'quick' && (
            <p className="text-xs text-gray-600 mt-1.5">
              Runs: {QUICK_CHECKS.join(', ')}
            </p>
          )}
        </div>

        <button
          className="btn-primary w-full"
          onClick={handleRun}
          disabled={running || !endpointUrl || !apiKey || !modelId}
        >
          {running ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin inline-block w-3 h-3 border-2 border-white/20 border-t-white rounded-full" />
              {mode === 'quick' ? 'Running 5 checks…' : 'Running full suite…'}
            </span>
          ) : `▶ Run ${mode === 'quick' ? 'Quick Probe' : 'Full Validation'}`}
        </button>
      </div>

      {error && (
        <div className="card border-red-800/50 text-red-400 text-sm">{error}</div>
      )}

      {/* Summary */}
      {summary && results && (
        <div className="card">
          <div className="flex items-center gap-4 mb-4">
            <div className={`text-2xl font-bold ${
              summary.failed === 0 ? 'text-green-400' :
              summary.failed <= 2 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {results.length - summary.skipped > 0
                ? Math.round((summary.passed / (results.length - summary.skipped)) * 100)
                : 0}%
            </div>
            <div className="text-xs space-y-0.5 flex-1">
              <div className="flex gap-3">
                <span className="text-green-600">{summary.passed} PASS</span>
                <span className="text-yellow-600">{summary.warned} WARN</span>
                <span className="text-red-600">{summary.failed} FAIL</span>
                <span className="text-gray-600">{summary.skipped} SKIP</span>
              </div>
              <div className="text-gray-600">{results.length} checks total</div>
            </div>
          </div>

          <div className="space-y-1">
            {results.map(check => (
              <div key={check.check_id} className="border border-gray-200 rounded overflow-hidden">
                <button
                  className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-50 text-left"
                  onClick={() => toggleExpand(check.check_id)}
                >
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded shrink-0 ${STATUS_COLOR[check.status] || STATUS_COLOR.fail}`}>
                    {check.status.toUpperCase()}
                  </span>
                  <span className="text-sm text-gray-700 flex-1">{check.name}</span>
                  <span className="text-xs text-gray-600 shrink-0">{check.latency_ms.toFixed(0)}ms</span>
                  <span className="text-gray-500 text-xs">{expanded.has(check.check_id) ? '▲' : '▼'}</span>
                </button>
                {expanded.has(check.check_id) && (
                  <div className="px-3 pb-3 space-y-2 border-t border-gray-200">
                    <p className="text-xs text-gray-600 pt-2">{check.message}</p>
                    <pre className="text-xs bg-gray-50 rounded p-2 overflow-x-auto text-gray-600 whitespace-pre-wrap">
                      {JSON.stringify(check.detail, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

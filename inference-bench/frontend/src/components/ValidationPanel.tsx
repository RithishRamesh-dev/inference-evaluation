import { useState } from 'react'
import { api } from '../api'
import type { ValidationRun, ValidationCheckResult } from '../types'

const STATUS_COLOR: Record<string, string> = {
  pass: 'bg-green-900/40 text-green-400 border border-green-700/40',
  fail: 'bg-red-900/40 text-red-400 border border-red-700/40',
  warn: 'bg-yellow-900/40 text-yellow-400 border border-yellow-700/40',
  skip: 'bg-gray-800 text-gray-500 border border-gray-700/40',
}

const CATEGORY_ORDER = [
  'connectivity', 'basic_completion', 'usage', 'streaming',
  'parameters', 'content_quality', 'advanced_features', 'performance',
  'headers_protocol', 'reasoning',
]

const CATEGORY_LABELS: Record<string, string> = {
  connectivity: 'Connectivity',
  basic_completion: 'Basic Completion',
  usage: 'Usage Accounting',
  streaming: 'Streaming',
  parameters: 'Parameters',
  content_quality: 'Content Quality',
  advanced_features: 'Advanced Features',
  performance: 'Performance',
  headers_protocol: 'Headers & Protocol',
  reasoning: 'Reasoning',
}

function CheckRow({ check }: { check: ValidationCheckResult }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="border-b border-gray-800/60 last:border-0">
      <button
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-800/40 text-left"
        onClick={() => setExpanded(x => !x)}
      >
        <span className={`text-xs font-semibold px-2 py-0.5 rounded shrink-0 ${STATUS_COLOR[check.status] || STATUS_COLOR.fail}`}>
          {check.status.toUpperCase()}
        </span>
        <span className="text-sm text-gray-200 flex-1">{check.name}</span>
        <span className="text-xs text-gray-500 shrink-0">{check.latency_ms.toFixed(0)}ms</span>
        <span className="text-gray-600 text-xs">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <p className="text-xs text-gray-400">{check.message}</p>
          <pre className="text-xs bg-gray-950 rounded p-2 overflow-x-auto text-gray-400 whitespace-pre-wrap">
            {JSON.stringify(check.detail, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function CategoryGroup({ category, checks }: { category: string; checks: ValidationCheckResult[] }) {
  const [collapsed, setCollapsed] = useState(false)
  const passed = checks.filter(c => c.status === 'pass').length
  const failed = checks.filter(c => c.status === 'fail').length
  const warned = checks.filter(c => c.status === 'warn').length

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-800/60 hover:bg-gray-800 text-left"
        onClick={() => setCollapsed(x => !x)}
      >
        <span className="text-sm font-semibold text-gray-200">
          {CATEGORY_LABELS[category] || category}
        </span>
        <div className="flex items-center gap-2 text-xs">
          {passed > 0 && <span className="text-green-400">{passed} pass</span>}
          {warned > 0 && <span className="text-yellow-400">{warned} warn</span>}
          {failed > 0 && <span className="text-red-400">{failed} fail</span>}
          <span className="text-gray-600 ml-1">{collapsed ? '▶' : '▼'}</span>
        </div>
      </button>
      {!collapsed && (
        <div>
          {checks.map(c => <CheckRow key={c.check_id} check={c} />)}
        </div>
      )}
    </div>
  )
}

interface Props {
  modelId: string
  onClose?: () => void
}

export default function ValidationPanel({ modelId, onClose }: Props) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ValidationRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleRun = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const r = await api.validation.run(modelId)
      setResult(r)
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning(false)
    }
  }

  // Group checks by category
  const grouped: Record<string, ValidationCheckResult[]> = {}
  if (result) {
    for (const c of result.checks) {
      if (!grouped[c.category]) grouped[c.category] = []
      grouped[c.category].push(c)
    }
  }

  const orderedCats = [
    ...CATEGORY_ORDER.filter(c => grouped[c]),
    ...Object.keys(grouped).filter(c => !CATEGORY_ORDER.includes(c)),
  ]

  const healthPct = result
    ? Math.round((result.passed / Math.max(result.total_checks - result.skipped, 1)) * 100)
    : null

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-200">Endpoint Validation</h3>
          <p className="text-xs text-gray-500 mt-0.5">Run 35+ compliance checks against this endpoint</p>
        </div>
        {onClose && (
          <button className="text-gray-600 hover:text-gray-400 text-sm" onClick={onClose}>✕</button>
        )}
      </div>

      {/* Summary bar if result exists */}
      {result && (
        <div className="bg-gray-800/60 rounded-lg p-3 flex items-center gap-4 flex-wrap">
          <div className={`text-2xl font-bold ${
            (healthPct ?? 0) >= 90 ? 'text-green-400' :
            (healthPct ?? 0) >= 70 ? 'text-yellow-400' : 'text-red-400'
          }`}>
            {healthPct}%
          </div>
          <div className="text-xs space-y-0.5 flex-1">
            <div className="flex gap-3">
              <span className="text-green-400">{result.passed} PASS</span>
              <span className="text-yellow-400">{result.warned} WARN</span>
              <span className="text-red-400">{result.failed} FAIL</span>
              <span className="text-gray-500">{result.skipped} SKIP</span>
            </div>
            <div className="text-gray-500">{result.total_checks} checks · {result.duration_ms ? `${(result.duration_ms / 1000).toFixed(1)}s` : ''}</div>
          </div>
          <a
            href={api.validation.curlUrl(modelId)}
            download="validate.sh"
            className="btn-secondary text-xs py-1"
          >
            ⬇ validate.sh
          </a>
          <a href={`/api/models/${modelId}/validate/python`} download="gauge_probe.py"
             className="btn-secondary text-xs py-1">
            🐍 Python Script
          </a>
          <a href={`/api/models/${modelId}/validate/github-actions`} download="gauge-probe.yml"
             className="btn-secondary text-xs py-1">
            ⚙ GitHub Actions
          </a>
        </div>
      )}

      {/* Run button */}
      <button
        className="btn-primary w-full"
        onClick={handleRun}
        disabled={running}
      >
        {running ? (
          <span className="flex items-center justify-center gap-2">
            <span className="animate-spin inline-block w-3 h-3 border-2 border-white/20 border-t-white rounded-full" />
            Running {result ? 'again…' : '35+ checks…'}
          </span>
        ) : result ? '↺ Re-run Validation' : '▶ Run Validation'}
      </button>

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2">{error}</div>
      )}

      {/* Results grouped by category */}
      {result && orderedCats.length > 0 && (
        <div className="space-y-2">
          {orderedCats.map(cat => (
            <CategoryGroup key={cat} category={cat} checks={grouped[cat]} />
          ))}
        </div>
      )}
    </div>
  )
}

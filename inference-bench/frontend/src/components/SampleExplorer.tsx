import { useState, useEffect } from 'react'
import { api } from '../api'
import type { SampleOutput } from '../types'

interface Props {
  runId: string
  rbId: string
  benchmarkName?: string
}

export default function SampleExplorer({ runId, rbId, benchmarkName }: Props) {
  const [samples, setSamples] = useState<SampleOutput[]>([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const limit = 20

  useEffect(() => {
    setLoading(true)
    api.evaluations.samples(runId, rbId, { limit, offset })
      .then(setSamples)
      .finally(() => setLoading(false))
  }, [runId, rbId, offset])

  if (loading && !samples.length) {
    return <p className="text-sm text-gray-500 py-4">Loading samples…</p>
  }

  return (
    <div>
      {benchmarkName && (
        <h3 className="text-sm font-semibold text-gray-300 mb-3">{benchmarkName} — Samples</h3>
      )}

      <div className="space-y-2">
        {samples.map(s => (
          <div key={s.id} className="bg-gray-800/50 border border-gray-700 rounded-lg">
            <button
              className="w-full text-left px-4 py-3 flex items-center gap-3"
              onClick={() => setExpanded(expanded === s.id ? null : s.id)}
            >
              <span className={`shrink-0 text-xs font-bold px-1.5 py-0.5 rounded ${
                s.is_correct ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
              }`}>
                {s.is_correct ? 'PASS' : 'FAIL'}
              </span>
              <span className="text-xs text-gray-500 shrink-0">#{s.sample_index}</span>
              <span className="text-sm text-gray-300 truncate flex-1">
                {s.question?.substring(0, 120) ?? '—'}
              </span>
              <span className="text-xs text-gray-600 shrink-0">
                {s.latency_s?.toFixed(1)}s
              </span>
            </button>

            {expanded === s.id && (
              <div className="px-4 pb-4 space-y-3 text-xs border-t border-gray-700 mt-0 pt-3">
                <div>
                  <p className="text-gray-500 font-medium mb-1">Question</p>
                  <p className="text-gray-300 whitespace-pre-wrap">{s.question ?? '—'}</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-gray-500 font-medium mb-1">Expected</p>
                    <p className="text-green-400 font-mono">{s.expected_answer ?? '—'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500 font-medium mb-1">Model Output</p>
                    <p className="text-gray-300 font-mono whitespace-pre-wrap line-clamp-6">
                      {s.model_output ?? '—'}
                    </p>
                  </div>
                </div>
                {s.reasoning_content && (
                  <div>
                    <p className="text-gray-500 font-medium mb-1">Reasoning</p>
                    <p className="text-gray-500 font-mono whitespace-pre-wrap line-clamp-8 italic">
                      {s.reasoning_content}
                    </p>
                  </div>
                )}
                <div className="flex gap-4 text-gray-600 flex-wrap">
                  <span>Latency: {s.latency_s?.toFixed(2)}s</span>
                  <span>In: {s.input_tokens} tok</span>
                  <span>Out: {s.output_tokens} tok</span>
                  <span>Finish: {s.finish_reason}</span>
                </div>
                {s.error && <p className="text-red-400">Error: {s.error}</p>}
              </div>
            )}
          </div>
        ))}
      </div>

      {samples.length === limit && (
        <div className="flex gap-2 mt-4">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(o => Math.max(0, o - limit))}
            className="btn-secondary text-xs py-1.5"
          >
            ← Prev
          </button>
          <button
            onClick={() => setOffset(o => o + limit)}
            className="btn-secondary text-xs py-1.5"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}

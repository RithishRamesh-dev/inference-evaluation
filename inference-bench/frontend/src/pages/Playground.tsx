import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import type { Model, PlaygroundRunResult, PlaygroundBatchResult, PlaygroundTemplate } from '../types'

const DEFAULT_PARAMS = {
  temperature: 0.7,
  max_tokens: 1024,
  top_p: 1.0,
  stop: [] as string[],
  response_format: 'none',
  thinking_mode: false,
}

export default function Playground() {
  // Endpoint
  const [endpointMode, setEndpointMode] = useState<'saved' | 'manual'>('saved')
  const [models, setModels] = useState<Model[]>([])
  const [selectedModelId, setSelectedModelId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [manualUrl, setManualUrl] = useState('')
  const [manualModelId, setManualModelId] = useState('')

  // Prompt
  const [systemPrompt, setSystemPrompt] = useState('')
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([
    { role: 'user', content: '' },
  ])
  const [params, setParams] = useState(DEFAULT_PARAMS)
  const [stopInput, setStopInput] = useState('')
  const [showParams, setShowParams] = useState(false)
  const [showTemplates, setShowTemplates] = useState(false)

  // Results
  const [running, setRunning] = useState(false)
  const [runMode, setRunMode] = useState<'single' | 'batch'>('single')
  const [result, setResult] = useState<PlaygroundRunResult | null>(null)
  const [batchResult, setBatchResult] = useState<PlaygroundBatchResult | null>(null)
  const [history, setHistory] = useState<Array<{ result: PlaygroundRunResult; preview: string }>>([])
  const [renderMarkdown, setRenderMarkdown] = useState(false)
  const [showReasoning, setShowReasoning] = useState(false)

  // Templates
  const [templates, setTemplates] = useState<PlaygroundTemplate[]>([])

  useEffect(() => {
    api.models.list().then(setModels).catch(() => {})
    api.playground.templates().then(setTemplates).catch(() => {})
  }, [])

  const selectedModel = models.find(m => m.id === selectedModelId)

  const buildBody = useCallback(() => {
    const endpointUrl = endpointMode === 'saved' ? (selectedModel?.endpoint_url ?? '') : manualUrl
    const modelId = endpointMode === 'saved' ? (selectedModel?.model_id ?? '') : manualModelId
    return {
      endpoint_url: endpointUrl,
      api_key: apiKey,
      model_id: modelId,
      messages: [
        ...(systemPrompt ? [{ role: 'system' as const, content: systemPrompt }] : []),
        ...messages,
      ],
      params: {
        temperature: params.temperature,
        max_tokens: params.max_tokens,
        top_p: params.top_p,
        stop: params.stop,
        response_format: params.response_format === 'none' ? undefined : params.response_format,
        thinking_mode: params.thinking_mode,
      },
    }
  }, [endpointMode, selectedModel, manualUrl, manualModelId, apiKey, systemPrompt, messages, params])

  const handleRun = useCallback(async () => {
    if (running) return
    setRunning(true)
    setRunMode('single')
    setBatchResult(null)
    try {
      const res = await api.playground.run(buildBody())
      setResult(res)
      setHistory(prev =>
        [{ result: res, preview: (res.content || res.error || '').slice(0, 60) }, ...prev].slice(0, 10)
      )
    } catch (e) {
      setResult({
        content: '',
        error: String(e),
        prompt_tokens: 0,
        completion_tokens: 0,
        reasoning_tokens: 0,
        latency_ms: 0,
      })
    } finally {
      setRunning(false)
    }
  }, [running, buildBody])

  const handleRunBatch = useCallback(async () => {
    if (running) return
    setRunning(true)
    setRunMode('batch')
    setResult(null)
    try {
      const res = await api.playground.runBatch(buildBody())
      setBatchResult(res)
    } catch (_e) {
      setBatchResult(null)
    } finally {
      setRunning(false)
    }
  }, [running, buildBody])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault()
        handleRun()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleRun])

  const addMessage = () =>
    setMessages(prev => [...prev, { role: 'user', content: '' }])

  const updateMessage = (i: number, field: 'role' | 'content', value: string) =>
    setMessages(prev =>
      prev.map((m, idx) =>
        idx === i
          ? { ...m, [field]: field === 'role' ? (value as 'user' | 'assistant') : value }
          : m
      )
    )

  const removeMessage = (i: number) =>
    setMessages(prev => prev.filter((_, idx) => idx !== i))

  const loadTemplate = (t: PlaygroundTemplate) => {
    setSystemPrompt(t.system_prompt || '')
    if (t.messages?.length) {
      setMessages(
        t.messages
          .filter(m => m.role !== 'system')
          .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))
      )
    }
    if (t.params) setParams(prev => ({ ...prev, ...t.params }))
    setShowTemplates(false)
  }

  const addStop = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && stopInput.trim()) {
      setParams(p => ({ ...p, stop: [...p.stop, stopInput.trim()] }))
      setStopInput('')
    }
  }

  const renderContent = (content: string) => {
    if (!renderMarkdown) {
      return (
        <pre className="whitespace-pre-wrap text-sm text-gray-700 font-mono leading-relaxed">
          {content}
        </pre>
      )
    }
    const html = content
      .replace(/`([^`]+)`/g, '<code class="bg-gray-100 px-1 rounded text-xs font-mono text-cyan-700">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-gray-800">$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em class="text-gray-700">$1</em>')
      .replace(/\n/g, '<br/>')
    return (
      <div
        className="text-sm text-gray-700 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  }

  return (
    <div className="flex h-full">
      {/* ─── LEFT PANEL ─────────────────────────────────────────────────── */}
      <div className="w-2/5 border-r border-gray-800 flex flex-col overflow-y-auto">
        {/* Header */}
        <div className="p-4 border-b border-gray-800 shrink-0">
          <h1 className="text-base font-bold text-gray-800">Playground</h1>
          <p className="text-xs text-gray-600 mt-0.5">Interactive prompt editor</p>
        </div>

        <div className="flex-1 p-4 space-y-4 overflow-y-auto">
          {/* ── Endpoint ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                Endpoint
              </label>
              <div className="flex gap-1 ml-auto">
                {(['saved', 'manual'] as const).map(m => (
                  <button
                    key={m}
                    onClick={() => setEndpointMode(m)}
                    className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                      endpointMode === m
                        ? 'bg-brand-600/20 border-brand-500 text-brand-400'
                        : 'border-gray-300 text-gray-600 hover:text-gray-800'
                    }`}
                  >
                    {m === 'saved' ? 'Saved Model' : 'Manual'}
                  </button>
                ))}
              </div>
            </div>

            {endpointMode === 'saved' ? (
              <select
                className="input"
                value={selectedModelId}
                onChange={e => setSelectedModelId(e.target.value)}
              >
                <option value="">Select a model…</option>
                {models.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.name} — {m.provider}
                  </option>
                ))}
              </select>
            ) : (
              <div className="space-y-2">
                <input
                  className="input"
                  placeholder="https://inference.example.com/v1"
                  value={manualUrl}
                  onChange={e => setManualUrl(e.target.value)}
                />
                <input
                  className="input"
                  placeholder="Model ID (e.g. llama3.3-70b-instruct)"
                  value={manualModelId}
                  onChange={e => setManualModelId(e.target.value)}
                />
              </div>
            )}

            {endpointMode === 'saved' && selectedModel && (
              <div className="text-xs text-gray-600 bg-gray-100 rounded px-2 py-1 font-mono truncate">
                {selectedModel.endpoint_url}
              </div>
            )}

            <div>
              <label className="label">
                API Key{' '}
                <span className="text-gray-500 font-normal normal-case tracking-normal">
                  (never stored — used only for this request)
                </span>
              </label>
              <input
                className="input"
                type="password"
                placeholder="sk-… (required)"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
              />
            </div>
          </div>

          {/* ── System Prompt ── */}
          <div>
            <label className="label">System Prompt</label>
            <textarea
              className="input font-mono text-xs resize-y min-h-[60px]"
              placeholder="You are a helpful assistant."
              value={systemPrompt}
              onChange={e => setSystemPrompt(e.target.value)}
              rows={3}
            />
          </div>

          {/* ── Messages ── */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                Messages
              </label>
              <button
                onClick={addMessage}
                className="text-xs text-brand-400 hover:text-brand-300 transition-colors"
              >
                ＋ Add
              </button>
            </div>

            {messages.map((msg, i) => (
              <div key={i} className="bg-gray-800/50 rounded-lg p-2 space-y-1.5">
                <div className="flex items-center gap-2">
                  <select
                    className="input py-0.5 text-xs flex-none w-28"
                    value={msg.role}
                    onChange={e => updateMessage(i, 'role', e.target.value)}
                  >
                    <option value="user">user</option>
                    <option value="assistant">assistant</option>
                  </select>
                  <button
                    onClick={() => removeMessage(i)}
                    className="ml-auto text-gray-600 hover:text-red-400 text-xs transition-colors"
                    title="Remove message"
                  >
                    ✕
                  </button>
                </div>
                <textarea
                  className="input font-mono text-xs resize-y min-h-[50px] w-full"
                  placeholder={msg.role === 'user' ? 'User message…' : 'Assistant response…'}
                  value={msg.content}
                  onChange={e => updateMessage(i, 'content', e.target.value)}
                  rows={2}
                />
              </div>
            ))}
          </div>

          {/* ── Generation Params (collapsible) ── */}
          <div className="border border-gray-800 rounded-lg overflow-hidden">
            <button
              onClick={() => setShowParams(p => !p)}
              className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <span>⚙ Generation Params</span>
              <span>{showParams ? '▲' : '▼'}</span>
            </button>

            {showParams && (
              <div className="px-3 pb-3 space-y-3 border-t border-gray-800 pt-3">
                {/* Temperature */}
                <div>
                  <div className="flex justify-between">
                    <label className="label">Temperature</label>
                    <span className="text-xs text-gray-600">{params.temperature.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.1}
                    value={params.temperature}
                    onChange={e =>
                      setParams(p => ({ ...p, temperature: parseFloat(e.target.value) }))
                    }
                    className="w-full accent-brand-500"
                  />
                </div>

                {/* Max tokens */}
                <div>
                  <label className="label">Max Tokens</label>
                  <input
                    type="number"
                    className="input"
                    min={1}
                    max={32000}
                    value={params.max_tokens}
                    onChange={e =>
                      setParams(p => ({ ...p, max_tokens: parseInt(e.target.value, 10) || 1024 }))
                    }
                  />
                </div>

                {/* Top-P */}
                <div>
                  <div className="flex justify-between">
                    <label className="label">Top-P</label>
                    <span className="text-xs text-gray-600">{params.top_p.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={params.top_p}
                    onChange={e =>
                      setParams(p => ({ ...p, top_p: parseFloat(e.target.value) }))
                    }
                    className="w-full accent-brand-500"
                  />
                </div>

                {/* Stop sequences */}
                <div>
                  <label className="label">Stop Sequences</label>
                  <input
                    className="input text-xs"
                    placeholder='Press Enter to add (e.g. "\n")'
                    value={stopInput}
                    onChange={e => setStopInput(e.target.value)}
                    onKeyDown={addStop}
                  />
                  {params.stop.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {params.stop.map((s, i) => (
                        <span
                          key={i}
                          className="bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded flex items-center gap-1"
                        >
                          {JSON.stringify(s)}
                          <button
                            onClick={() =>
                              setParams(p => ({ ...p, stop: p.stop.filter((_, j) => j !== i) }))
                            }
                            className="hover:text-red-400 transition-colors"
                          >
                            ✕
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Response format */}
                <div>
                  <label className="label">Response Format</label>
                  <select
                    className="input"
                    value={params.response_format}
                    onChange={e => setParams(p => ({ ...p, response_format: e.target.value }))}
                  >
                    <option value="none">Default</option>
                    <option value="json_object">JSON Object</option>
                  </select>
                </div>

                {/* Thinking mode */}
                <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={params.thinking_mode}
                    onChange={e => setParams(p => ({ ...p, thinking_mode: e.target.checked }))}
                    className="accent-brand-500"
                  />
                  Thinking mode
                </label>
              </div>
            )}
          </div>

          {/* ── Templates (collapsible) ── */}
          <div className="border border-gray-800 rounded-lg overflow-hidden">
            <button
              onClick={() => setShowTemplates(p => !p)}
              className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <span>📄 Templates</span>
              <span>{showTemplates ? '▲' : '▼'}</span>
            </button>

            {showTemplates && (
              <div className="px-2 pb-2 border-t border-gray-800">
                {templates.length === 0 ? (
                  <p className="text-xs text-gray-600 text-center py-3">No templates available</p>
                ) : (
                  <div className="grid grid-cols-2 gap-1 pt-2">
                    {templates.map(t => (
                      <button
                        key={t.id}
                        onClick={() => loadTemplate(t)}
                        className="text-left p-2 rounded bg-gray-800/50 hover:bg-gray-800 border border-gray-800 hover:border-gray-700 transition-colors"
                      >
                        <p className="text-xs font-medium text-gray-700 truncate">{t.name}</p>
                        <p className="text-[10px] text-gray-600 truncate mt-0.5">{t.description}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── Action Buttons ── */}
        <div className="p-4 border-t border-gray-800 space-y-2 shrink-0">
          <button
            onClick={handleRun}
            disabled={running}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {running && runMode === 'single' ? (
              <>
                <span className="animate-spin w-3 h-3 border-2 border-white/20 border-t-white rounded-full inline-block" />
                Running…
              </>
            ) : (
              '▶ Run  ⌘↵'
            )}
          </button>
          <button
            onClick={handleRunBatch}
            disabled={running}
            className="btn-secondary w-full flex items-center justify-center gap-2"
          >
            {running && runMode === 'batch' ? (
              <>
                <span className="animate-spin w-3 h-3 border-2 border-white/20 border-t-white rounded-full inline-block" />
                Running 5×…
              </>
            ) : (
              '⟳ Run 5× (consistency test)'
            )}
          </button>
        </div>
      </div>

      {/* ─── RIGHT PANEL ────────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col overflow-y-auto">

          {/* ── Running state ── */}
          {running && (
            <div className="flex items-center justify-center h-32 text-gray-600 text-sm gap-2">
              <span className="animate-spin w-4 h-4 border-2 border-gray-700 border-t-gray-400 rounded-full inline-block" />
              {runMode === 'batch' ? 'Running 5 completions…' : 'Waiting for response…'}
            </div>
          )}

          {/* ── Single result ── */}
          {!running && runMode === 'single' && result && (
            <div className="p-4 space-y-3">
              {/* Controls row */}
              <div className="flex items-center justify-between">
                <div className="flex gap-2">
                  {(['Raw', 'Rendered'] as const).map(mode => (
                    <button
                      key={mode}
                      onClick={() => setRenderMarkdown(mode === 'Rendered')}
                      className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                        (renderMarkdown ? 'Rendered' : 'Raw') === mode
                          ? 'bg-brand-600/20 border-brand-500 text-brand-400'
                          : 'border-gray-300 text-gray-600 hover:text-gray-800'
                      }`}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
                {result.finish_reason && (
                  <span
                    className={`text-xs px-2 py-0.5 rounded border ${
                      result.finish_reason === 'stop'
                        ? 'border-green-700/40 text-green-400'
                        : 'border-yellow-700/40 text-yellow-400'
                    }`}
                  >
                    {result.finish_reason}
                  </span>
                )}
              </div>

              {/* Content or error */}
              {result.error ? (
                <div className="card border-red-800/40 text-red-400 text-sm">{result.error}</div>
              ) : (
                <div className="card">{renderContent(result.content)}</div>
              )}

              {/* Reasoning (collapsible) */}
              {result.reasoning_content && (
                <div className="border border-gray-800 rounded-lg overflow-hidden">
                  <button
                    onClick={() => setShowReasoning(p => !p)}
                    className="w-full flex items-center justify-between px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 transition-colors"
                  >
                    <span>🧠 Reasoning</span>
                    <span>{showReasoning ? '▲' : '▼'}</span>
                  </button>
                  {showReasoning && (
                    <div className="px-3 pb-3 pt-1 border-t border-gray-800">
                      <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono">
                        {result.reasoning_content}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* Usage stats */}
              <div className="flex flex-wrap gap-3 text-xs text-gray-600">
                <span className="flex items-center gap-1">
                  <span className="text-gray-500">prompt</span>
                  <span className="badge-gray">{result.prompt_tokens}</span>
                </span>
                <span className="flex items-center gap-1">
                  <span className="text-gray-500">completion</span>
                  <span className="badge-gray">{result.completion_tokens}</span>
                </span>
                {result.reasoning_tokens > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="text-gray-500">reasoning</span>
                    <span className="badge-gray">{result.reasoning_tokens}</span>
                  </span>
                )}
                <span className="flex items-center gap-1">
                  <span className="text-gray-500">latency</span>
                  <span className="badge-gray">{result.latency_ms.toFixed(0)}ms</span>
                </span>
                {result.cost_estimate !== undefined && result.cost_estimate > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="text-gray-500">cost</span>
                    <span className="badge-gray">${result.cost_estimate.toFixed(5)}</span>
                  </span>
                )}
              </div>
            </div>
          )}

          {/* ── Batch results ── */}
          {!running && runMode === 'batch' && batchResult && (
            <div className="p-4 space-y-3">
              {/* Stats grid */}
              <div className="grid grid-cols-4 gap-3">
                <div className="card text-center">
                  <p
                    className={`text-2xl font-bold ${
                      batchResult.consistency_score >= 0.8
                        ? 'text-green-600'
                        : batchResult.consistency_score >= 0.6
                        ? 'text-yellow-600'
                        : 'text-red-600'
                    }`}
                  >
                    {(batchResult.consistency_score * 100).toFixed(0)}%
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5">Consistent</p>
                </div>
                <div className="card text-center">
                  <p className="text-xl font-bold text-gray-800">
                    {batchResult.avg_latency_ms.toFixed(0)}ms
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5">Avg latency</p>
                </div>
                <div className="card text-center">
                  <p className="text-xl font-bold text-gray-700">
                    {batchResult.min_latency_ms.toFixed(0)}ms
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5">Min</p>
                </div>
                <div className="card text-center">
                  <p className="text-xl font-bold text-gray-700">
                    {batchResult.max_latency_ms.toFixed(0)}ms
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5">Max</p>
                </div>
              </div>

              {/* Individual results */}
              <div className="space-y-2">
                {batchResult.results.map((r, i) => (
                  <details key={i} className="border border-gray-200 rounded-lg">
                    <summary className="px-3 py-2 text-xs cursor-pointer text-gray-600 hover:text-gray-800 flex items-center gap-2 list-none">
                      <span className="font-mono text-gray-500">#{i + 1}</span>
                      <span className="flex-1 truncate text-gray-700">
                        {r.error ? (
                          <span className="text-red-600">{r.error.slice(0, 80)}</span>
                        ) : (
                          r.content.slice(0, 80)
                        )}
                      </span>
                      <span className="text-gray-600 shrink-0">{r.latency_ms.toFixed(0)}ms</span>
                    </summary>
                    <div className="px-3 pb-3 pt-1 border-t border-gray-200">
                      {r.error ? (
                        <p className="text-xs text-red-600">{r.error}</p>
                      ) : (
                        <pre className="text-xs text-gray-700 whitespace-pre-wrap">{r.content}</pre>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}

          {/* ── Empty state ── */}
          {!running && !result && !batchResult && (
            <div className="flex flex-col items-center justify-center h-full text-gray-600 gap-2 p-8">
              <span className="text-4xl select-none">🎮</span>
              <p className="text-sm">Configure your endpoint and run a prompt</p>
              <p className="text-xs text-gray-700">⌘ + Enter to run</p>
            </div>
          )}
        </div>

        {/* ── History sidebar ── */}
        {history.length > 0 && (
          <div className="w-48 border-l border-gray-800 flex flex-col overflow-y-auto shrink-0">
            <div className="px-3 py-2 border-b border-gray-800 shrink-0">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                History
              </p>
            </div>
            <div className="flex-1 overflow-y-auto">
              {history.map((h, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setResult(h.result)
                    setRunMode('single')
                    setBatchResult(null)
                  }}
                  className="w-full text-left px-3 py-2 border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                >
                  <p className="text-xs text-gray-600 truncate">{h.preview || '(empty)'}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">
                    {h.result.latency_ms.toFixed(0)}ms
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

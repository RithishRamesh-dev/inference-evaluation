import { useState, useEffect } from 'react'
import { api } from '../api'
import type { WebhookKey } from '../types'

export default function Integrations() {
  const [keys, setKeys] = useState<WebhookKey[]>([])
  const [newKey, setNewKey] = useState<{ key: string; name: string } | null>(null)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  const load = () => api.webhooks.keys().then(setKeys)
  useEffect(() => { load() }, [])

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text).then(() => { setCopied(label); setTimeout(() => setCopied(null), 2000) })
  }

  const createKey = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const k = await api.webhooks.createKey(newName)
      setNewKey({ key: k.key, name: k.name })
      setNewName('')
      load()
    } finally { setCreating(false) }
  }

  const deleteKey = async (id: string) => {
    if (!confirm('Delete this webhook key? This cannot be undone.')) return
    await api.webhooks.deleteKey(id)
    load()
  }

  const gaugeUrl = window.location.origin
  const curlExample = `curl -X POST ${gaugeUrl}/api/webhooks/trigger \\
  -H "X-Gauge-Webhook-Key: YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model_id":"MODEL_ID","benchmark_ids":["BENCH_ID"]}'`

  const ghActionsYaml = `- name: Run Gauge Evaluation
  run: |
    curl -s -X POST \${{ secrets.GAUGE_URL }}/api/webhooks/trigger \\
      -H "X-Gauge-Webhook-Key: \${{ secrets.GAUGE_WEBHOOK_KEY }}" \\
      -H "Content-Type: application/json" \\
      -d '{"model_id":"\${{ vars.MODEL_ID }}","benchmark_ids":["aime25","mmlu_pro","humaneval"],"callback_url":"\${{ vars.CALLBACK_URL }}"}'`

  return (
    <div className="p-6 space-y-8 max-w-3xl mx-auto">
      <div>
        <h1 className="text-xl font-bold text-gray-800">Integrations</h1>
        <p className="text-sm text-gray-600 mt-0.5">CI/CD webhooks and API access</p>
      </div>

      {/* Webhook Keys */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Webhook Keys</h2>
        <div className="flex gap-2">
          <input className="input flex-1" placeholder="Key name (e.g. GitHub CI)" value={newName} onChange={e => setNewName(e.target.value)} />
          <button onClick={createKey} disabled={creating || !newName.trim()} className="btn-primary">{creating ? 'Creating…' : 'Generate Key'}</button>
        </div>

        {newKey && (
          <div className="card border-green-800/40 bg-green-950/10 space-y-2">
            <p className="text-xs font-semibold text-green-400">✓ Key created — copy it now, it won't be shown again</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs font-mono bg-gray-900 px-2 py-1.5 rounded text-green-300 break-all">{newKey.key}</code>
              <button onClick={() => copy(newKey.key, 'key')} className="btn-secondary text-xs py-1 shrink-0">
                {copied === 'key' ? '✓ Copied' : 'Copy'}
              </button>
            </div>
            <button onClick={() => setNewKey(null)} className="text-xs text-gray-600 hover:text-gray-400">Dismiss</button>
          </div>
        )}

        <div className="space-y-2">
          {keys.length === 0 && <p className="text-xs text-gray-600">No webhook keys yet</p>}
          {keys.map(k => (
            <div key={k.id} className="card flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-700">{k.name}</p>
                <p className="text-xs text-gray-600 font-mono">{k.key_prefix}…</p>
              </div>
              <p className="text-xs text-gray-600">{k.created_at ? new Date(k.created_at).toLocaleDateString() : ''}</p>
              <button onClick={() => deleteKey(k.id)} className="text-xs text-red-500 hover:text-red-400">Revoke</button>
            </div>
          ))}
        </div>
      </section>

      {/* Curl example */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Trigger from curl</h2>
        <div className="relative">
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 text-gray-700 overflow-x-auto whitespace-pre-wrap">{curlExample}</pre>
          <button onClick={() => copy(curlExample, 'curl')} className="absolute top-2 right-2 btn-secondary text-xs py-0.5 px-2">
            {copied === 'curl' ? '✓' : 'Copy'}
          </button>
        </div>
      </section>

      {/* GitHub Actions */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">GitHub Actions</h2>
        <p className="text-xs text-gray-600">Add to your workflow YAML to trigger evaluations on push:</p>
        <div className="relative">
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 text-gray-700 overflow-x-auto whitespace-pre-wrap">{ghActionsYaml}</pre>
          <button onClick={() => copy(ghActionsYaml, 'gh')} className="absolute top-2 right-2 btn-secondary text-xs py-0.5 px-2">
            {copied === 'gh' ? '✓' : 'Copy'}
          </button>
        </div>
        <p className="text-xs text-gray-600">Set secrets: <code className="font-mono">GAUGE_URL</code>, <code className="font-mono">GAUGE_WEBHOOK_KEY</code></p>
      </section>

      {/* Result payload */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">Callback Payload</h2>
        <p className="text-xs text-gray-600">When evaluation completes, Gauge posts this to your callback_url:</p>
        <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 text-gray-600 overflow-x-auto">{JSON.stringify({ run_id: "abc123", status: "completed", overall_score: 0.847, passed: true, benchmarks: [{ name: "aime25", score: 0.933, passed: true }], regressions: [], duration_seconds: 1847 }, null, 2)}</pre>
      </section>
    </div>
  )
}

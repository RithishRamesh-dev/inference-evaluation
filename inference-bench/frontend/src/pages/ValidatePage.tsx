import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../api'
import type { Model } from '../types'
import ValidationPanel from '../components/ValidationPanel'
import StressTestPanel from '../components/StressTestPanel'

export default function ValidatePage() {
  const { modelId } = useParams<{ modelId: string }>()
  const [model, setModel] = useState<Model | null>(null)
  const [tab, setTab] = useState<'validate' | 'stress'>('validate')

  useEffect(() => {
    if (modelId) api.models.get(modelId).then(setModel).catch(() => {})
  }, [modelId])

  if (!modelId) return <div className="p-6 text-gray-600">No model ID</div>

  return (
    <div className="p-6 space-y-5 max-w-3xl mx-auto">
      <div className="flex items-center gap-3">
        <Link to="/models" className="text-gray-600 hover:text-gray-800 text-sm">← Models</Link>
        <span className="text-gray-300">/</span>
        <h1 className="text-lg font-bold text-gray-800">
          {model?.name ?? modelId}
        </h1>
        {model && (
          <span className="text-xs text-gray-600 font-mono">{model.model_id}</span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {([['validate', '✓ Validation'], ['stress', '⚡ Stress Test']] as const).map(([t, lbl]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === t
                ? 'border-brand-500 text-brand-400'
                : 'border-transparent text-gray-600 hover:text-gray-800'
            }`}
          >
            {lbl}
          </button>
        ))}
      </div>

      {tab === 'validate' && <ValidationPanel modelId={modelId} />}
      {tab === 'stress' && <StressTestPanel modelId={modelId} />}
    </div>
  )
}

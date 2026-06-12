import type { Model } from '../types'

interface Props {
  model: Model
  onSelect?: (m: Model) => void
  selected?: boolean
  onTest?: (id: string) => void
}

const Cap = ({ label, active }: { label: string; active: boolean }) =>
  active ? <span className="badge-blue">{label}</span> : null

export default function ModelCard({ model, onSelect, selected, onTest }: Props) {
  return (
    <div
      className={`card cursor-pointer hover:border-gray-700 transition-colors ${
        selected ? 'border-brand-600 bg-brand-600/5' : ''
      }`}
      onClick={() => onSelect?.(model)}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">{model.provider}</p>
          <h3 className="mt-0.5 text-sm font-semibold text-gray-100">{model.name}</h3>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{model.model_id}</p>
        </div>
        {selected && <span className="text-brand-400 text-lg">✓</span>}
      </div>

      {model.context_length && (
        <p className="text-xs text-gray-500 mt-2">{(model.context_length / 1000).toFixed(0)}k context</p>
      )}

      <div className="flex flex-wrap gap-1 mt-3">
        <Cap label="Vision" active={model.supports_vision} />
        <Cap label="Tools" active={model.supports_tool_calling} />
        <Cap label="Reasoning" active={model.supports_reasoning} />
        <Cap label="Structured" active={model.supports_structured_output} />
        <Cap label="Multimodal" active={model.supports_multimodal} />
      </div>

      {onTest && (
        <button
          className="btn-secondary text-xs py-1 mt-3 w-full"
          onClick={e => { e.stopPropagation(); onTest(model.id) }}
        >
          Test Connection
        </button>
      )}
    </div>
  )
}

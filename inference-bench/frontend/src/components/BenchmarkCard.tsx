import type { BenchmarkSuite } from '../types'

interface Props {
  bench: BenchmarkSuite
  selected: boolean
  onToggle: (id: number) => void
  disabled?: boolean
  disabledReason?: string
}

const CATEGORY_COLOR: Record<string, string> = {
  math: 'text-purple-400',
  coding: 'text-green-400',
  vision: 'text-pink-400',
  general: 'text-blue-400',
  science: 'text-orange-400',
  reasoning: 'text-yellow-400',
  tool_calling: 'text-cyan-400',
  compliance: 'text-red-400',
}

export default function BenchmarkCard({ bench, selected, onToggle, disabled, disabledReason }: Props) {
  const catColor = CATEGORY_COLOR[bench.category] ?? 'text-gray-400'

  return (
    <div
      title={disabled ? disabledReason : undefined}
      onClick={() => !disabled && onToggle(bench.id)}
      className={`card transition-all cursor-pointer select-none
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'hover:border-gray-600'}
        ${selected && !disabled ? 'border-brand-600 bg-brand-600/5' : ''}
      `}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            {bench.is_recommended && (
              <span className="badge bg-yellow-900/40 text-yellow-400 border border-yellow-800">★ Rec</span>
            )}
            <span className={`text-xs font-medium ${catColor}`}>{bench.category}</span>
          </div>
          <h3 className="text-sm font-semibold text-gray-100 mt-1">{bench.display_name}</h3>
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{bench.description}</p>
        </div>
        <div className="ml-3 shrink-0">
          <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors
            ${selected && !disabled ? 'bg-brand-600 border-brand-600' : 'border-gray-600 bg-gray-800'}`}>
            {selected && !disabled && <span className="text-white text-xs">✓</span>}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-gray-500">
        {bench.total_samples && <span>{bench.total_samples.toLocaleString()} samples</span>}
        <span className="font-mono">{bench.default_metric}</span>
        {bench.is_vision && <span className="badge-blue">Vision</span>}
        {bench.requires_tools && <span className="badge-yellow">Tools</span>}
      </div>
    </div>
  )
}

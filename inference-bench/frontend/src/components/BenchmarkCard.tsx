import type { BenchmarkSuite } from '../types'

interface Props {
  bench: BenchmarkSuite
  selected: boolean
  onToggle: (id: string) => void
  disabled?: boolean
  disabledReason?: string
}

const CATEGORY_COLOR: Record<string, string> = {
  math: 'text-purple-600',
  coding: 'text-green-600',
  vision: 'text-pink-600',
  general: 'text-blue-600',
  science: 'text-orange-600',
  reasoning: 'text-yellow-600',
  tool_calling: 'text-cyan-700',
  compliance: 'text-red-600',
}

export default function BenchmarkCard({ bench, selected, onToggle, disabled, disabledReason }: Props) {
  const catColor = CATEGORY_COLOR[bench.category] ?? 'text-gray-600'

  return (
    <div
      title={disabled ? disabledReason : undefined}
      onClick={() => !disabled && onToggle(bench.id)}
      className={`card transition-all cursor-pointer select-none
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'hover:border-do-blue/50'}
        ${selected && !disabled ? 'border-brand-600 bg-brand-600/5' : ''}
      `}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            {bench.is_recommended && (
              <span className="badge bg-yellow-50 text-yellow-700 border border-yellow-200">★ Rec</span>
            )}
            <span className={`text-xs font-medium ${catColor}`}>{bench.category}</span>
          </div>
          <h3 className="text-sm font-semibold text-gray-900 mt-1">{bench.display_name}</h3>
          <p className="text-xs text-gray-600 mt-0.5 line-clamp-2">{bench.description}</p>
        </div>
        <div className="ml-3 shrink-0">
          <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-colors
            ${selected && !disabled ? 'bg-brand-600 border-brand-600' : 'border-gray-300 bg-white'}`}>
            {selected && !disabled && <span className="text-white text-xs">✓</span>}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-gray-600">
        {bench.total_samples && <span>{bench.total_samples.toLocaleString()} samples</span>}
        <span className="font-mono">{bench.default_metric}</span>
        {bench.is_vision && <span className="badge-blue">Vision</span>}
        {bench.requires_tools && <span className="badge-yellow">Tools</span>}
      </div>
    </div>
  )
}

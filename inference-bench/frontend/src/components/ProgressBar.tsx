interface Props {
  percent: number
  label?: string
  color?: 'blue' | 'green' | 'yellow' | 'red'
  size?: 'sm' | 'md' | 'lg'
}

const COLOR = {
  blue:   'bg-brand-500',
  green:  'bg-green-500',
  yellow: 'bg-yellow-500',
  red:    'bg-red-500',
}

const HEIGHT = { sm: 'h-1.5', md: 'h-2.5', lg: 'h-4' }

export default function ProgressBar({ percent, label, color = 'blue', size = 'md' }: Props) {
  const clamped = Math.min(100, Math.max(0, percent))
  return (
    <div>
      {label && (
        <div className="flex justify-between text-xs text-gray-400 mb-1">
          <span>{label}</span>
          <span>{clamped.toFixed(0)}%</span>
        </div>
      )}
      <div className={`w-full bg-gray-800 rounded-full overflow-hidden ${HEIGHT[size]}`}>
        <div
          className={`${HEIGHT[size]} rounded-full transition-all duration-500 ${COLOR[color]}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}

interface Props {
  title: string
  score: number | null
  metric?: string
  sampleCount?: number | null
  status?: string
  target?: number
}

export default function ScoreCard({ title, score, metric = 'acc', sampleCount, status, target }: Props) {
  const pct = score != null ? score * 100 : null
  const passed = target != null && pct != null && pct >= target * 100
  const failed  = target != null && pct != null && pct < target * 100

  return (
    <div className="card text-center">
      <p className="text-xs text-gray-400 font-medium truncate" title={title}>{title}</p>
      <p className={`text-3xl font-bold mt-2 ${
        status === 'failed' ? 'text-red-400' :
        passed ? 'text-green-400' :
        failed ? 'text-yellow-400' :
        'text-gray-100'
      }`}>
        {pct != null ? `${pct.toFixed(1)}%` : status === 'failed' ? 'ERR' : '—'}
      </p>
      <p className="text-xs text-gray-600 mt-1 font-mono">{metric}</p>
      {sampleCount != null && (
        <p className="text-xs text-gray-600 mt-0.5">{sampleCount.toLocaleString()} samples</p>
      )}
      {target != null && pct != null && (
        <p className={`text-xs mt-1 font-medium ${passed ? 'text-green-400' : 'text-yellow-400'}`}>
          {passed ? '✓ Target met' : `${(pct - target * 100).toFixed(1)}% vs target`}
        </p>
      )}
    </div>
  )
}

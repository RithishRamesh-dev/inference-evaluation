import {
  Radar, RadarChart as ReRadar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Legend, Tooltip,
} from 'recharts'

export interface RadarSeries {
  name: string
  color: string
  data: Record<string, number>
}

interface Props {
  series: RadarSeries[]
}

export default function RadarChart({ series }: Props) {
  if (!series.length) return null

  // Collect all categories
  const categories = Array.from(new Set(series.flatMap(s => Object.keys(s.data))))

  // Build recharts-compatible data: [{category, run1: val, run2: val}]
  const chartData = categories.map(cat => {
    const point: Record<string, string | number> = { category: cat }
    series.forEach(s => {
      point[s.name] = parseFloat(((s.data[cat] ?? 0) * 100).toFixed(1))
    })
    return point
  })

  return (
    <ResponsiveContainer width="100%" height={320}>
      <ReRadar data={chartData}>
        <PolarGrid stroke="#374151" />
        <PolarAngleAxis dataKey="category" tick={{ fill: '#9CA3AF', fontSize: 11 }} />
        <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#6B7280', fontSize: 10 }} />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
          labelStyle={{ color: '#F9FAFB' }}
          formatter={(v: number) => `${v}%`}
        />
        {series.map(s => (
          <Radar
            key={s.name}
            name={s.name}
            dataKey={s.name}
            stroke={s.color}
            fill={s.color}
            fillOpacity={0.15}
          />
        ))}
        {series.length > 1 && <Legend />}
      </ReRadar>
    </ResponsiveContainer>
  )
}

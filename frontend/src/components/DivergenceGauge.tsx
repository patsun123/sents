import { clsx } from 'clsx'

interface Props {
  sentimentPrice: number | null
  realPrice: number | null
  size?: 'sm' | 'md'
}

export function DivergenceGauge({ sentimentPrice, realPrice, size = 'sm' }: Props) {
  if (sentimentPrice === null || realPrice === null || realPrice === 0) {
    return <span className="text-slate-600 text-xs">—</span>
  }

  const pctDiff = ((sentimentPrice - realPrice) / realPrice) * 100
  const clamped = Math.max(-10, Math.min(10, pctDiff))
  const normalized = (clamped + 10) / 20 // 0..1

  const isPositive = pctDiff >= 0
  const barColor = isPositive ? 'bg-emerald-500' : 'bg-red-500'
  const textColor = isPositive ? 'text-emerald-400' : 'text-red-400'

  const isSm = size === 'sm'
  const barWidth = isSm ? 48 : 80
  const barHeight = isSm ? 6 : 10

  return (
    <div className={clsx('flex items-center gap-2', isSm ? 'gap-1.5' : 'gap-2')}>
      <div
        className="relative rounded-full bg-slate-700 overflow-hidden"
        style={{ width: barWidth, height: barHeight }}
      >
        {/* Center marker */}
        <div
          className="absolute top-0 bottom-0 w-px bg-slate-500"
          style={{ left: '50%' }}
        />
        {/* Fill bar */}
        <div
          className={clsx('absolute top-0 bottom-0 rounded-full', barColor)}
          style={{
            left: `${Math.min(normalized, 0.5) * 100}%`,
            width: `${Math.abs(normalized - 0.5) * 100}%`,
          }}
        />
      </div>
      <span className={clsx('font-mono tabular-nums', textColor, isSm ? 'text-xs' : 'text-sm')}>
        {isPositive ? '+' : ''}{pctDiff.toFixed(1)}%
      </span>
    </div>
  )
}

import { clsx } from 'clsx'

type Timeframe = '1d' | '1w' | '1m'

interface Props {
  value: Timeframe
  onChange: (tf: Timeframe) => void
}

const OPTIONS: { value: Timeframe; label: string }[] = [
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
]

export function TimeframeSelector({ value, onChange }: Props) {
  return (
    <div className="flex gap-1 rounded-lg bg-slate-900 p-1">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={clsx(
            'rounded-md px-3 py-1 text-xs font-semibold transition-colors',
            value === opt.value
              ? 'bg-slate-700 text-white'
              : 'text-slate-400 hover:text-slate-200'
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

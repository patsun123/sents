interface Props {
  value: number
  max: number
  unit: 'hours' | 'days'
  onChange: (v: number) => void
}

export function ShiftControl({ value, max, unit, onChange }: Props) {
  if (max === 0) return null

  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span className="uppercase tracking-wider font-semibold">Shift</span>
      <button
        onClick={() => onChange(Math.max(0, value - 1))}
        disabled={value === 0}
        className="w-6 h-6 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-30 flex items-center justify-center font-mono"
      >
        −
      </button>
      <span className="w-16 text-center font-mono text-slate-200">
        {value === 0 ? 'none' : `${value}${unit[0]}`}
      </span>
      <button
        onClick={() => onChange(Math.min(max, value + 1))}
        disabled={value === max}
        className="w-6 h-6 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-30 flex items-center justify-center font-mono"
      >
        +
      </button>
    </div>
  )
}

import { clsx } from 'clsx'
import type { StalenessLevel } from '@/types/api'

interface Props {
  staleness: StalenessLevel
  className?: string
}

const CONFIG: Record<StalenessLevel, { dot: string; label: string }> = {
  fresh:       { dot: 'bg-emerald-400', label: 'Live'      },
  warning:     { dot: 'bg-amber-400',   label: 'Delayed'   },
  critical:    { dot: 'bg-orange-500',  label: 'Stale'     },
  unavailable: { dot: 'bg-slate-500',   label: 'No data'   },
}

export function StalenessIndicator({ staleness, className }: Props) {
  const { dot, label } = CONFIG[staleness]
  return (
    <span className={clsx('inline-flex items-center gap-1.5 text-xs', className)}>
      <span className={clsx('h-2 w-2 rounded-full', dot)} />
      <span className="text-slate-400">{label}</span>
    </span>
  )
}

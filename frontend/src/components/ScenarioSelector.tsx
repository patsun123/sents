import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { queryKeys } from '@/lib/queryKeys'
import { api } from '@/lib/api'
import { scenarioColor } from '@/lib/scenarioColors'
import type { PricingConfig } from '@/types/api'

interface Props {
  selected: string[]
  onChange: (slugs: string[]) => void
}

export function ScenarioSelector({ selected, onChange }: Props) {
  const { data } = useQuery({
    queryKey: queryKeys.pricing.configs(),
    queryFn: api.getPricingConfigs,
    staleTime: 5 * 60_000,  // configs change rarely
  })

  const configs = data?.configs ?? []

  function toggle(slug: string) {
    if (selected.includes(slug)) {
      onChange(selected.filter((s) => s !== slug))
    } else if (selected.length < 3) {
      onChange([...selected, slug])
    }
  }

  if (configs.length === 0) return null

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-slate-500 uppercase tracking-wider font-semibold pr-1">
        Compare:
      </span>
      {configs.map((config: PricingConfig, idx: number) => {
        const isActive = selected.includes(config.slug)
        const color = scenarioColor(idx)
        return (
          <button
            key={config.slug}
            onClick={() => toggle(config.slug)}
            title={config.description ?? config.name}
            className={clsx(
              'flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all border',
              isActive
                ? 'border-transparent text-white'
                : 'border-slate-600 text-slate-400 hover:border-slate-400 hover:text-slate-200 bg-transparent'
            )}
            style={isActive ? { backgroundColor: color, borderColor: color } : {}}
          >
            <span
              className="h-2 w-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: isActive ? 'rgba(255,255,255,0.7)' : color }}
            />
            {config.name}
          </button>
        )
      })}
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { queryKeys } from '@/lib/queryKeys'
import { api } from '@/lib/api'
import { useMarketSSE } from '@/hooks/useMarketSSE'
import { StalenessIndicator } from './StalenessIndicator'
import { SparklineChart } from './SparklineChart'
import { DivergenceGauge } from './DivergenceGauge'
import type { TickerSummary } from '@/types/api'

interface Props {
  onSelectTicker: (ticker: string) => void
  selectedTicker: string | null
}

function PriceCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-slate-500">—</span>
  return (
    <span className="font-mono text-sm">
      ${value.toFixed(2)}
    </span>
  )
}

function DeltaCell({ delta }: { delta: number }) {
  const positive = delta >= 0
  return (
    <span className={clsx('font-mono text-sm tabular-nums', positive ? 'text-emerald-400' : 'text-red-400')}>
      {positive ? '+' : ''}{delta.toFixed(2)}
    </span>
  )
}

export function MarketTable({ onSelectTicker, selectedTicker }: Props) {
  // Subscribe to SSE updates (updates cache directly)
  useMarketSSE()

  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.market.overview(),
    queryFn: api.getMarketOverview,
    refetchInterval: 60_000,   // fallback poll every 60s
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
        <div className="animate-pulse space-y-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-10 rounded bg-slate-700" />
          ))}
        </div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-800 bg-slate-800 p-6 text-red-400 text-sm">
        Failed to load market data. Check your connection.
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200 tracking-wide uppercase">
          Market Overview
        </h2>
        <span className="text-xs text-slate-500">
          {data.tickers.length} tickers
        </span>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-slate-500 uppercase tracking-wider">
            <th className="text-left px-5 py-3">Ticker</th>
            <th className="text-right px-5 py-3">Sentiment $</th>
            <th className="text-right px-5 py-3">Real $</th>
            <th className="text-right px-5 py-3">Trend</th>
            <th className="text-right px-5 py-3">Divergence</th>
            <th className="text-right px-5 py-3">Mentions/24h</th>
            <th className="text-right px-5 py-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {data.tickers.map((ticker: TickerSummary) => (
            <tr
              key={ticker.ticker}
              onClick={() => onSelectTicker(ticker.ticker)}
              className={clsx(
                'border-t border-slate-700/50 cursor-pointer transition-colors',
                selectedTicker === ticker.ticker
                  ? 'bg-blue-900/30'
                  : 'hover:bg-slate-700/40'
              )}
            >
              <td className="px-5 py-3.5">
                <span className="font-bold text-white tracking-wide">
                  {ticker.ticker}
                </span>
              </td>
              <td className="px-5 py-3.5 text-right">
                <PriceCell value={ticker.sentiment_price}  />
              </td>
              <td className="px-5 py-3.5 text-right">
                <PriceCell value={ticker.real_price}  />
              </td>
              <td className="px-5 py-3.5 text-right">
                <SparklineChart data={ticker.sparkline ?? []} />
              </td>
              <td className="px-5 py-3.5 text-right">
                <DivergenceGauge sentimentPrice={ticker.sentiment_price} realPrice={ticker.real_price} size="sm" />
              </td>
              <td className="px-5 py-3.5 text-right font-mono text-slate-300">
                {ticker.mention_count_24h.toLocaleString()}
              </td>
              <td className="px-5 py-3.5 text-right">
                <StalenessIndicator staleness={ticker.staleness} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '@/lib/queryKeys'
import { api } from '@/lib/api'
import { useTickerSSE } from '@/hooks/useTickerSSE'
import { TickerChart } from './TickerChart'
import { ChartLegend } from './ChartLegend'
import { DivergenceGauge } from './DivergenceGauge'
import { TimeframeSelector } from './TimeframeSelector'
import { ScenarioSelector } from './ScenarioSelector'
import { ShiftControl } from './ShiftControl'

interface Props {
  ticker: string
  onClose: () => void
}

const SHIFT_MAX: Record<string, { max: number; unit: 'hours' | 'days' }> = {
  '1d': { max: 23, unit: 'hours' },
  '1w': { max: 6, unit: 'days' },
  '1m': { max: 29, unit: 'days' },
}

export function TickerDetail({ ticker, onClose }: Props) {
  const [timeframe, setTimeframe] = useState<'1d' | '1w' | '1m'>('1d')
  const [shift, setShift] = useState(0)
  const [scenarios, setScenarios] = useState<string[]>([])

  useTickerSSE(ticker)

  const { data: marketData } = useQuery({
    queryKey: queryKeys.market.overview(),
    queryFn: api.getMarketOverview,
    staleTime: 30_000,
  })
  const tickerData = marketData?.tickers.find((t) => t.ticker === ticker)

  const { data: configsData } = useQuery({
    queryKey: queryKeys.pricing.configs(),
    queryFn: api.getPricingConfigs,
    staleTime: 5 * 60_000,
  })
  const configs = configsData?.configs ?? []

  const { max: shiftMax, unit: shiftUnit } = SHIFT_MAX[timeframe]

  function handleTimeframeChange(tf: '1d' | '1w' | '1m') {
    setTimeframe(tf)
    setShift(0)  // reset shift when timeframe changes
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-white tracking-wide">{ticker}</h2>
          {tickerData && (
            <DivergenceGauge
              sentimentPrice={tickerData.sentiment_price}
              realPrice={tickerData.real_price}
              size="md"
            />
          )}
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-white text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4 px-5 py-3 border-b border-slate-700/50">
        <TimeframeSelector value={timeframe} onChange={handleTimeframeChange} />
        <ShiftControl
          value={shift}
          max={shiftMax}
          unit={shiftUnit}
          onChange={setShift}
        />
        <div className="ml-auto">
          <ScenarioSelector selected={scenarios} onChange={setScenarios} />
        </div>
      </div>

      {/* Chart */}
      <div className="p-4">
        <TickerChart
          ticker={ticker}
          timeframe={timeframe}
          shift={shift}
          scenarioSlugs={scenarios}
          configs={configs}
        />
        <ChartLegend items={[
          { label: 'Sentiment Price', color: '#3b82f6', style: 'solid' },
          { label: 'Real Price', color: '#94a3b8', style: 'dashed' },
        ]} />
      </div>
    </div>
  )
}

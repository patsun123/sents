import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineData,
  ColorType,
  LineStyle,
} from 'lightweight-charts'
import { queryKeys } from '@/lib/queryKeys'
import { api } from '@/lib/api'
import { scenarioColor } from '@/lib/scenarioColors'
import type { PricingConfig } from '@/types/api'

interface Props {
  ticker: string
  timeframe: '1d' | '1w' | '1m'
  shift: number
  scenarioSlugs: string[]
  configs: PricingConfig[]
}

const CHART_BG = '#1e293b'
const SENTIMENT_COLOR = '#3b82f6'  // blue
const REAL_COLOR = '#94a3b8'        // slate

function toTimestamp(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000)
}

export function TickerChart({ ticker, timeframe, shift, scenarioSlugs, configs }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<Record<string, ISeriesApi<'Line'>>>({})

  const { data, isLoading } = useQuery({
    queryKey: [...queryKeys.ticker.history(ticker, timeframe, scenarioSlugs), shift],
    queryFn: () =>
      api.getTickerHistory(
        ticker,
        timeframe,
        scenarioSlugs.length ? scenarioSlugs : undefined,
        shift || undefined,
      ),
    staleTime: 30_000,
    enabled: !!ticker,
  })

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: CHART_BG },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#334155' },
        horzLines: { color: '#334155' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: 360,
    })

    // Sentiment price line (primary)
    seriesRef.current['sentiment'] = chart.addLineSeries({
      color: SENTIMENT_COLOR,
      lineWidth: 2,
      title: 'Sentiment $',
    })

    // Real price line
    seriesRef.current['real'] = chart.addLineSeries({
      color: REAL_COLOR,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: 'Real $',
    })

    chartRef.current = chart

    const ro = new ResizeObserver(() => {
      if (!containerRef.current || !chartRef.current) return
      chartRef.current.applyOptions({ width: containerRef.current.clientWidth })
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chartRef.current = null   // clear ref BEFORE remove() so ResizeObserver guard fires
      chart.remove()
      seriesRef.current = {}
    }
  }, [])

  // Update data when query result changes
  useEffect(() => {
    if (!data || !chartRef.current) return

    const sentimentData: LineData[] = data.series
      .filter((p) => p.sentiment_price !== null)
      .map((p) => ({ time: toTimestamp(p.time as unknown as string) as any, value: p.sentiment_price! }))

    const realData: LineData[] = data.series
      .filter((p) => p.real_price !== null)
      .map((p) => ({ time: toTimestamp(p.time as unknown as string) as any, value: p.real_price! }))

    seriesRef.current['sentiment']?.setData(sentimentData)
    seriesRef.current['real']?.setData(realData)

    // Remove old scenario series
    Object.keys(seriesRef.current)
      .filter((k) => k.startsWith('scenario:'))
      .forEach((k) => {
        chartRef.current!.removeSeries(seriesRef.current[k])
        delete seriesRef.current[k]
      })

    // Add scenario overlay series
    if (data.scenario_series) {
      Object.entries(data.scenario_series).forEach(([slug, points]) => {
        const configIdx = configs.findIndex((c) => c.slug === slug)
        const color = scenarioColor(configIdx === -1 ? 0 : configIdx)
        const series = chartRef.current!.addLineSeries({
          color,
          lineWidth: 1,
          lineStyle: LineStyle.SparseDotted,
          title: configs.find((c) => c.slug === slug)?.name ?? slug,
        })
        const lineData: LineData[] = points.map((p) => ({
          time: toTimestamp(p.time as unknown as string) as any,
          value: p.sentiment_price,
        }))
        series.setData(lineData)
        seriesRef.current[`scenario:${slug}`] = series
      })
    }

    chartRef.current.timeScale().fitContent()
  }, [data, configs])

  return (
    <div className="relative">
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-800/80 rounded-lg z-10">
          <span className="text-slate-400 text-sm">Loading chart…</span>
        </div>
      )}
      <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />
    </div>
  )
}

import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/lib/queryKeys'
import { useSSE } from './useSSE'

/**
 * Opens a per-ticker SSE connection and invalidates the market overview
 * and ticker history queries whenever a price_update event arrives.
 *
 * V1: SSE events trigger query invalidation -> full refetch -> setData().
 * Future: parse event payload and use series.update() for zero-latency append.
 */
export function useTickerSSE(ticker: string): void {
  const qc = useQueryClient()
  const url = `${import.meta.env.VITE_API_BASE_URL || ''}/api/v1/tickers/${ticker}/stream`

  const onMessage = useCallback(
    (_e: MessageEvent) => {
      qc.invalidateQueries({ queryKey: queryKeys.market.overview() })
      qc.invalidateQueries({ queryKey: ['ticker', ticker, 'history'] })
    },
    [qc, ticker],
  )

  useSSE({ url, onMessage, enabled: !!ticker })
}

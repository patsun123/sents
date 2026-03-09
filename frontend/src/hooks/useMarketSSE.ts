import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/lib/queryKeys'
import { TickerSummary } from '@/types/api'
import { useSSE } from './useSSE'

const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * Opens a global SSE connection and updates the market overview cache
 * whenever a price_update or data_refresh event arrives.
 */
export function useMarketSSE(): void {
  const qc = useQueryClient()

  const onMessage = useCallback(
    (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data)

        // Handle all_tickers_snapshot (initial burst)
        if (payload.tickers) {
          qc.setQueryData(queryKeys.market.overview(), (old: any) => {
            if (!old) return old
            const updates = new Map<string, Partial<TickerSummary>>(
              payload.tickers.map((t: any) => [t.ticker, t])
            )
            return {
              ...old,
              tickers: old.tickers.map((t: TickerSummary) =>
                updates.has(t.ticker) ? { ...t, ...updates.get(t.ticker) } : t
              ),
            }
          })
        }

        // Handle per-ticker price_update
        if (payload.ticker) {
          qc.setQueryData(queryKeys.market.overview(), (old: any) => {
            if (!old) return old
            return {
              ...old,
              tickers: old.tickers.map((t: TickerSummary) =>
                t.ticker === payload.ticker ? { ...t, ...payload } : t
              ),
            }
          })
        }
      } catch {
        // ignore malformed events
      }
    },
    [qc]
  )

  useSSE({ url: `${BASE}/api/v1/tickers/stream`, onMessage })
}

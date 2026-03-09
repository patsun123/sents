import { useEffect, useRef } from 'react'

interface SSEOptions {
  url: string
  onMessage: (event: MessageEvent) => void
  onError?: (event: Event) => void
  enabled?: boolean
}

/**
 * Connects to an SSE endpoint and calls onMessage for each event.
 * Automatically reconnects on connection loss.
 */
export function useSSE({ url, onMessage, onError, enabled = true }: SSEOptions): void {
  const onMessageRef = useRef(onMessage)
  const onErrorRef = useRef(onError)
  onMessageRef.current = onMessage
  onErrorRef.current = onError

  useEffect(() => {
    if (!enabled) return

    let es: EventSource | null = null
    let retryTimeout: ReturnType<typeof setTimeout> | null = null
    let retries = 0
    let cancelled = false
    const MAX_RETRIES = 10

    function connect() {
      if (cancelled) return
      es = new EventSource(url)

      es.onmessage = (e) => {
        retries = 0
        onMessageRef.current(e)
      }

      // Listen for named events too
      const namedEvents = ['price_update', 'all_tickers_snapshot', 'data_refresh']
      namedEvents.forEach((evt) => {
        es!.addEventListener(evt, (e) => {
          retries = 0
          onMessageRef.current(e as MessageEvent)
        })
      })

      es.onerror = (e) => {
        onErrorRef.current?.(e)
        es?.close()
        if (retries < MAX_RETRIES) {
          const delay = Math.min(1000 * 2 ** retries, 30_000)
          retries++
          retryTimeout = setTimeout(connect, delay)
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      retryTimeout && clearTimeout(retryTimeout)
      es?.close()
    }
  }, [url, enabled])
}

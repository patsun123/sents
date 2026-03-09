// Staleness thresholds (matches sse_common constants)
export type StalenessLevel = 'fresh' | 'warning' | 'critical' | 'unavailable'

// Ticker summary for the market overview table
export interface TickerSummary {
  ticker: string
  sentiment_price: number | null
  real_price: number | null
  sentiment_delta: number
  staleness: StalenessLevel
  last_updated: string // ISO 8601
  mention_count_24h: number
}

// Pricing configuration (from pricing_configurations table)
export interface PricingConfig {
  id: string // UUID
  slug: string
  name: string
  description: string
  params: Record<string, number | string>
}

// A single data point in a scenario overlay series
export interface ScenarioDataPoint {
  time: string // ISO 8601
  sentiment_price: number
}

// History response for ticker detail chart
export interface HistoryResponse {
  ticker: string
  interval: '1d' | '1w' | '1m'
  shift_applied: number
  shift_unit: string
  generated_at: string
  series: Array<{
    time: string
    sentiment_price: number | null
    real_price: number | null
    sentiment_delta: number
  }>
  // Present only when ?configs= query param is used
  scenario_series?: Record<string, ScenarioDataPoint[]>
}

// Market overview (list endpoint)
export interface MarketOverviewResponse {
  tickers: TickerSummary[]
  generated_at: string
}

// Pricing configs list endpoint
export interface PricingConfigsResponse {
  configs: PricingConfig[]
}

// Staleness info for a ticker
export interface StalenessInfo {
  ticker: string
  staleness: StalenessLevel
  last_updated: string | null
  minutes_since_update: number | null
}

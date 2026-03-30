# Design Spec — V1 Gap Closure

**Author:** Galadriel (UI/UX Designer)
**Date:** 2026-03-30
**Status:** APPROVED
**Scope:** REQ-08 (Frontend Chart Components) — the only requirement with a user-facing design surface

---

## 1. Design Context

### Current State
The frontend has two views, managed by `useState` (no router):

1. **Market Overview** — a full-width table showing all tickers with columns: Ticker, Sentiment $, Real $, Delta, Mentions/24h, Status. Clicking a row opens the detail panel.
2. **Ticker Detail** — a panel above the table with a `lightweight-charts` line chart (sentiment price vs real price), timeframe selector (1d/1w/1m), shift control, and scenario selector (overlay up to 3 pricing configs).

### Design System
- Dark theme: `slate-900` background, `slate-800` surfaces, `slate-700` borders
- Tailwind CSS utility classes throughout
- Font: system default (Tailwind's sans stack)
- Monospace for prices (`font-mono`)
- Color coding: emerald for positive, red for negative, blue for sentiment, slate for real price
- `clsx` for conditional classes
- `lightweight-charts` (TradingView) for charting

### What's Missing (from REQ-08)
1. **SparklineChart** — inline mini-chart in the market overview table
2. **DivergenceGauge** — visual indicator of gap between real and sentiment price
3. **Per-ticker price history chart** — already exists (`TickerChart.tsx`) but needs SSE live updates
4. **Scenario comparison** — already exists (scenario overlay on `TickerChart`)

---

## 2. Component Designs

### 2.1 SparklineChart

**Purpose:** Tiny inline chart in the market overview table showing recent price movement at a glance.

**Placement:** New column in `MarketTable` between "Delta" and "Mentions/24h".

**Specifications:**
- Width: 80px, Height: 32px
- Renders the last 24 data points (or whatever the market overview API provides)
- Single line — sentiment price only
- Line color: follows delta sign (emerald if positive trend, red if negative)
- No axes, no labels, no grid, no tooltip — pure visual trend indicator
- Area fill beneath the line at 10% opacity of line color
- Rounded container with no border

**Data Source:** Requires a `sparkline` field on `TickerSummary` — an array of recent sentiment prices. This is a new API field the backend must provide (coordinate with System Architect).

**Component Interface:**
```tsx
interface SparklineChartProps {
  data: number[]        // recent sentiment prices (last 24 points)
  trend: 'up' | 'down'  // determines color
  width?: number         // default 80
  height?: number        // default 32
}
```

**Rendering Approach:** Use a `<canvas>` element for performance (many sparklines rendered simultaneously in the table). Do NOT use `lightweight-charts` for sparklines — too heavy for inline use.

### 2.2 DivergenceGauge

**Purpose:** Visual indicator showing the magnitude and direction of the gap between real price and sentiment price.

**Placement:** Two locations:
1. **Market table:** New column after Sparkline, replacing the current "Delta" text column with a visual gauge + text
2. **Ticker detail header:** Displayed next to the ticker name

**Specifications:**
- Width: 120px (table), 160px (detail header)
- Horizontal bar gauge with center line representing zero divergence
- Bar extends left (red) for negative divergence, right (emerald) for positive
- Bar length proportional to divergence percentage: `(sentiment_price - real_price) / real_price * 100`
- Max bar extent at +/-10% (anything beyond clips to full bar)
- Numeric label showing the percentage: e.g., "+2.4%" or "-1.8%"
- Background: `slate-700` track, colored fill

**Component Interface:**
```tsx
interface DivergenceGaugeProps {
  sentimentPrice: number | null
  realPrice: number | null
  size?: 'sm' | 'md'    // sm = table, md = detail header
}
```

**States:**
- Normal: colored bar + percentage label
- No data: gray track with "—" label (when either price is null)

### 2.3 TickerChart Enhancements (Existing Component)

The `TickerChart` component already works. Two enhancements needed:

#### 2.3.1 SSE Live Updates
- When new data arrives via the existing `useTickerSSE` hook, append the new data point to the chart in real-time
- New points should appear smoothly (lightweight-charts handles this natively via `update()`)
- No full re-render — incremental update only

#### 2.3.2 Chart Legend Improvements
- Add a legend below the chart showing all active series with their colors
- Legend items: "Sentiment $" (blue solid), "Real $" (slate dashed), and any active scenario names with their colors
- Legend should be a simple flex row of color-dot + label pairs

**Component Interface (legend):**
```tsx
interface ChartLegendProps {
  items: Array<{
    label: string
    color: string
    style: 'solid' | 'dashed' | 'dotted'
  }>
}
```

---

## 3. Layout Changes

### 3.1 Market Overview Table — Updated Columns

```
| Ticker | Sentiment $ | Real $ | Divergence | Sparkline | Mentions/24h | Status |
```

Changes from current:
- **Delta column → Divergence column:** Replace the text-only DeltaCell with the DivergenceGauge component (sm size). The numeric delta value is embedded in the gauge.
- **New Sparkline column:** Inserted between Divergence and Mentions/24h.
- Column widths: Ticker (auto), Sentiment $ (100px), Real $ (100px), Divergence (140px), Sparkline (96px), Mentions/24h (100px), Status (80px)

### 3.2 Ticker Detail — Updated Header

```
┌─────────────────────────────────────────────────────────────────┐
│  AAPL     [DivergenceGauge md]     [Timeframe] [Shift] [×]     │
│                                     Compare: [scenario pills]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                     [TickerChart - 360px tall]                   │
│                                                                 │
│  ● Sentiment $   ○ Real $   ◇ balanced   ◇ upvote-heavy        │
└─────────────────────────────────────────────────────────────────┘
```

Changes from current:
- DivergenceGauge (md) added next to ticker name in header
- Chart legend row added below the chart

---

## 4. Interaction Patterns

### 4.1 Sparkline Hover
- No tooltip on sparkline in the table (keep it minimal)
- Clicking the row still opens the ticker detail (existing behavior)

### 4.2 DivergenceGauge
- Static display, no interaction
- Updates in real-time when SSE delivers new prices

### 4.3 Chart Live Updates
- When SSE delivers a new price, the chart appends the point without resetting the view
- If the user has scrolled/zoomed the chart, live updates should NOT force the view back to "fit all" — respect user's current viewport
- If the user is viewing the latest data (not scrolled back), new points should auto-scroll into view

---

## 5. Visual Reference

### Color Palette (Unchanged)
| Token | Color | Usage |
|-------|-------|-------|
| `emerald-400` | #34d399 | Positive delta, positive divergence, bullish trend |
| `red-400` | #f87171 | Negative delta, negative divergence, bearish trend |
| `blue-500` | #3b82f6 | Sentiment price line |
| `slate-400` | #94a3b8 | Real price line, secondary text |
| `slate-700` | #334155 | Gauge tracks, chart grid |
| `slate-800` | #1e293b | Surface backgrounds |

### Typography (Unchanged)
- Prices: `font-mono text-sm`
- Labels: `text-xs text-slate-500 uppercase tracking-wider`
- Headings: `text-sm font-semibold text-slate-200`

---

## 6. API Data Requirements

The following new data is needed from the backend to support these components:

1. **`sparkline` field on `TickerSummary`:** Array of up to 24 recent sentiment prices for each ticker. Added to the `/api/v1/market/overview` response.

2. **No other new endpoints needed.** All other data (prices, deltas, scenarios) is already available via existing endpoints.

---

## 7. Out of Scope (Per Requirements)

- React Router / URL navigation (NH-05)
- Price flash animation (NH-06)
- Accessibility enhancements (deferred)
- Mobile responsiveness (deferred)
- Ticker card grid layout (mockup shows cards, but stakeholder said "build on top of what we have" — keeping table layout)

---

## Sign-Off

- [x] Product Manager (Aragorn) — approved 2026-03-30
- [x] Stakeholder (User) — approved 2026-03-30

# UI Design Specification — Sentiment Stock Exchange

## Design Philosophy

Inspired by **Robinhood** (clean, data-forward, minimal chrome) and **Bloomberg Terminal** (density, information hierarchy). Dark background keeps focus on price data. Color is used sparingly and semantically — green means up/positive sentiment, red means down/negative sentiment, never decorative.

**Guiding principles:**
- Price numbers are the hero element on every screen — they must be immediately readable
- Real-time updates should feel alive without being distracting (smooth transitions, not flash-and-flash)
- Data staleness is always visible — users should never wonder if they're seeing live or stale data
- Mobile-first — a trader checking positions on their phone is a first-class user

---

## Design Tokens

### Color Palette

```
Background layer   #0f1419   ← page background (near-black with blue tint)
Surface layer      #1a2332   ← cards, panels
Surface raised     #222d3e   ← hover states, dropdowns
Border             #2d3748   ← card borders, dividers

Text primary       #e2e8f0   ← main content
Text secondary     #94a3b8   ← labels, metadata
Text muted         #4a5568   ← disabled, placeholders

Positive (up)      #10b981   ← green (emerald-500)
Positive dim       #064e3b   ← green background tint
Negative (down)    #ef4444   ← red (red-500)
Negative dim       #7f1d1d   ← red background tint
Neutral            #94a3b8   ← flat / no change

Warning            #f59e0b   ← staleness warning (amber-500)
Critical           #ef4444   ← staleness critical (same as negative red)
Offline            #6b7280   ← gray-500

Accent blue        #3b82f6   ← interactive elements, active states
Accent blue dim    #1e3a5f   ← active button backgrounds
```

### Typography

```
Font stack:  "Inter", "SF Pro Display", system-ui, sans-serif
Mono stack:  "JetBrains Mono", "SF Mono", ui-monospace, monospace

Price values:  font-variant-numeric: tabular-nums  ← prevents layout shift as digits change
Ticker symbols: font-family: mono, font-weight: 700
```

| Role | Size | Weight | Color |
|---|---|---|---|
| Ticker symbol (card) | 20px / 1.25rem | 700 bold | text-primary |
| Ticker symbol (detail hero) | 40px / 2.5rem | 800 | text-primary |
| Price (large) | 28px / 1.75rem | 600 | contextual green/red |
| Price (card) | 18px / 1.125rem | 500 | contextual |
| Label | 11px / 0.6875rem | 500 | text-secondary, uppercase, letter-spacing 0.08em |
| Body | 14px / 0.875rem | 400 | text-primary |
| Caption | 12px / 0.75rem | 400 | text-muted |

### Spacing

4px grid. Key values: `4 8 12 16 20 24 32 48 64px`

### Border Radius

Cards: `12px` | Buttons: `8px` | Badges: `full (9999px)` | Inputs: `6px`

---

## Page 1: Homepage

### Layout (desktop 1280px)

```
┌─────────────────────────────────────────────────────────────────────┐
│  HEADER                                                             │
│  ┌───────────────────────────────────────────┐  ┌────────────────┐ │
│  │  📈  Sentiment Stock Exchange              │  │ ● Market Open  │ │
│  │      sentiment-driven prices, 24/7         │  │  3h 42m left   │ │
│  └───────────────────────────────────────────┘  │ ✓ Live  0:32   │ │
│                                                  └────────────────┘ │
├─────────────────────────────────────────────────────────────────────┤
│  TICKER GRID  (3 columns)                                           │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│  │  TSLA          ↑ │  │  NVDA          ↑ │  │  GME           ↓ │ │
│  │                  │  │                  │  │                  │ │
│  │  Market   $245.80│  │  Market   $875.22│  │  Market    $18.44│ │
│  │  Sentiment$251.40│  │  Sentiment$901.55│  │  Sentiment $15.90│ │
│  │                  │  │                  │  │                  │ │
│  │  ▲ +$5.60 +2.3%  │  │  ▲ +$26.33+3.0% │  │  ▼ -$2.54 -13.8%│ │
│  │  ▁▂▃▄▅▆▇▇▆▆▇▇   │  │  ▁▁▂▃▄▅▆▇▇▇▇▇   │  │  ▇▆▅▄▃▂▂▁▁▁▂▂   │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘ │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│  │  PLTR          ↑ │  │  SOFI          → │  │  RIVN          ↓ │ │
│  │  ...             │  │  ...             │  │  ...             │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  FOOTER   Last pipeline run: 4 min ago · 6 tickers active           │
└─────────────────────────────────────────────────────────────────────┘
```

### Ticker Card — Detail

```
┌─────────────────────────────┐
│  TSLA              ▲        │  ← direction arrow, green or red
│                             │
│  Market Price               │  ← label: 11px uppercase muted
│  $245.80                    │  ← 18px tabular-nums
│                             │
│  Sentiment Price            │
│  $251.40                    │  ← green because > market
│                             │
│  ▲ +$5.60  +2.28%          │  ← divergence: sign + dollar + pct
│                             │
│  ▁▂▃▄▅▆▇▇▆▆▇▇▇▇           │  ← sparkline (sentiment price, 24 pts)
└─────────────────────────────┘
  border: 1px solid #2d3748
  background: #1a2332
  hover: background #222d3e, border #3b82f6, cursor: pointer
  border-left: 3px solid #10b981 (green) or #ef4444 (red) — sentiment direction
```

**Live update animation:** When a `price_update` SSE event arrives, the updated price briefly `flash`es — background tint pulses from `#064e3b` (green flash) or `#7f1d1d` (red flash) back to `#1a2332` over 800ms. The direction arrow may flip and animate a 180° rotation.

### Mobile Layout (375px)

```
┌─────────────────────────┐
│ 📈 SSE         ● Open  │  ← abbreviated header
├─────────────────────────┤
│  TSLA               ▲  │
│  Market:   $245.80      │
│  Sentiment:$251.40      │  ← single column, full-width cards
│  ▲ +$5.60 +2.28%       │
│  ▁▂▃▄▅▆▇▇▆▆▇▇▇▇       │
├─────────────────────────┤
│  NVDA               ▲  │
│  ...                    │
└─────────────────────────┘
```

---

## Page 2: Ticker Detail

### Layout (desktop)

```
┌─────────────────────────────────────────────────────────────────────┐
│  HEADER                                                             │
│  ← Back    TSLA  Tesla, Inc.            ● Market Open  ✓ Live      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐│
│  │  MARKET PRICE            │  │  SENTIMENT PRICE                 ││
│  │  $245.80                 │  │  $251.40                         ││
│  │  ▲ +$3.20 +1.32% today  │  │  ▲ +$5.60 vs market             ││
│  │  Updates during NYSE hrs │  │  Updates 24/7                    ││
│  └──────────────────────────┘  └──────────────────────────────────┘│
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  DIVERGENCE                                                     ││
│  │                                                                 ││
│  │  Sentiment is  ▲ +$5.60  (+2.28%)  ABOVE market               ││
│  │                                                                 ││
│  │  Market  ───────────────┤                    ├─── Sentiment   ││
│  │  $245.80               gap = $5.60           $251.40          ││
│  │          ◄──────────────── 2.28% ────────────────►            ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │  Compare: [○ Upvote-Heavy] [○ Volume-Heavy] [○ Momentum]      ││
│  │  [  1D  ] [  1W  ] [  1M  ]   Sentiment shift: [−] 0 [+] hrs ││
│  │                                                                 ││
│  │  $270 ─────────────────────────────────────────────────────    ││
│  │  $260 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─●─ ─ ─ ─ ─ (sentiment)     ││
│  │  $250 ──────────────────────────────●───────── (market)       ││
│  │  $240 ─────────────────────────────────────────────────────    ││
│  │  $230 ─────────────────────────────────────────────────────    ││
│  │       9am  10am  11am  12pm   1pm   2pm   3pm   4pm            ││
│  │                                                                 ││
│  │  ── Market Price    - - Sentiment Price                        ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                     │
│  FOOTER: Last updated 2 min ago (fresh) · 847 posts analyzed       │
└─────────────────────────────────────────────────────────────────────┘
```

### Dual Price Display — Component Detail

```
┌──────────────────────────────┐   ┌──────────────────────────────┐
│  MARKET PRICE                │   │  SENTIMENT PRICE             │
│                              │   │                              │
│  $245.80                     │   │  $251.40                     │
│   text: #e2e8f0 (neutral)    │   │   text: #10b981 (green)      │
│                              │   │    because > market price     │
│  ▲ +$3.20   +1.32%           │   │  ▲ +$5.60 vs market          │
│   green, 14px                │   │   green, 14px                │
│                              │   │                              │
│  Updates during NYSE hours   │   │  Updates 24/7                │
│   text-muted, 12px italic    │   │   text-muted, 12px italic    │
└──────────────────────────────┘   └──────────────────────────────┘

Background: #1a2332
Border: 1px solid #2d3748
Left accent bar: 3px solid (neutral gray for market, green/red for sentiment)
```

### Divergence Gauge — Component Detail

The gauge is a horizontal bar showing the gap between the two prices visually.

```
Sentiment > Market (bull case):

  Market                        Sentiment
  $245.80                       $251.40
    │                              │
    ├──────────────────────────────┤
    ◄── baseline ──────── +2.28% ──►

  Left half: gray (market side)
  Right half: green fill (sentiment premium)
  Center tick: vertical line at "fair value" (where prices would be equal)
  Label above: "Sentiment Premium: +$5.60 (+2.28%)"

Sentiment < Market (bear case):

  Sentiment                     Market
  $238.20                       $245.80
    │                              │
    ├──────────────────────────────┤
    ◄── -3.12% ──────── baseline ──►

  Left half: red fill (sentiment discount)
  Right half: gray (market side)
  Label above: "Sentiment Discount: -$7.60 (-3.12%)"
```

### Chart — TradingView Lightweight Charts Config

```
Two LineSeries on a shared chart (base configuration):

Series 1 — Market Price:
  color: #94a3b8  (slate-400, neutral gray)
  lineWidth: 2
  lineStyle: solid
  title: "Market"

Series 2 — Sentiment Price (primary algorithm):
  color: #10b981  (if sentiment > market at last point)
         #ef4444  (if sentiment < market at last point)
  lineWidth: 2
  lineStyle: dashed (style: 1)
  title: "Sentiment"

Chart options:
  background: { type: 'solid', color: '#1a2332' }
  textColor: '#94a3b8'
  grid: { vertLines: { color: '#2d3748' }, horzLines: { color: '#2d3748' } }
  crosshair: { mode: CrosshairMode.Normal }
  rightPriceScale: { borderColor: '#2d3748' }
  timeScale: { borderColor: '#2d3748', timeVisible: true }

Tooltip (custom overlay on crosshair):
  ┌─────────────────────────┐
  │  2:34 PM                │
  │  Market:    $244.50     │
  │  Sentiment: $249.10     │
  │  Gap:     ▲ +$4.60     │
  └─────────────────────────┘
  background: #222d3e
  border: 1px solid #3b82f6
  border-radius: 8px
  padding: 8px 12px
```

---

## Component: Scenario Selector

Appears above the chart on the Ticker Detail page. Controls which additional pricing formula "concoctions" are overlaid on the chart. Each scenario is a named configuration of weighting parameters (upvote weight, volume weight, sensitivity, etc.) stored in `pricing_configurations` (TASK-BE41). Users toggle scenarios to compare how different formulas would have priced the same ticker over time.

### Scenario Color Palette (index-assigned, not slug-hardcoded)

Colors are assigned sequentially from a fixed palette — independent of the scenario's name, so adding new configs in the DB automatically gets the next color without code changes:
```
Slot 0:  #3b82f6   blue-500
Slot 1:  #a855f7   purple-500
Slot 2:  #f59e0b   amber-500
```
The primary/live sentiment line is always `#10b981` (green) or `#ef4444` (red) and is not part of this palette.

### Wireframe

```
Desktop:
┌─────────────────────────────────────────────────────────────────────┐
│  Compare:                                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  ○ Upvote-Heavy  │  │  ○ Volume-Heavy  │  │  ○ Momentum      │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

● = toggled on (button tinted with its assigned slot color)
○ = toggled off (gray dot, transparent background)
```

### Button States

```
Inactive (default):
  background: transparent
  border: 1px solid #2d3748
  text: #94a3b8
  dot: #4a5568 (gray)

Active (toggled on) — color comes from SCENARIO_PALETTE[slot_index]:
  background: dim version of slot color (e.g. #1e3a5f for blue)
  border: 1px solid {slot_color}
  text: {slot_color}
  dot: {slot_color} (solid)

Hidden when API returns no configs: entire selector row not rendered
```

### Updated Chart with Scenarios Active

```
┌─────────────────────────────────────────────────────────────────────┐
│  Compare: [○ Upvote-Heavy] [● Volume-Heavy] [○ Momentum]           │
│  [  1D  ] [  1W  ] [  1M  ]                  Shift: [−] 0 [+] hrs  │
│                                                                     │
│  $270 ─────────────────────────────────────────────────────────    │
│  $252 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─●─ ─ ─ ─ (Volume-Heavy, blue) │
│  $249 - - - - - - - - - - - - - - -●- - - - - (live config, green) │
│  $245 ──────────────────────────────●───────── (market, gray)      │
│       9am  10am  11am  12pm   1pm   2pm   3pm   4pm                │
│                                                                     │
│  Legend:  ── Market  - - Sentiment  ─ ─ Volume-Heavy               │
└─────────────────────────────────────────────────────────────────────┘

Scenario overlay line specs:
  lineStyle: dashed (style: 1)
  lineWidth: 1.5  (thinner than primary 2px to preserve visual hierarchy)
  priceLineVisible: false
```

### Updated Tooltip with Scenarios Active

```
┌──────────────────────────────────┐
│  2:34 PM                         │
│  Market:          $244.50        │
│  Sentiment:       $249.10        │  ← primary/live config (always shown)
│  ──────────────────────────────  │
│  Volume-Heavy:    $252.30        │  ← scenario price (slot color: blue)
└──────────────────────────────────┘
background: #222d3e
border: 1px solid #3b82f6
Scenario rows rendered in their assigned slot color
```

---

## Component: Time-Shift Control

Appears on the same row as the timeframe selector, right-aligned. Controls an integer offset applied to all sentiment data on the chart.

### Wireframe

```
┌───────────────────────────────────────────────────────────────────┐
│  [  1D  ] [  1W  ] [  1M  ]          Sentiment shift: [−] 3 [+] hours  [↺]  │
└───────────────────────────────────────────────────────────────────┘

Mobile (stacks below timeframe row):
┌─────────────────────────┐
│  [1D]  [1W]  [1M]       │
│  Shift: [−] 3 [+] hrs ↺ │
└─────────────────────────┘
```

### Control Anatomy

```
Label: "Sentiment shift:"     color: #94a3b8, 12px
  [−]  decrement button:      16×32px, border: 1px solid #2d3748
  [ 3] value input:           40px wide, text-center, tabular-nums
  [+]  increment button:      16×32px, border: 1px solid #2d3748
  "hours" / "days" label:     12px, #94a3b8, derived from active timeframe
  [↺]  reset button:          16px icon, hidden when shift = 0

Button border-radius: 4px (left side rounded on −, right side rounded on +, forming a pill group)
```

### Shift Ranges per Timeframe

| Timeframe | Unit  | Min | Max | Example label       |
|-----------|-------|-----|-----|---------------------|
| 1D        | hours |  0  |  23 | "Shift: [−] 3 [+] hours" |
| 1W        | days  |  0  |   6 | "Shift: [−] 1 [+] days"  |
| 1M        | days  |  0  |  29 | "Shift: [−] 5 [+] days"  |

### Shift Annotation on Chart

When shift > 0, a banner appears directly above the chart:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚡ Sentiment shifted +3 hours  (showing what sentiment looked like │
│     3h before each price point)                                     │
└─────────────────────────────────────────────────────────────────────┘
background: #451a03 (amber dim)
border: 1px solid #f59e0b
border-radius: 6px
text: #f59e0b, 12px
icon: ⚡ or clock icon
padding: 6px 12px
```

### Button States for [−] and [+]

```
Default:  border: 1px solid #2d3748, text: #94a3b8, background: transparent
Hover:    border: 1px solid #4a5568, text: #e2e8f0, background: #222d3e
Disabled: opacity: 0.3, cursor: not-allowed
  (− disabled at shift=0; + disabled at shift=max for active timeframe)
```

### Mobile Detail Layout (375px)

```
┌─────────────────────────┐
│ ← Back  TSLA    ✓ Live │
├─────────────────────────┤
│  MARKET        SENTIMENT│
│  $245.80       $251.40  │  ← side by side, smaller text
│  ▲ +1.32%      ▲ +2.28%│
├─────────────────────────┤
│  ▲ Sentiment +$5.60    │
│  ████████████░░░░░░░░░░ │  ← divergence bar, full width
├─────────────────────────┤
│  [1D]  [1W]  [1M]      │
│  ┌─────────────────────┐│
│  │    [chart]          ││  ← full width, 200px tall on mobile
│  └─────────────────────┘│
├─────────────────────────┤
│  Updated 2 min ago ✓   │
└─────────────────────────┘
```

---

## Component: Header

```
Desktop (1280px):
┌─────────────────────────────────────────────────────────────────────┐
│  [📈 icon]  Sentiment Stock Exchange          [Market: ● Open 3h42m]│
│             sentiment-driven prices, 24/7     [✓ Live  Updated 0:32]│
└─────────────────────────────────────────────────────────────────────┘
  background: #0f1419
  border-bottom: 1px solid #2d3748
  height: 64px
  padding: 0 24px

Mobile (375px):
┌─────────────────────────┐
│ 📈 SSE        ● ✓ 0:32 │
└─────────────────────────┘
  height: 52px
  padding: 0 16px
  Abbreviated: "SSE" instead of full title
```

### Staleness Badge (in header)

```
States:

  Fresh (< 30 min):
  ┌──────────────────┐
  │ ✓ Live  2m ago   │   background: #064e3b, text: #10b981, border: #10b981
  └──────────────────┘

  Warning (30–60 min):
  ┌──────────────────┐
  │ ⚠ Delayed 35m   │   background: #451a03, text: #f59e0b, border: #f59e0b
  └──────────────────┘

  Critical (60min–4hr):
  ┌──────────────────┐
  │ ✕ Stale 1h 20m  │   background: #7f1d1d, text: #ef4444, border: #ef4444
  └──────────────────┘

  Unavailable (> 4hr):
  ┌──────────────────┐
  │ ✕ Offline        │   background: #1f2937, text: #6b7280, border: #4b5563
  └──────────────────┘

  All badges: border-radius: 9999px, padding: 4px 12px, font-size: 12px, font-weight: 600
```

---

## Component: Market Hours Indicator

```
Market Open:
  ● Open · Closes in 3h 42m
  dot: #10b981 (pulsing animation, 2s ease-in-out, opacity 1→0.4→1)

Market Closed:
  ○ Closed · Opens Mon 9:30 AM ET
  dot: #4b5563 (static, no pulse)

Weekend:
  ○ Closed · Opens Mon 9:30 AM ET

Font: 12px, text-secondary
```

---

## Interaction States

### Price Update Flash Animation

When an SSE `price_update` arrives and a price changes:

```css
@keyframes priceFlashUp {
  0%   { background-color: #1a2332; }
  20%  { background-color: #064e3b; }  /* green flash */
  100% { background-color: #1a2332; }
}

@keyframes priceFlashDown {
  0%   { background-color: #1a2332; }
  20%  { background-color: #7f1d1d; }  /* red flash */
  100% { background-color: #1a2332; }
}

/* applied via JS class add/remove */
.flash-up   { animation: priceFlashUp   0.8s ease-out; }
.flash-down { animation: priceFlashDown 0.8s ease-out; }
```

Direction arrow flip: `transform: rotateX(180deg)` with `transition: transform 0.3s ease`

### Timeframe Button States

```
Default:   background: transparent, text: #94a3b8, border: 1px solid #2d3748
Hover:     background: #222d3e,     text: #e2e8f0, border: 1px solid #4a5568
Active:    background: #1e3a5f,     text: #3b82f6, border: 1px solid #3b82f6
Focus:     outline: 2px solid #3b82f6, outline-offset: 2px
```

### Ticker Card Hover

```
Default: border: 1px solid #2d3748, background: #1a2332, shadow: none
Hover:   border: 1px solid #3b82f6, background: #222d3e, shadow: 0 4px 20px rgba(59,130,246,0.15)
         cursor: pointer
         transition: all 0.15s ease
```

---

## Loading States

### Ticker Card Skeleton

```
┌──────────────────────────────┐
│  ████████          ▓▓▓▓▓▓▓▓ │  ← shimmer animation
│                              │
│  ████████████████████        │
│  ████████████████████████    │
│                              │
│  ████████   ████████         │
│  ██████████████████████████  │
└──────────────────────────────┘

Shimmer: background gradient sliding left→right
  from: #1a2332  via: #222d3e  to: #1a2332
  animation: 1.5s infinite linear
```

### Chart Loading

```
┌──────────────────────────────────────────────────┐
│                                                  │
│           Loading chart data...                  │
│              [spinner]                           │
│                                                  │
└──────────────────────────────────────────────────┘
  Center-aligned spinner, text-secondary, 14px
  Spinner: 24px border-2 border-t-blue-500 rounded-full animate-spin
```

---

## Error States

```
API error (full page):
┌────────────────────────────────────┐
│                                    │
│    ⚠  Unable to load prices        │
│    Connection to server failed.    │
│                                    │
│    [  Try Again  ]                 │
│                                    │
└────────────────────────────────────┘
  Icon: amber-500
  Button: solid blue, 44px height minimum

Individual card error (inline):
┌──────────────────────────────┐
│  TSLA                ⚠       │
│  Data unavailable            │
│  [Retry]                     │
└──────────────────────────────┘
```

---

## Accessibility Requirements

| Requirement | Implementation |
|---|---|
| Color is never the only signal | Direction: ▲/▼ arrows + text ("up"/"down") + color |
| Staleness: icons + text + color | "✓ Live", "⚠ Delayed", "✕ Offline" |
| Price change: aria-live | `<span aria-live="polite">` wraps price values — screen reader announces updates |
| Focus indicator | `outline: 2px solid #3b82f6; outline-offset: 2px` on all interactive elements |
| Touch targets | Minimum 44×44px on all buttons, cards, and links |
| Chart accessibility | `<div role="img" aria-label="Price chart for TSLA showing market and sentiment prices over 1D">` |
| Keyboard navigation | Tab through cards → Enter to navigate, Esc to go back |

---

## File Structure

```
frontend/src/
  components/
    TickerCard.tsx          ← card with sparkline, prices, direction
    SparklineChart.tsx      ← lightweight sparkline (no axes)
    DualPriceDisplay.tsx    ← side-by-side market/sentiment prices
    DivergenceGauge.tsx     ← horizontal bar gauge
    PriceChart.tsx          ← TradingView wrapper (market + sentiment + algorithm overlays)
    TimeframeSelector.tsx   ← 1D/1W/1M button group
    ScenarioSelector.tsx    ← toggle buttons for pricing config overlays (fetched from API)
    TimeShiftControl.tsx    ← [−] N [+] unit input for sentiment lag exploration
    StalenessIndicator.tsx  ← badge with color-coded staleness level
    MarketHoursIndicator.tsx← open/closed dot + time
    SkeletonCard.tsx        ← loading shimmer for TickerCard
    PriceValue.tsx          ← animated price span (flash on change)
  pages/
    HomePage.tsx
    TickerDetailPage.tsx
    NotFoundPage.tsx
  hooks/
    useSSEPrices.ts         ← global SSE → setQueryData
    useTickerSSE.ts         ← per-ticker SSE for detail page
    useMarketHours.ts       ← is NYSE currently open?
  lib/
    queryKeys.ts            ← TICKERS_QUERY_KEY, tickerDetailKey, tickerHistoryKey
    api.ts                  ← fetchTickers, fetchTicker, fetchHistory (with algorithms + shift params)
    scenarioColors.ts       ← SCENARIO_PALETTE: string[], scenarioColor(index): string
  types/
    api.ts                  ← TickerSummary, TickerListResponse, SSEPriceUpdateEvent,
                               PricingConfig, ScenarioDataPoint, HistoryResponse
    index.ts                ← re-exports
  utils/
    formatPrice.ts          ← $1,234.50 formatting
    formatDivergence.ts     ← +$5.60 / -$3.20 formatting
    calcDivergencePct.ts    ← (sentiment - market) / market * 100
    parseStalenessLevel.ts  ← StalenessLevel → { color, label, icon }
    parseSSEEvent.ts        ← raw string → SSEPriceUpdateEvent | null
    shiftRange.ts           ← getShiftMax(timeframe): number, getShiftUnit(timeframe): string
  styles/
    globals.css             ← Tailwind directives + CSS variables
```

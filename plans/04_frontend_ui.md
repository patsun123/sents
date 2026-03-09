# Frontend / UI — Atomic Implementation Plan

## Domain: Frontend (React + Tailwind CSS + TradingView)

---

### TASK-FE01: Initialize React project with Vite and Tailwind CSS
**Domain:** Frontend
**Depends on:** none
**Description:** Set up a new React 18 project using Vite as the build tool and install Tailwind CSS with PostCSS. Configure the project structure with `src/components`, `src/pages`, `src/hooks`, `src/types`, `src/lib`, and `src/utils` directories.

**Dependencies to install:**
- `@tanstack/react-query` — server state management and SSE cache integration (see TASK-FE24)
- `react-router-dom` v6+
- `tailwindcss`, `postcss`, `autoprefixer`
- `lightweight-charts` (TradingView)

**Acceptance criteria:**
- Vite dev server starts without errors (`npm run dev`)
- Tailwind classes are recognized and compile correctly
- ES modules working for imports/exports
- Hot module reloading (HMR) functional
- Build process produces optimized output (`npm run build`)
- `src/lib/queryKeys.ts` exists and exports `TICKERS_QUERY_KEY = ['tickers'] as const`

---

### TASK-FE02: Implement dark theme design system
**Domain:** Frontend
**Depends on:** TASK-FE01
**Description:** Create Tailwind configuration with custom color palette (dark background #0f1419, green #10b981, red #ef4444, neutral grays). Export theme tokens as CSS variables and create utility classes for consistent styling across components.
**Acceptance criteria:**
- Tailwind config supports dark theme colors globally
- CSS variables defined for all brand colors
- Semantic color classes (text-positive, bg-negative, border-neutral)
- Theme colors work in all components without additional configuration
- Color contrast meets WCAG AA accessibility standards

---

### TASK-FE03: Configure TypeScript and shared type definitions
**Domain:** Frontend
**Depends on:** TASK-FE01
**Description:** Set up TypeScript with strict mode enabled. Create shared type definitions at `src/types/api.ts` for all API response shapes and SSE event types. These types are the single source of truth used by React Query (TASK-FE24) and the SSE hook (TASK-FE15).

**Types to define in `src/types/api.ts`:**
```typescript
export type StalenessLevel = "fresh" | "warning" | "critical" | "unavailable";

export type TickerSummary = {
  symbol: string;
  sentiment_price: number;
  real_price: number;
  divergence: number;
  staleness_level: StalenessLevel;
  timestamp: string;
};

export type TickerListResponse = { tickers: TickerSummary[] };

export type SSEPriceUpdateEvent = {
  type: "price_update";
  ticker: string;
  sentiment_price: number;
  real_price: number;
  divergence: number;
  timestamp: string;
};
```

**Acceptance criteria:**
- `tsconfig.json` configured with `strict: true`
- All `.ts` and `.tsx` files compile without errors
- Types file at `src/types/api.ts` defines all domain models above
- `src/types/index.ts` re-exports from `src/types/api.ts` for convenience
- No `any` types used except where explicitly needed

---

### TASK-FE04: Build layout and navigation structure with React Router
**Domain:** Frontend
**Depends on:** TASK-FE01, TASK-FE02
**Description:** Create a root Layout component with header/navigation bar and set up React Router with routes for HomePage (/), TickerDetailPage (/:ticker), and NotFound. Configure routing with proper error boundaries.
**Acceptance criteria:**
- React Router v6+ configured with BrowserRouter
- Navigation bar displays "Sentiment Stock Exchange" branding
- Routes navigate without full page reload
- URL updates reflect current page
- 404 page shows for invalid routes
- Layout persists across page navigation

---

### TASK-FE05: Build header and navigation component
**Domain:** Frontend
**Depends on:** TASK-FE04
**Description:** Build a professional header with logo, title, and navigation links. Include mobile hamburger menu with responsive behavior. Show staleness indicator badge on header when data is stale.
**Acceptance criteria:**
- Header responsive on mobile (hamburger) and desktop (inline nav)
- Staleness badge displays when data is outdated
- Click logo/title returns to homepage
- Navigation links work correctly
- Styling matches dark professional theme

---

### TASK-FE06: Create TickerCard component for homepage grid
**Domain:** Frontend
**Depends on:** TASK-FE02, TASK-FE03
**Description:** Build a reusable ticker card component showing: ticker symbol, real market price, sentiment price, mini sparkline, and sentiment direction indicator (up/down arrow). Card should be clickable to navigate to detail view.
**Acceptance criteria:**
- Displays ticker symbol, real price, sentiment price, direction indicator
- Prices color-coded green (up) or red (down) based on direction
- Mini sparkline shows price trend
- Card is clickable and navigates to /ticker/:symbol
- Hover state provides visual feedback
- Responsive on mobile (full width) and desktop (grid column)

---

### TASK-FE07: Build sparkline mini-chart component
**Domain:** Frontend
**Depends on:** TASK-FE02, TASK-FE03
**Description:** Create a lightweight sparkline component that renders a simple line chart (~50px height) showing price trend. Line color changes based on direction (green up, red down). No axes or labels — clean sparkline only.
**Acceptance criteria:**
- Renders quickly without performance issues
- Line color matches direction (green/red)
- No axes or labels
- Accepts array of price points as prop
- Properly scales data to fit dimensions
- Mobile-readable at small size

---

### TASK-FE08: Build HomePage with ticker grid layout
**Domain:** Frontend
**Depends on:** TASK-FE04, TASK-FE06, TASK-FE07
**Description:** Create the homepage displaying all tracked tickers in a responsive grid layout. Fetch ticker data from GET /api/v1/tickers and render TickerCard components. Show loading state while fetching.
**Acceptance criteria:**
- Fetches ticker data on mount from /api/v1/tickers
- Displays responsive grid of TickerCards (1 col mobile, 2–3 col desktop)
- Loading spinner shows while data fetches
- Error state with retry button if API fails
- "Sentiment Stock Exchange" title prominent at top
- Periodic polling fallback if SSE not yet connected

---

### TASK-FE09: Create TickerDetailPage layout structure
**Domain:** Frontend
**Depends on:** TASK-FE04, TASK-FE02
**Description:** Build the layout for the ticker detail page with sections for: header (ticker symbol), dual price display, timeframe selector (1D/1W/1M), chart container, and metadata footer. Fully responsive.
**Acceptance criteria:**
- Header shows ticker symbol prominently
- Dual price display area reserved
- Timeframe buttons (1D, 1W, 1M) render in a row
- Chart area flexible to fill available space
- Footer shows last update time and market hours info
- Mobile: full-width stacked layout
- Route params correctly extract ticker symbol

---

### TASK-FE10: Implement dual price display component
**Domain:** Frontend
**Depends on:** TASK-FE03, TASK-FE02
**Description:** Create a component showing two prices side-by-side: real market price and sentiment price. Each price shows: label, value formatted as currency, change percentage, and direction arrow. Clear visual distinction between the two.
**Acceptance criteria:**
- Two columns: "Market Price" and "Sentiment Price"
- Market price labeled clearly (updates during trading hours)
- Sentiment price labeled clearly (updates 24/7)
- Change percentage with +/- prefix and green/red color
- Price values formatted to 2 decimal places with $ prefix
- Responsive: stacked on mobile, side-by-side on desktop

---

### TASK-FE11: Build divergence indicator visualization
**Domain:** Frontend
**Depends on:** TASK-FE10, TASK-FE03
**Description:** Create a visual component showing the gap between real and sentiment price as the focal point of the UI. Display dollar difference, percentage difference, and a visual gauge/bar indicating which price is higher and by how much.
**Acceptance criteria:**
- Shows absolute dollar divergence
- Shows percentage divergence
- Visual gauge/bar with labeled sides
- Green when sentiment > real, red when real > sentiment
- Clearly labeled "Divergence"
- Updates in real-time when prices change
- Tooltip or label explains what divergence means

---

### TASK-FE12: Integrate TradingView Lightweight Charts library
**Domain:** Frontend
**Depends on:** TASK-FE03, TASK-FE02
**Description:** Install and configure the TradingView Lightweight Charts library. Set up a wrapper React component that initializes the chart with dark theme, custom colors matching the design system, and container-responsive sizing.
**Acceptance criteria:**
- Package installed and importable
- Chart renders without errors
- Dark background and green/red colors applied from design tokens
- Chart resizes with container (ResizeObserver)
- No console warnings
- Wrapper component properly handles mount/unmount

---

### TASK-FE13: Build dual-line chart component (real vs sentiment price)
**Domain:** Frontend
**Depends on:** TASK-FE12, TASK-FE03
**Description:** Create a chart component displaying two price lines: real market price (solid, white/gray) and sentiment price (dashed, colored). Both lines share X and Y axes. Include a legend identifying each line. Tooltip shows both values on hover.
**Acceptance criteria:**
- Two lines rendered with distinct visual styles
- Real price: solid white/gray line
- Sentiment price: dashed colored line
- Both share same time axis and price axis
- Legend identifies each line
- Tooltip on hover shows both values and timestamp
- Works with 1D, 1W, 1M data

---

### TASK-FE14: Implement timeframe selector and chart data refetching
**Domain:** Frontend
**Depends on:** TASK-FE09, TASK-FE12
**Description:** Create timeframe button group (1D, 1W, 1M) that triggers chart data refetch. On timeframe change, call appropriate API endpoint and update chart. Show loading state during fetch.
**Acceptance criteria:**
- Buttons: "1D", "1W", "1M" with active state styling
- Active button visually highlighted
- Clicking fetches new data from API
- Loading state shown while fetching
- Chart updates smoothly on new data
- Default timeframe is 1D on page load
- Error handling if fetch fails

---

### TASK-FE15: Create SSE client hook (`useSSEPrices`)
**Domain:** Frontend
**Depends on:** TASK-FE03, TASK-FE24
**Description:** Build a custom React hook that establishes a Server-Sent Events connection to the **global** endpoint `GET /api/v1/tickers/stream` (TASK-BE38). On each `price_update` SSE event, the hook calls `queryClient.setQueryData` with `TICKERS_QUERY_KEY` to merge the update into the TanStack Query cache, so all components using `useQuery(TICKERS_QUERY_KEY)` see live prices without re-fetching.

**Contract:**
```typescript
import { useQueryClient } from '@tanstack/react-query';
import { TICKERS_QUERY_KEY } from '../lib/queryKeys';
import type { TickerListResponse, SSEPriceUpdateEvent } from '../types/api';

function applySSEUpdate(
  queryClient: ReturnType<typeof useQueryClient>,
  event: SSEPriceUpdateEvent,
) {
  queryClient.setQueryData<TickerListResponse>(TICKERS_QUERY_KEY, (prev) => {
    if (!prev) return prev;
    return {
      tickers: prev.tickers.map((t) =>
        t.symbol === event.ticker
          ? { ...t, sentiment_price: event.sentiment_price, real_price: event.real_price, divergence: event.divergence, timestamp: event.timestamp }
          : t,
      ),
    };
  });
}
```

**Acceptance criteria:**
- Connects to `/api/v1/tickers/stream` (global endpoint, not per-ticker)
- Opens SSE connection on mount, closes on unmount (no memory leaks)
- Reconnects automatically on disconnect with exponential backoff (1s→2s→4s→…→60s cap)
- Each `price_update` event calls `applySSEUpdate` — no separate state atom
- Handles parse errors gracefully without crashing
- Single instance of `useSSEPrices` in a top-level component (e.g., `App.tsx`) suffices for all consumers

---

### TASK-FE16: Integrate real-time SSE updates into HomePage
**Domain:** Frontend
**Depends on:** TASK-FE08, TASK-FE15
**Description:** Connect the HomePage ticker cards to real-time price updates from the SSE hook. When new prices arrive for a ticker, update that card's display (prices, direction, sparkline) without a full page reload.
**Acceptance criteria:**
- Prices update in real-time as SSE messages arrive
- Sparkline extends with new price point
- Direction indicators (green/red arrows) update when direction changes
- No full page refresh
- Updated card does not cause unnecessary re-renders in other cards

---

### TASK-FE17: Integrate real-time SSE updates into TickerDetailPage
**Domain:** Frontend
**Depends on:** TASK-FE09, TASK-FE13, TASK-FE15
**Description:** Connect the detail page dual price display, divergence indicator, and chart to real-time SSE updates. The detail page uses the **per-ticker** endpoint `GET /api/v1/tickers/{ticker}/stream` (TASK-BE26) so only relevant price updates are received. Chart lines extend with new price points; prices and divergence recalculate instantly.

Note: `useSSEPrices` (TASK-FE15) connects to the global stream for the homepage grid. The detail page opens its own per-ticker `EventSource` so chart updates are isolated to the viewed symbol.
**Acceptance criteria:**
- Opens `EventSource` to `/api/v1/tickers/{ticker}/stream` on mount, closes on unmount and ticker navigation
- Dual price display updates instantly on SSE message
- Chart lines extend with new data points in real-time
- Divergence indicator recalculates on every update
- No lag visible on updates
- Both real and sentiment prices update independently

---

### TASK-FE18: Build staleness indicator component
**Domain:** Frontend
**Depends on:** TASK-FE05, TASK-FE15
**Description:** Create a component that shows data freshness — timestamp of last successful data refresh and a warning when data is stale (scraper is down). Color codes by the `staleness_level` field on each `TickerSummary` (from `sse_common.constants`, mirrored in TASK-BE28):

| `staleness_level`  | Age threshold | Display color  |
|--------------------|---------------|----------------|
| `"fresh"`          | < 30 min      | Green          |
| `"warning"`        | 30–60 min     | Yellow/Orange  |
| `"critical"`       | 60 min–4 hr   | Red            |
| `"unavailable"`    | > 4 hr        | Gray / "Offline" |

**Acceptance criteria:**
- Shows "Last updated X minutes ago" derived from `TickerSummary.timestamp`
- Indicator color matches `staleness_level` enum (not raw minutes)
- Shows "Offline" / gray badge when `staleness_level === "unavailable"` or SSE connection is lost
- Updates its own displayed age every 30 seconds without re-fetching
- Appears in both header (global) and detail page footer (per-ticker)

---

### TASK-FE19: Implement market hours indicator
**Domain:** Frontend
**Depends on:** TASK-FE10, TASK-FE03
**Description:** Add a small component showing whether the US stock market is currently open or closed. Explain that real prices only update during market hours (9:30 AM–4:00 PM ET, Mon–Fri) while sentiment prices run 24/7.
**Acceptance criteria:**
- Shows "Market Open" or "Market Closed" with appropriate color
- Shows time until close (if open) or next open (if closed)
- Explains update behavior for real vs sentiment prices
- Updates every minute
- Subtle styling — does not compete visually with price data

---

### TASK-FE20: Audit and finalize mobile-first responsive design
**Domain:** Frontend
**Depends on:** TASK-FE01–TASK-FE19
**Description:** Audit all components at mobile (375px), tablet (768px), and desktop (1024px+) breakpoints. Fix any layout overflow, truncation, or touch-target issues. Ensure minimum 44px touch targets on all interactive elements.
**Acceptance criteria:**
- No horizontal scrolling at any breakpoint
- Touch targets >= 44px on all buttons and links
- Text legible at all breakpoints (min 16px body)
- Ticker grid: 1 col mobile, 2 col tablet, 3 col desktop
- Charts fill container correctly on all screen sizes
- Tested in Chrome DevTools device emulation at 375px, 768px, 1280px

---

### TASK-FE21: Add loading and error states to all data-fetching components
**Domain:** Frontend
**Depends on:** TASK-FE08, TASK-FE09, TASK-FE14
**Description:** Implement loading spinners, skeleton loaders, and error messages with retry buttons for all API-driven components. Every component that fetches data must handle all three states: loading, error, success.
**Acceptance criteria:**
- Loading spinner or skeleton shown while fetching
- Error message shown on failure with retry button
- No infinite loading states (timeout after 10s → error)
- Success state replaces loading automatically
- Error messages are informative and actionable

---

### TASK-FE22: Accessibility audit and fixes
**Domain:** Frontend
**Depends on:** TASK-FE01–TASK-FE21
**Description:** Audit all components for accessibility: semantic HTML, ARIA labels, keyboard navigation, and color contrast. Ensure price direction is communicated beyond color alone (arrows + text), and charts have text descriptions.
**Acceptance criteria:**
- All interactive elements keyboard-navigable with Tab
- Focus visually visible on all interactive elements
- Semantic HTML used throughout (nav, main, section, article)
- ARIA labels on icon-only buttons
- Color contrast >= 4.5:1 for body text, >= 3:1 for UI elements
- Direction communicated with arrows and text, not color alone
- Tested with keyboard-only navigation

---

### TASK-FE23: Performance optimization and code splitting
**Domain:** Frontend
**Depends on:** TASK-FE01–TASK-FE22
**Description:** Implement code splitting for pages using React.lazy and Suspense. Memoize expensive components with React.memo. Audit bundle size and optimize. Target Lighthouse performance score >= 80 and initial load < 2 seconds.
**Acceptance criteria:**
- Detail page lazy-loaded (not in initial bundle)
- Gzipped bundle size < 150KB
- Homepage initial load < 2 seconds on average connection
- No unnecessary re-renders (verified with React DevTools Profiler)
- Lighthouse performance score >= 80
- CSS tree-shaken and minified in production build

---

### TASK-FE24: Integrate TanStack Query for server state and SSE cache merging
**Domain:** Frontend
**Depends on:** TASK-FE01, TASK-FE03
**Description:** Set up `@tanstack/react-query` as the server state layer. All REST API calls use `useQuery`; the SSE hook (TASK-FE15) uses `setQueryData` to merge live events into the same cache so components never need two data sources.

**Setup:**
- Wrap `<App>` in `<QueryClientProvider client={queryClient}>` in `main.tsx`
- Configure `QueryClient` with `staleTime: 30_000` (30 s) and `retry: 2`

**Query key contract (exported from `src/lib/queryKeys.ts`):**
```typescript
export const TICKERS_QUERY_KEY = ['tickers'] as const;
export const tickerDetailKey = (symbol: string) => ['tickers', symbol] as const;
export const tickerHistoryKey = (symbol: string, tf: '1D' | '1W' | '1M') =>
  ['tickers', symbol, 'history', tf] as const;
```

**Data flow:**
1. `HomePage` calls `useQuery({ queryKey: TICKERS_QUERY_KEY, queryFn: fetchTickers })` → populates cache with `TickerListResponse`
2. `useSSEPrices` (TASK-FE15) receives `SSEPriceUpdateEvent` → calls `setQueryData<TickerListResponse>(TICKERS_QUERY_KEY, updater)` → all `TickerCard` components re-render with fresh price via React Query's subscription, no prop drilling
3. `TickerDetailPage` calls `useQuery({ queryKey: tickerDetailKey(symbol), queryFn: fetchTicker(symbol) })` for initial load; per-ticker SSE (TASK-FE17) updates via `setQueryData(tickerDetailKey(symbol), ...)` independently

**Acceptance criteria:**
- `QueryClientProvider` wraps the app at the root level
- `TICKERS_QUERY_KEY`, `tickerDetailKey`, and `tickerHistoryKey` exported from `src/lib/queryKeys.ts`
- `fetchTickers()` returns `TickerListResponse` (typed, not `any`)
- `setQueryData` updater passes TypeScript compilation with `strict: true` (type parameter ensures shape correctness)
- No duplicate `fetch` calls — React Query deduplicates concurrent requests
- Stale data shown immediately on navigation; background refetch updates silently

---

### TASK-FE25: Vitest unit tests for utility functions
**Domain:** Frontend
**Depends on:** TASK-FE01, TASK-FE03
**Description:** Set up Vitest as the test runner (included with Vite; no separate install). Write unit tests for all pure utility functions: price formatting, divergence calculation, staleness level mapping, and SSE event parsing.

**Test setup:**
- `vite.config.ts` includes `test: { environment: 'jsdom' }` block
- `src/setupTests.ts` imports `@testing-library/jest-dom` matchers

**Functions to test (in `src/utils/`):**
| Function | Test cases |
|---|---|
| `formatPrice(n: number): string` | `1234.5` → `"$1,234.50"`, negatives, zero |
| `formatDivergence(d: number): string` | positive `+$12.34`, negative `-$5.00` |
| `calcDivergencePct(real, sentiment): number` | standard case, zero real price guard |
| `parseStalenessLevel(level: StalenessLevel): { color: string; label: string }` | all 4 enum values |
| `parseSSEEvent(raw: string): SSEPriceUpdateEvent \| null` | valid JSON, malformed JSON → null |

**Acceptance criteria:**
- `npm test -- --run` passes with all tests green
- Each utility function has ≥ 3 test cases covering happy path, edge cases, and error path
- Test coverage for `src/utils/` ≥ 90% (enforced via `--coverage` in CI if desired)
- No network calls in any unit test

---

### TASK-FE26: React Testing Library component tests for critical flows
**Domain:** Frontend
**Depends on:** TASK-FE06, TASK-FE15, TASK-FE18, TASK-FE24, TASK-FE25
**Description:** Write component-level tests using React Testing Library (RTL) and `@testing-library/user-event` for the three most critical interactive flows.

**Install:** `npm install -D @testing-library/react @testing-library/user-event @testing-library/jest-dom`

**Tests to write:**

1. **`TickerCard` renders correctly** (`src/components/TickerCard.test.tsx`)
   - Given a `TickerSummary` prop, renders symbol, real price, sentiment price, and divergence
   - Green color class applied when `sentiment_price > real_price`; red when below
   - `staleness_level: "unavailable"` shows gray/offline badge

2. **SSE update propagates to `TickerCard` via React Query cache** (`src/hooks/useSSEPrices.test.tsx`)
   - Render a `QueryClientProvider` + `TickerCard` seeded with initial data
   - Simulate an `SSEPriceUpdateEvent` via `EventSource` mock
   - Assert the card re-renders with updated `sentiment_price` without re-fetching

3. **`HomePage` loading and error states** (`src/pages/HomePage.test.tsx`)
   - Mock `fetchTickers` to return loading → assert skeleton/spinner rendered
   - Mock `fetchTickers` to reject → assert error message and retry button rendered
   - Mock `fetchTickers` to resolve → assert ticker cards rendered

**Acceptance criteria:**
- All 3 test files pass with `npm test -- --run`
- `EventSource` is mocked (not a real network connection) — use `vitest-fetch-mock` or manual mock
- React Query's `QueryClientProvider` is wrapped per test (not global) to prevent cache contamination between tests
- Tests run in under 10 seconds total

---

### TASK-FE27: Playwright E2E smoke test
**Domain:** Frontend
**Depends on:** TASK-FE08, TASK-FE09, TASK-FE16
**Description:** One end-to-end smoke test using Playwright that verifies the core user journey against a running dev stack. Run manually or in a dedicated nightly CI job — not in the standard PR workflow (too slow).

**Install:** `npm install -D @playwright/test` then `npx playwright install chromium`

**Test file:** `e2e/smoke.spec.ts`

**Scenario:**
```
1. Navigate to http://localhost:5173 (Vite dev server)
2. Assert: page title contains "Sentiment Stock Exchange"
3. Assert: at least one TickerCard is visible (selector: [data-testid="ticker-card"])
4. Assert: each visible card shows a symbol, a real price, and a sentiment price (not empty/NaN)
5. Click the first TickerCard
6. Assert: URL changes to /SYMBOL
7. Assert: dual price display is visible (selectors: [data-testid="real-price"], [data-testid="sentiment-price"])
8. Assert: chart container is rendered (selector: [data-testid="price-chart"])
```

**Makefile target:** `make e2e` — starts Vite dev server, waits for it, runs Playwright, tears down

**Acceptance criteria:**
- `make e2e` passes against a running local stack with seeded data
- Test uses `data-testid` attributes (not CSS classes or text, which are brittle)
- Chromium-only (no cross-browser in smoke test — full browser matrix is out of scope)
- E2E test is NOT part of the PR CI workflow (TASK-CI06) — runs separately to avoid requiring a full stack in CI

---

### TASK-FE28: Scenario selector and multi-series chart overlay
**Domain:** Frontend
**Depends on:** TASK-FE14, TASK-FE24, TASK-BE39, TASK-BE41
**Description:** Add a scenario selector UI to the Ticker Detail page and extend `PriceChart.tsx` to render an additional sentiment price line per active scenario. Enables side-by-side comparison of different pricing formula "concoctions" — e.g., comparing an upvote-weighted formula against a volume-weighted one — to evaluate which configuration tracks price movement better.

**Concept:** A "scenario" is a named pricing configuration from `pricing_configurations` (TASK-BE41). Each has a slug (e.g., `"upvote-heavy"`), a display name, and a set of formula coefficients. The chart's existing dashed line is the primary/live config. Additional toggled scenarios add extra dashed lines at the what-if prices those configs would have produced for the same historical data.

**New component — `ScenarioSelector.tsx`:**
- On mount: fetches `GET /api/v1/pricing/configs` to get available scenarios (name, slug, description)
- Renders a toggle-button group — one button per scenario returned by the API
- Multiple scenarios can be active simultaneously (multi-select); default: none active
- Each button has a color swatch and shows the scenario display name
- Disabled state when the API returns no scenarios (hides the entire selector row)

**Scenario color assignment (defined in `src/lib/scenarioColors.ts`):**
Colors are assigned by array index from a fixed palette — not hardcoded per slug — so adding a new config in the DB automatically gets the next color:
```typescript
export const SCENARIO_PALETTE = [
  '#3b82f6',  // blue-500   — first active scenario
  '#a855f7',  // purple-500 — second
  '#f59e0b',  // amber-500  — third
];
export function scenarioColor(index: number): string {
  return SCENARIO_PALETTE[index % SCENARIO_PALETTE.length];
}
```

**`PriceChart.tsx` extension:**
- Accepts new prop: `scenarioSeries?: Record<string, ScenarioDataPoint[]>` where `ScenarioDataPoint = { time: string; sentiment_price: number }`
- For each slug in `scenarioSeries`, adds a `LineSeries` with:
  - `color`: `scenarioColor(index)` where `index` is the scenario's position in the active list
  - `lineStyle`: 2 (dashed), `lineWidth`: 1.5 (thinner than primary 2px lines)
  - `title`: scenario display name
- Chart legend updated to include all active scenario lines
- Tooltip extended to show each scenario's `sentiment_price` at the crosshair position:
  ```
  ┌─────────────────────────────┐
  │  2:34 PM                    │
  │  Market:        $244.50     │
  │  Sentiment:     $249.10     │  ← primary/live config
  │  ─────────────────────────  │
  │  Upvote-Heavy:  $252.30     │  ← scenario overlay
  │  Volume-Heavy:  $246.80     │  ← scenario overlay
  └─────────────────────────────┘
  ```

**Data fetching:**
- `TickerDetailPage.tsx` tracks `activeScenarios: string[]` (slugs) in state (empty = no overlay)
- When `activeScenarios` changes, refetch history with `?configs=upvote-heavy,volume-heavy` appended
- `tickerHistoryKey` updated to include scenarios and shift:
  ```typescript
  export const tickerHistoryKey = (symbol: string, tf: Timeframe, scenarios: string[], shift: number) =>
    ['tickers', symbol, 'history', tf, scenarios.join(','), shift] as const;
  ```
- `fetchHistory` updated to pass `configs` and `shift` query params

**TypeScript additions (`src/types/api.ts`):**
```typescript
export interface PricingConfig {
  id: string;
  slug: string;
  name: string;
  description?: string;
}

export interface ScenarioDataPoint {
  time: string;
  sentiment_price: number;
}

export interface HistoryResponse {
  // ... existing fields ...
  scenario_series?: Record<string, ScenarioDataPoint[]>;
  shift_applied: number;
  shift_unit: 'hours' | 'days';
}
```

**Acceptance criteria:**
- `ScenarioSelector` fetches configs on mount; renders one button per config returned
- Toggling "Upvote-Heavy" on adds a blue dashed line showing what-if prices
- Toggling all scenarios off removes overlay lines, leaving the primary two-line chart unchanged
- Chart tooltip shows all active scenario prices at the crosshair
- `scenarioColor` is the single color source — no hardcoded color strings for scenarios elsewhere
- `data-testid="scenario-selector"` on container; `data-testid="scenario-btn-{slug}"` on each button
- Unit test: `ScenarioSelector` renders buttons for fetched configs; click calls `onToggle(slug)`
- Unit test: `PriceChart` with `scenarioSeries={{ 'upvote-heavy': [...] }}` adds a second dashed line series
- If `GET /api/v1/pricing/configs` fails, selector renders nothing — chart still works normally

---

### TASK-FE29: Time-shift control component
**Domain:** Frontend
**Depends on:** TASK-FE12, TASK-FE28, TASK-BE40
**Description:** Add a time-shift control to the Ticker Detail chart panel that lets users offset sentiment data timestamps by N units relative to price data. Enables exploration of whether Reddit sentiment leads or lags price movement by a configurable lag.

**New component — `TimeShiftControl.tsx`:**
```
┌────────────────────────────────────────┐
│  Sentiment shift:  [−]  [ 3 ]  [+]  hours  [↺]  │
└────────────────────────────────────────┘
```
- `−` and `+` buttons decrement/increment the shift value by 1
- Numeric input allows direct typing (validated: integers only, within range)
- Unit label is read-only, derived from the active timeframe: `"hours"` (1D), `"days"` (1W / 1M)
- `↺` reset button sets shift back to 0 (disabled when shift = 0)
- Range clamping: 1D → 0–23, 1W → 0–6, 1M → 0–29. Out-of-range input is clamped silently.
- API call is debounced 400ms after the last input change to avoid hammering the endpoint

**Visual indicator when shift > 0:**
- A labeled annotation appears above the chart: `"Sentiment shifted +3 hours"` in amber text (`#f59e0b`)
- Helps the user remember that the sentiment line has been moved

**Placement in `TickerDetailPage.tsx`:**
```
[Algorithm toggles row]
[Timeframe buttons]  [Shift control — right-aligned]
[Chart]
```

**State management:**
- `shift: number` state in `TickerDetailPage.tsx` (default: 0)
- Passed to `tickerHistoryKey` and included in `fetchHistory` query params alongside `algorithms`
- Timeframe change resets shift to 0 (prevents invalid shift for new timeframe's range)

**Acceptance criteria:**
- `TimeShiftControl` renders with correct unit label for each timeframe (verified with unit tests)
- Timeframe change resets shift to 0 and the control reflects 0
- `shift=3` on 1D chart triggers `?shift=3` in the API call; chart re-renders with shifted sentiment
- Shift annotation appears when shift > 0, disappears at shift = 0
- `−` button disabled at shift = 0; `+` button disabled at shift = max for active timeframe
- `data-testid="time-shift-control"` on container; `data-testid="shift-decrement"`, `"shift-increment"`, `"shift-input"`, `"shift-reset"` on controls
- Unit tests: clamp logic (shift above max → clamped); unit label changes with timeframe; debounce verified with fake timers

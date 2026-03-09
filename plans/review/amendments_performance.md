# Performance & Risk Amendments
# SSE — Sentiment Stock Exchange
# Covers: PERF-1–6, SCRAPE-7–9, RISK-1–3

---

## Confirmation Section

### PERF-1: Batch Sentiment Analysis
**Tasks checked:** TASK-NLP01, TASK-NLP19
**Finding:** TASK-NLP01 defines `SentimentAnalyzer` with a single method `analyze(text: str) -> float` — no batch method. TASK-NLP19 pipeline acceptance criteria: "Failed NLP scoring on a **single comment** logs the error and skips that comment" — per-comment loop is implicit and confirmed. No mention of batching in TASK-NLP10 (FinBERT) either.
**CONFIRMED**

---

### PERF-2: Batch DB Upserts
**Tasks checked:** TASK-S03, TASK-S18
**Finding:** TASK-S03 exposes `upsert_raw_item(item: RawRedditItem)` (singular). TASK-S18 explicitly states "Calls `upsert_raw_item()` for each item" and "Calls `upsert_raw_item` exactly once per item." N sequential DB roundtrips per scrape run.
**CONFIRMED**

---

### PERF-3: Redis Connection Pooling
**Tasks checked:** TASK-BE11
**Finding:** TASK-BE11 creates async Redis client with no mention of `ConnectionPool`, `max_connections`, or pool sizing. Acceptance criteria: "Redis client connects from URL in settings" — no pooling required.
**CONFIRMED**

---

### PERF-4: TimescaleDB Continuous Aggregates
**Tasks checked:** TASK-BE24
**Finding:** TASK-BE24 acceptance criteria: "Uses `time_bucket()` to reduce data points for 1W and 1M." No mention of materialized views or continuous aggregates anywhere in TASK-BE01–BE33.
**CONFIRMED**

---

### PERF-5: Sentiment Result Caching
**Tasks checked:** TASK-NLP18, TASK-NLP19
**Finding:** TASK-NLP18 defines `comment_sentiment` with `reddit_comment_id TEXT UNIQUE` — the data needed to detect already-analyzed comments exists in schema. However, TASK-NLP19 pipeline has no step that checks `comment_sentiment` before running NLP. No `recompute_on_score_change` config guard mentioned.
**CONFIRMED**

---

### PERF-6: React Query for Frontend
**Tasks checked:** TASK-FE01, TASK-FE08, TASK-FE15, TASK-FE16
**Finding:** TASK-FE01 lists Vite, React 18, Tailwind only — no data-fetching library. TASK-FE08 requires "Periodic polling fallback if SSE not yet connected" implying raw `fetch + useEffect`. TASK-FE15 `useSSEPrices` and REST data are completely separate data flows with no shared cache.
**CONFIRMED**

---

### SCRAPE-7: CAPTCHA Handling
**Tasks checked:** TASK-S10
**Finding:** TASK-S10 notes Playwright is used "when `old.reddit.com` is blocked or returns a CAPTCHA" but acceptance criteria only states "If Playwright also fails, raises `ScraperExhaustedError`" — no CAPTCHA detection branch, no warning log, no `SCRAPER_CAPTCHA_SERVICE_URL` config.
**CONFIRMED**

---

### SCRAPE-8: Concurrent Subreddit Scraping
**Tasks checked:** TASK-S13
**Finding:** TASK-S13 acceptance criteria: "Each subreddit scraped independently" but uses "for each subreddit" language and "Returns combined list" — sequential accumulation. No mention of `asyncio.gather`, `ThreadPoolExecutor`, or `MAX_CONCURRENT_SUBREDDITS`.
**CONFIRMED**

---

### SCRAPE-9: Adaptive Scrape Interval
**Tasks checked:** TASK-S14
**Finding:** TASK-S14 — "Unhandled orchestrator exceptions are logged; scheduler does not exit." No feedback from logged failures into scheduling interval. Interval randomized but not adaptive to failure rate.
**CONFIRMED**

---

### RISK-1: Pushshift Is Dead
**Tasks checked:** TASK-S12
**Finding:** TASK-S12 plans `pushshift_scraper.py` against `/reddit/search/submission` and `/reddit/search/comment` with no availability verification step and no conditional gate. Depends only on TASK-S05/S06 (HTTP client), not on any availability confirmation.
**CONFIRMED**

---

### RISK-2: old.reddit.com May Be Deprecated
**Tasks checked:** TASK-S07, TASK-S10
**Finding:** TASK-S07 targets `old.reddit.com` with no structural assertions or `StructureChangedError`. Tested against "a locally saved fixture" only. No parallel `new.reddit.com` parser in TASK-S10.
**CONFIRMED**

---

### RISK-3: FinBERT RAM on 2GB Droplet
**Tasks checked:** TASK-OPS01, TASK-NLP10, TASK-OPS06
**Finding:** TASK-OPS01 specifies "minimum 2GB RAM." TASK-NLP10 has lazy model loading with no memory guard. TASK-OPS13 states "Resource limits defined" with no specific numbers per service. FinBERT requires ~1.5GB RAM alone.
**CONFIRMED**

---

## Amendment Tasks

---

### TASK-PERF01: Add `analyze_batch` method to `SentimentAnalyzer` interface
**Domain:** Performance
**Amends:** TASK-NLP01 (extends abstract interface), TASK-NLP04, TASK-NLP05, TASK-NLP10 (backends implement), TASK-NLP19 (orchestrator calls batch)
**Depends on:** none
**Description:** Extend the `SentimentAnalyzer` ABC with `analyze_batch(texts: list[str]) -> list[float]`. The default base class implementation calls `analyze()` in a loop (backward-compatible). The FinBERT backend overrides with the Hugging Face pipeline's native batching at a configurable batch size (default 32). The pipeline orchestrator is updated to call `analyze_batch` for all comments in a run.
**Acceptance criteria:**
- `SentimentAnalyzer` defines `analyze_batch(texts: list[str]) -> list[float]` with a default loop-based implementation
- `FinBertSentimentAnalyzer.analyze_batch` uses `pipeline(texts, batch_size=N)` where `N` is from config key `sentiment.finbert.batch_size` (default: 32, valid range: 1–128)
- `len(output) == len(texts)` enforced; mismatched lengths raise `ValueError`
- TASK-NLP19 pipeline orchestrator updated to call `analyze_batch` instead of a per-comment loop
- Unit tests: empty list → empty list; single-element → same result as `analyze()`; batch result order matches input order; FinBERT mock verifies `pipeline` called once per batch, not once per text

---

### TASK-PERF02: Add batch upsert to repository layer
**Domain:** Performance
**Amends:** TASK-S03 (adds new public method), TASK-S18 (deduplicator uses batch method)
**Depends on:** TASK-S03
**Description:** Add `upsert_raw_items_batch(items: list[RawRedditItem]) -> DeduplicationResult` to the repository using `psycopg2.extras.execute_values()` with a single `INSERT ... ON CONFLICT DO UPDATE RETURNING xmax` statement. Update the deduplicator (TASK-S18) to call the batch method instead of a per-item loop.
**Acceptance criteria:**
- `upsert_raw_items_batch` issues exactly one SQL statement regardless of batch size
- Uses `psycopg2.extras.execute_values()` with `page_size` from `DB_BATCH_PAGE_SIZE` env var (default: 500)
- Returns `DeduplicationResult` with correct `inserted`, `score_updated`, `unchanged` counts via `RETURNING xmax`
- Empty list input executes no SQL and returns zeroed `DeduplicationResult`
- Singular `upsert_raw_item` retained as thin wrapper for backward compatibility
- Unit tests: 500-item batch issues one SQL call; correct counts for mixed insert/update/unchanged; empty batch returns zeros

---

### TASK-PERF03: Configure Redis connection pool
**Domain:** Performance
**Amends:** TASK-BE11 (adds pool configuration), TASK-BE30 (pool lifecycle in lifespan)
**Depends on:** TASK-BE02
**Description:** Update `backend/app/db/redis.py` to initialize a `redis.asyncio.ConnectionPool` with a configurable `max_connections` ceiling. Pool is created during FastAPI lifespan startup and stored on `app.state`. Document pool size in `.env.example`.
**Acceptance criteria:**
- `redis.asyncio.ConnectionPool(max_connections=N, decode_responses=True)` used, where `N` is from `REDIS_MAX_CONNECTIONS` env var (default: 50)
- `Redis` client constructed from the pool via `redis.asyncio.Redis(connection_pool=pool)`
- Pool created in lifespan startup (TASK-BE30), stored on `app.state.redis_pool`
- Pool explicitly closed in lifespan shutdown: `await pool.aclose()`
- `REDIS_MAX_CONNECTIONS` documented in `.env.example` with note on sizing relative to uvicorn worker count
- Integration test: 50 concurrent `cache_get` calls all succeed without connection errors

---

### TASK-PERF04: Create TimescaleDB continuous aggregate for 1-hour sentiment price buckets
**Domain:** Performance
**Amends:** TASK-BE06 (adds continuous aggregate to `sentiment_prices` hypertable), TASK-BE24 (queries aggregate for 1W/1M)
**Depends on:** TASK-BE06
**Description:** Create a TimescaleDB continuous aggregate `sentiment_prices_1h` pre-computing 1-hour `time_bucket` aggregates automatically. Update the `GET /api/v1/tickers/{ticker}` endpoint to query `sentiment_prices_1h` for 1W and 1M timeframes instead of rescanning the raw hypertable.
**Acceptance criteria:**
- Migration creates the continuous aggregate:
  ```sql
  CREATE MATERIALIZED VIEW sentiment_prices_1h
  WITH (timescaledb.continuous) AS
  SELECT time_bucket('1 hour', time) AS bucket,
         ticker,
         last(sentiment_price, time) AS sentiment_price,
         last(real_price_at_calc, time) AS real_price
  FROM sentiment_prices
  GROUP BY bucket, ticker;

  SELECT add_continuous_aggregate_policy('sentiment_prices_1h',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
  ```
- TASK-BE24 endpoint selects from `sentiment_prices_1h` for `1W`/`1M` and from raw `sentiment_prices` for `1D`
- Migration is reversible (drops policy then view on downgrade)
- Explain plan for a 1W query shows index scan on aggregate, not sequential scan on raw hypertable

---

### TASK-PERF05: Add pre-analysis existence check to sentiment pipeline
**Domain:** Performance
**Amends:** TASK-NLP19 (adds skip-on-existing gate), TASK-NLP18 (adds bulk query method)
**Depends on:** TASK-NLP18, TASK-NLP19
**Description:** Before running NLP on a batch of comments, query `comment_sentiment` for existing rows matching `reddit_comment_id` + `backend`. Skip re-analysis unless `recompute_on_score_change` config is true and the net score has changed by more than a configurable threshold.
**Acceptance criteria:**
- `SentimentRepository.get_existing_scores(comment_ids: list[str], backend: str) -> dict[str, SentimentResult]` added — fetches all matching rows in one query
- `run_sentiment_pipeline` calls this once per run and filters comments before `analyze_batch`
- Config key `sentiment.recompute_on_score_change` (bool, default: false)
- Config key `sentiment.recompute_score_delta_threshold` (int, default: 10) — minimum net-score change triggering re-analysis when flag is true
- Skipped comments logged at DEBUG with reason "existing result, no recompute"
- Pipeline metrics extended with `comments_skipped_cached` counter
- Unit tests: all cached → zero NLP calls; one with score change above threshold → one NLP call; flag false → no re-analysis regardless

---

### TASK-PERF06: Integrate TanStack Query as frontend data layer
**Domain:** Performance
**Amends:** TASK-FE01 (adds dependency), TASK-FE08 (replaces manual fetch), TASK-FE15 (SSE integrates with query cache), TASK-FE16 (SSE updates flow through cache)
**Depends on:** TASK-FE01
**Description:** Add `@tanstack/react-query` to the Vite project. Wrap application in `QueryClientProvider`. Replace all manual `fetch + useEffect + useState` patterns with `useQuery`. Update `useSSEPrices` to call `queryClient.setQueryData()` on incoming SSE messages, unifying REST and SSE data into a single cache.

**Query key structure and SSE merge contract:** The SSE updater passed to `queryClient.setQueryData` must match the exact shape that `GET /api/v1/tickers` returns, or the merge will silently fail and the UI will show stale REST data. The canonical query key and data shape are:

```typescript
// REST response shape from GET /api/v1/tickers
type TickerListResponse = {
  tickers: TickerSummary[];
};
type TickerSummary = {
  symbol: string;
  sentiment_price: number;
  real_price: number;
  divergence: number;
  staleness_level: "fresh" | "warning" | "critical" | "unavailable";
  timestamp: string;
};

// Query key for the ticker list
const TICKERS_QUERY_KEY = ['tickers'] as const;

// SSE message shape (from sse:pricing:run_complete → BE-SUB broadcast)
type SSEPriceUpdateEvent = {
  type: "price_update";
  ticker: string;  // matches TickerSummary.symbol
  sentiment_price: number;
  real_price: number;
  divergence: number;
  timestamp: string;
};

// SSE updater — field names MUST match TickerSummary exactly
function applySSEUpdate(event: SSEPriceUpdateEvent) {
  queryClient.setQueryData<TickerListResponse>(TICKERS_QUERY_KEY, (prev) => {
    if (!prev) return prev;
    return {
      tickers: prev.tickers.map((t) =>
        t.symbol === event.ticker
          ? { ...t, sentiment_price: event.sentiment_price, real_price: event.real_price, divergence: event.divergence, timestamp: event.timestamp }
          : t
      ),
    };
  });
}
```

The per-ticker detail query key `['ticker', symbol, timeframe]` is updated separately by the per-ticker SSE hook added by TASK-MODERATE-7 amendment.

**Acceptance criteria:**
- `@tanstack/react-query` in `package.json`
- `QueryClient` configured with `staleTime: 30_000`, `gcTime: 300_000`
- `GET /api/v1/tickers` wrapped in `useQuery({ queryKey: TICKERS_QUERY_KEY })` in TASK-FE08; `TICKERS_QUERY_KEY` exported from `src/lib/queryKeys.ts` and imported wherever the key is referenced (no inline string arrays)
- `GET /api/v1/tickers/{ticker}?timeframe=X` wrapped in `useQuery({ queryKey: ['ticker', symbol, timeframe] })`
- `useSSEPrices` calls `queryClient.setQueryData(TICKERS_QUERY_KEY, updater)` on each SSE message using the updater pattern above — field names verified against the `TickerSummary` TypeScript type at compile time
- TypeScript type `SSEPriceUpdateEvent` and `TickerSummary` are co-located in `src/types/api.ts` and share field names; the compiler catches any mismatch between the SSE shape and the cache shape at build time
- No component maintains separate `useState` for prices that could conflict with query cache
- React Query DevTools enabled in development builds only (`import.meta.env.DEV`)
- TASK-FE21 loading/error/retry states derived from `useQuery`'s `isPending`, `isError`, `refetch`
- Bundle size impact documented (~11KB gzipped)

---

### TASK-SCRP01: Add CAPTCHA detection and fallback skip logic to Playwright scraper
**Domain:** Scraping
**Amends:** TASK-S10 (adds CAPTCHA detection branch)
**Depends on:** TASK-S10
**Description:** Add CAPTCHA detection to `PlaywrightScraper` by checking page content for known CAPTCHA indicators after page load. On detection, log WARNING and raise `CaptchaDetectedError` immediately (a subclass of `ScraperExhaustedError`) so the orchestrator advances to RSS fallback. Optionally forward to an external CAPTCHA service if configured.
**Acceptance criteria:**
- `CaptchaDetectedError(ScraperExhaustedError)` defined in `scraper/exceptions.py`
- Checks after page load: `iframe[src*="recaptcha"]` presence, URL containing `captcha`, page title containing "Access Denied" or "Robot"
- On detection: log `WARNING "CAPTCHA detected on {url} for subreddit {subreddit} — skipping Playwright fallback"` and raise `CaptchaDetectedError` with no retry budget consumed
- `SCRAPER_CAPTCHA_SERVICE_URL` env var: when set and non-empty, forward to service and inject solved token; when empty, immediately raise `CaptchaDetectedError`
- Orchestrator (TASK-S13) treats `CaptchaDetectedError` identically to `ScraperExhaustedError` for fallback purposes
- Unit test: mock page with reCAPTCHA iframe → `CaptchaDetectedError` with no retry attempts; mock page without → normal scraping

---

### TASK-SCRP02: Concurrent subreddit scraping in orchestrator
**Domain:** Scraping
**Amends:** TASK-S13 (replaces sequential loop with concurrent execution)
**Depends on:** TASK-S13
**Description:** Replace the sequential per-subreddit loop in `scraper/orchestrator.py` with `asyncio.gather()` so all configured subreddits are scraped concurrently, bounded by a configurable semaphore. Each subreddit task is independent — failure of one does not cancel others.

**Two-tier semaphore design** (Playwright memory constraint): Playwright is memory-hungry — each headless Chromium instance consumes ~300–500MB. Running 4 concurrent instances on the target droplet (4GB RAM, shared with 8 other services) would risk OOM. Therefore concurrency is split by scraper type:
- **Outer semaphore (`MAX_CONCURRENT_SUBREDDITS`, default: 4):** Controls how many subreddits run their full fallback chain concurrently. HTML/BeautifulSoup and RSS scrapers are lightweight and can run at this limit.
- **Inner semaphore (`PLAYWRIGHT_MAX_CONCURRENT`, default: 1):** Shared across all subreddit tasks. Only one Playwright instance is permitted at a time, regardless of `MAX_CONCURRENT_SUBREDDITS`. When a task's fallback chain reaches the Playwright step, it blocks on this inner semaphore until no other Playwright instance is running.

**Acceptance criteria:**
- `asyncio.gather(*tasks, return_exceptions=True)` used to run one scrape task per subreddit concurrently
- `MAX_CONCURRENT_SUBREDDITS` env var (default: 4, minimum: 1) controls outer `asyncio.Semaphore` ceiling
- `PLAYWRIGHT_MAX_CONCURRENT` env var (default: 1, maximum: 2) controls a second `asyncio.Semaphore` shared across all tasks; injected into `PlaywrightScraper` at construction
- `PlaywrightScraper.scrape()` acquires `PLAYWRIGHT_MAX_CONCURRENT` semaphore before launching the browser and releases it on exit (including on exception)
- At most `PLAYWRIGHT_MAX_CONCURRENT` headless browser processes exist simultaneously regardless of subreddit concurrency level
- Exception objects from `gather` logged at ERROR and excluded from results; do not abort other subreddits
- Total wall-clock time for 4-subreddit run ≤ 1.25× the slowest single-subreddit scrape when all subreddits use HTML/RSS path; Playwright serialization is expected and acceptable
- Each concurrent task receives its own proxy selection from the rotation pool (no shared proxy state)
- Unit test: 4 subreddits, all reach Playwright fallback → Playwright runs are serialized (sequential), not concurrent; assert semaphore acquired/released in order
- Unit test: 4 subreddits, one raises `ScraperExhaustedError` → other 3 complete; results contain only items from successful subreddits

---

### TASK-SCRP03: Adaptive scrape interval with health-score backoff
**Domain:** Scraping
**Amends:** TASK-S14 (extends scheduler with adaptive interval logic)
**Depends on:** TASK-S14, TASK-S25
**Description:** Track a rolling `health_score` (0.0–1.0) based on the success rate of the last N scrape runs. When health drops below a threshold, multiply the next interval by a backoff factor. When health recovers, return to normal randomized interval. Log all interval changes at INFO.
**Acceptance criteria:**
- Scheduler maintains a fixed-length deque of last `HEALTH_WINDOW_SIZE` run outcomes (bool), default 10
- `health_score = sum(successes) / HEALTH_WINDOW_SIZE`
- When `health_score < HEALTH_THRESHOLD_LOW` (default: 0.5): next interval = `random.uniform(MIN, MAX) * BACKOFF_FACTOR` (default: 2.0), capped at `SCRAPE_INTERVAL_MAX_BACKOFF` (default: 60 min)
- When `health_score > HEALTH_THRESHOLD_HIGH` (default: 0.8): return to normal `random.uniform(MIN, MAX)`
- Interval changes logged at INFO: `"Scrape health_score={:.2f} — interval adjusted to {:.0f}s (backoff factor {:.1f}x)"`
- All thresholds/factors configurable via env vars: `HEALTH_WINDOW_SIZE`, `HEALTH_THRESHOLD_LOW`, `HEALTH_THRESHOLD_HIGH`, `SCRAPE_BACKOFF_FACTOR`, `SCRAPE_INTERVAL_MAX_BACKOFF`
- Unit tests: 6/10 failures → `health_score=0.4` → backoff applied; 9/10 successes → normal interval; interval never exceeds `SCRAPE_INTERVAL_MAX_BACKOFF`

---

### TASK-RISK01: Research spike — verify Pushshift and alternative API availability
**Domain:** Risk Mitigation
**Amends:** TASK-S12 (implementation BLOCKED until this spike completes)
**Depends on:** none
**Description:** Time-boxed research spike (max 4 hours) to test actual availability of Pushshift, Pullpush, and Arctic Shift APIs. Document results in `docs/pushshift_availability_report.md`. TASK-S12 is BLOCKED until this spike concludes with a written recommendation.
**Acceptance criteria:**
- Each API tested with a concrete HTTP request to submission search endpoint (e.g., `GET /reddit/search/submission?subreddit=wallstreetbets&size=10`)
- Report documents per API: HTTP status code, authentication requirements, rate limits, most-recent post timestamp returned, whether comments endpoint is available
- Report concludes with one of three recommendations: (A) implement against a specific working API, (B) implement against Reddit's official OAuth API (free tier: 100 req/min — sufficient for 4 subreddits at 15–30 min intervals), or (C) remove Pushshift fallback and rely on RSS as last-resort
- TASK-S12 status marked "CONDITIONAL — do not implement until TASK-RISK01 completes"
- If recommendation (B): a new TASK-SCRP04 is created for an OAuth-based fallback scraper

---

### TASK-RISK02: Add structural validation and alternative parser to HTML scrapers
**Domain:** Risk Mitigation
**Amends:** TASK-S07 (adds structural assertions), TASK-S10 (adds `new.reddit.com` JSON API parser)
**Depends on:** TASK-S07, TASK-S10
**Description:** Add a structural validation layer to the BeautifulSoup listing scraper asserting expected CSS selectors are present before parsing. Raise `StructureChangedError` (distinct from network errors) on mismatch. Add a `new.reddit.com` JSON API parser as a lower-brittleness alternative within the Playwright fallback.
**Acceptance criteria:**
- `StructureChangedError(ScraperError)` defined in `scraper/exceptions.py` with fields `url: str`, `expected_selector: str`, `page_snippet: str` (first 500 chars)
- `ListingScraper` checks for selectors before parsing: `div.thing`, `time[datetime]`, `a.title`, `span.score`. Absence of any raises `StructureChangedError`
- `StructureChangedError` logged at CRITICAL (not ERROR) to distinguish Reddit HTML changes from transient network errors
- Orchestrator treats `StructureChangedError` as signal to skip to Playwright with additional log entry noting structural failure
- `PlaywrightScraper` includes secondary parser targeting `new.reddit.com` JSON API (`/r/{subreddit}.json?raw_json=1`), activated by `PLAYWRIGHT_TARGET=new_reddit_json` env var
- Fixture test: removing `div.thing` from saved `old.reddit.com` HTML fixture → `StructureChangedError` raised
- `docs/scraper_structure_assumptions.md` documents all CSS selectors relied upon

---

### TASK-RISK03: Raise minimum RAM and add FinBERT startup memory guard
**Domain:** Risk Mitigation
**Amends:** TASK-OPS01 (raises RAM minimum), TASK-NLP10 (adds startup guard), TASK-OPS06 (adds memory resource limit)
**Depends on:** TASK-OPS01, TASK-NLP10
**Description:** Raise minimum droplet from 2GB to 4GB RAM (8GB recommended for FinBERT). Add a startup memory guard to `FinBertSentimentAnalyzer` that checks available RAM via `psutil` and aborts with a clear error if insufficient. Default `SENTIMENT_BACKEND` to `vader` in all production configs.
**Acceptance criteria:**
- TASK-OPS01 acceptance criteria amended: "minimum **4GB RAM** (8GB RAM recommended when `SENTIMENT_BACKEND=finbert`)" — 2GB minimum removed
- `FinBertSentimentAnalyzer.__init__` calls `_check_memory_requirements()` before model loading when backend is `finbert`
- `_check_memory_requirements()` reads `psutil.virtual_memory().available`; if below `FINBERT_MIN_RAM_GB` (default: 3GB, configurable), raises `InsufficientMemoryError` with message: `"FinBERT requires at least {FINBERT_MIN_RAM_GB}GB free RAM. Found {available:.1f}GB. Set SENTIMENT_BACKEND=vader or upgrade to a larger instance."`
- `InsufficientMemoryError` causes service startup to abort with exit code 1
- Default `SENTIMENT_BACKEND=vader` documented in `.env.example` with comment: `# Set to 'finbert' only on instances with >= 4GB RAM (8GB recommended). See docs/finbert_deployment.md`
- `docs/finbert_deployment.md` created: RAM requirements, ONNX Runtime export procedure (~40% memory reduction), recommended instance size
- TASK-OPS06 docker-compose entry includes `mem_limit: 3g` when `finbert`, `mem_limit: 512m` when `vader`/`textblob`
- Unit test: mock `psutil.virtual_memory().available` returning 1GB → `InsufficientMemoryError`; returning 4GB → loading proceeds

---

## Summary Table

| Finding | Status | New Task | Amends |
|---|---|---|---|
| PERF-1 Batch Sentiment | CONFIRMED | TASK-PERF01 | TASK-NLP01, TASK-NLP04/05/10, TASK-NLP19 |
| PERF-2 Batch DB Upserts | CONFIRMED | TASK-PERF02 | TASK-S03, TASK-S18 |
| PERF-3 Redis Pool | CONFIRMED | TASK-PERF03 | TASK-BE11, TASK-BE30 |
| PERF-4 Continuous Aggregates | CONFIRMED | TASK-PERF04 | TASK-BE06, TASK-BE24 |
| PERF-5 Sentiment Caching | CONFIRMED | TASK-PERF05 | TASK-NLP18, TASK-NLP19 |
| PERF-6 React Query | CONFIRMED | TASK-PERF06 | TASK-FE01, TASK-FE08, TASK-FE15/16 |
| SCRAPE-7 CAPTCHA | CONFIRMED | TASK-SCRP01 | TASK-S10 |
| SCRAPE-8 Concurrent Scraping | CONFIRMED | TASK-SCRP02 | TASK-S13 |
| SCRAPE-9 Adaptive Interval | CONFIRMED | TASK-SCRP03 | TASK-S14 |
| RISK-1 Pushshift Dead | CONFIRMED | TASK-RISK01 | TASK-S12 (BLOCKED) |
| RISK-2 old.reddit Deprecation | CONFIRMED | TASK-RISK02 | TASK-S07, TASK-S10 |
| RISK-3 FinBERT RAM | CONFIRMED | TASK-RISK03 | TASK-OPS01, TASK-NLP10, TASK-OPS06 |

---

## Implementation Sequencing Notes

**Immediate blockers (complete before writing any affected code):**
- TASK-RISK01 (Pushshift research spike) must complete before TASK-S12 is implemented
- TASK-RISK03 must update TASK-OPS01 before any DigitalOcean droplet is provisioned

**Implement alongside core infrastructure (not after):**
- TASK-PERF02 alongside TASK-S03
- TASK-PERF01 alongside TASK-NLP01
- TASK-PERF03 alongside TASK-BE11
- TASK-PERF04 alongside TASK-BE06 migration

**Extend after initial implementation:**
- TASK-SCRP01 after TASK-S10
- TASK-SCRP02 after TASK-S13
- TASK-SCRP03 after TASK-S14
- TASK-RISK02 after TASK-S07
- TASK-PERF05 after TASK-NLP18 and TASK-NLP19

**Frontend (before any component fetches data):**
- TASK-PERF06 as part of TASK-FE01 setup

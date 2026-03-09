# Pricing Engine Service — Atomic Implementation Plan

## Domain: Standalone Service, Pricing Computation, Market Data Fetching, Redis Pub/Sub

> This service owns ALL pricing computation. TASK-BE19, TASK-BE20, TASK-BE21 from
> `03_backend_api.md` are MOVED here. The API server no longer performs pricing calculations.
> Resolves CRITICAL-1 and part of CRITICAL-3 from gap analysis. Also resolves MODERATE-6
> (no market price fetching scheduler).

---

### TASK-PRC01: Project scaffolding and package structure
**Domain:** Pricing Engine Service
**Depends on:** none
**Description:** Create the `pricing/` directory with package structure: `pricing/main.py` (entry point), `pricing/subscriber.py`, `pricing/engine/` (pricing logic moved from backend), `pricing/market_data/` (real price fetcher), `pricing/health.py`, `pricing/config.py`, `pricing/db/`, `pricing/tests/`. Create `pyproject.toml` with dependencies: redis, asyncpg (or psycopg2-binary), httpx, yfinance, structlog, uvicorn, tenacity, apscheduler. Independent of `backend/`.
**Acceptance criteria:**
- `pip install -e .` succeeds in a clean virtualenv
- `python -m pricing.main` starts without import errors (exits cleanly if DB unavailable)
- `pricing/` is independent of `backend/` — no imports from `backend.app.*`
- Config loaded from environment variables with documented defaults

---

### TASK-PRC02: Service configuration and environment variables
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC01
**Description:** Create `pricing/config.py` using pydantic-settings `BaseSettings`. Required: `DATABASE_URL`. Optional: `REDIS_URL` (logs WARNING if absent), `MARKET_DATA_PROVIDER` ("yfinance" or "finnhub", default: "yfinance"), `FINNHUB_API_KEY` (required if provider is finnhub), `HEALTH_PORT` (default: 8082), `POLL_INTERVAL_SECONDS` (default: 300), `MARKET_HOURS_FETCH_INTERVAL_SECONDS` (default: 300), `LOG_LEVEL` (default: INFO).
**Acceptance criteria:**
- Missing `DATABASE_URL` raises clear error at startup
- Missing `REDIS_URL` logs WARNING and enables poll-only mode
- `FINNHUB_API_KEY` required only when `MARKET_DATA_PROVIDER=finnhub`
- All defaults documented in `.env.example` with inline comments

---

### TASK-PRC03: Pricing engine configuration loader (MOVED from TASK-BE19)
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC01, TASK-BE09
**Description:** Move `PricingConfig` and `load_active_config()` from `backend/app/services/pricing/config.py` into `pricing/engine/config.py`. Functionality identical to TASK-BE19: Pydantic model validating all pricing parameters, loaded from the active row in `pricing_parameters` table, with YAML file fallback. No dependency on FastAPI.
**Acceptance criteria:**
- Same acceptance criteria as TASK-BE19
- Code lives in `pricing/engine/config.py`, not `backend/`
- No dependency on FastAPI or backend application code
- TASK-BE19 in `03_backend_api.md` marked as `[MOVED → TASK-PRC03]`

---

### TASK-PRC04: Pricing engine core calculation (MOVED from TASK-BE20)
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC03
**Description:** Move `PricingEngine` class from `backend/app/services/pricing/engine.py` into `pricing/engine/calculator.py`. Functionality identical to TASK-BE20: `calculate_sentiment_price(ticker, sentiment_scores, config) -> Decimal` applying temporal decay, volume weighting, score magnitude weighting, dampening, and per-ticker sensitivity. Each factor is a separate testable method.
**Acceptance criteria:**
- Same acceptance criteria as TASK-BE20
- Code lives in `pricing/engine/calculator.py`, not `backend/`
- No dependency on FastAPI or backend application code
- All unit tests from TASK-BE20 moved to `pricing/tests/`
- TASK-BE20 in `03_backend_api.md` marked as `[MOVED → TASK-PRC04]`

---

### TASK-PRC05: Pricing engine orchestrator (MOVED from TASK-BE21)
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC04, TASK-BE05, TASK-BE06, TASK-BE07
**Description:** Move `PricingService` from `backend/app/services/pricing/service.py` into `pricing/engine/service.py`. Orchestrates a full pricing cycle: load active config → for each active ticker, query latest sentiment from `ticker_sentiment_snapshot` → query current real price from `real_prices` → calculate sentiment price → write to `sentiment_prices` → update Redis cache. Modified from TASK-BE21: does NOT call `SSEManager.broadcast()` — that is now the API server's job via Redis pub/sub.
**Acceptance criteria:**
- Processes all active tickers in a single cycle
- Writes results to `sentiment_prices` hypertable with `parameters_version`
- Updates Redis cache keys: `sse:prices:current`, `sse:ticker:{symbol}:latest`
- Logs timing for the full cycle
- Partial failures handled gracefully (one ticker failing does not stop others)
- Returns `PricingCycleResult` with summary of what was calculated
- Does NOT call SSEManager or any API server code
- TASK-BE21 in `03_backend_api.md` marked as `[MOVED → TASK-PRC05]`

---

### TASK-PRC06: Redis subscriber for `sse:sentiment:run_complete`
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC02
**Description:** Implement `pricing/subscriber.py` with `SentimentEventSubscriber` subscribing to Redis pub/sub channel `sse:sentiment:run_complete`. On message: parses JSON payload (`run_id`, `tickers_processed`, `items_analyzed`, `timestamp`), invokes pricing cycle callback. Handles Redis disconnection with exponential backoff (same pattern as TASK-PROC03).
**Acceptance criteria:**
- Subscribes to `sse:sentiment:run_complete` channel
- Parses and validates JSON payload
- Invokes registered callback with parsed payload
- On Redis disconnect: logs WARNING, retries with exponential backoff (1s to 60s cap)
- On invalid JSON: logs ERROR, does not crash
- Unit tests mock Redis and verify callback invocation

---

### TASK-PRC07: Redis publisher for `sse:pricing:run_complete`
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC05
**Description:** After `PricingService` completes a successful pricing cycle, publish JSON to Redis channel `sse:pricing:run_complete`. Payload: `{"run_id": "<uuid>", "tickers_priced": ["TSLA", ...], "timestamp": "2026-03-01T12:00:00Z"}`. Resilient to Redis unavailability (same pattern as TASK-S20 and TASK-PROC06).
**Acceptance criteria:**
- Publishes to `sse:pricing:run_complete` after each successful pricing cycle
- Payload contains `run_id` (UUID4), `tickers_priced` (list of strings), `timestamp` (ISO 8601 UTC)
- If Redis unavailable: logs WARNING, does not raise
- Channel name is a constant in shared constants module
- Unit tests verify correct payload and graceful degradation on Redis failure

---

### TASK-PRC08: Poll-based fallback trigger
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC05
**Description:** Implement `pricing/poller.py` with `DatabasePoller` periodically checking for new `ticker_sentiment_snapshot` rows that haven't been priced yet. Query: find snapshots where `created_at > last_pricing_run_timestamp` and no corresponding row exists in `sentiment_prices` for `(ticker, window_end)`. Triggers pricing cycle if found. Mutex prevents duplicate runs with the Redis subscriber.
**Acceptance criteria:**
- Polls every `POLL_INTERVAL_SECONDS` (configurable, default 300)
- Skips if pricing cycle already in progress (mutex)
- Resets timer when Redis subscriber triggers a run
- Correct SQL query identifies unpriced sentiment snapshots
- Unit tests verify poll logic and mutex behavior

---

### TASK-PRC09: Market data provider integration
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC01, TASK-BE15, TASK-BE16, TASK-BE17, TASK-BE18
**Description:** Import or re-implement the market data provider abstraction (`MarketDataProvider` ABC, yfinance, Finnhub, factory) within the pricing service at `pricing/market_data/`. Used by both `RealPriceFetcher` (TASK-PRC10) and `PricingService` (TASK-PRC05). The pricing service and API server may share code via a `sse-common` package or re-implement independently with the same interface.
**Acceptance criteria:**
- `MarketDataProvider` ABC available in `pricing/market_data/base.py`
- yfinance and Finnhub implementations available
- Factory function selects provider based on `MARKET_DATA_PROVIDER` config
- Provider code has no dependency on FastAPI
- Unit tests mock the provider in both implementations

---

### TASK-PRC10: Real price fetcher — scheduled market data ingestion
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC09, TASK-BE07
**Description:** Implement `pricing/market_data/fetcher.py` with `RealPriceFetcher`. During US market hours (9:30 AM – 4:00 PM ET, Mon–Fri), fetches batch real prices for all active tickers every `MARKET_HOURS_FETCH_INTERVAL_SECONDS` (default: 300). Writes to `real_prices` hypertable with `source` and `market_status`. Updates Redis cache `sse:prices:current`. Outside market hours: fetches once at startup to get last close price, then idles until next market open.
**Acceptance criteria:**
- Fetches prices only during US market hours
- Accounts for US federal holidays (NYSE calendar library or configurable holiday list)
- Writes to `real_prices` table with all required fields (`time`, `ticker`, `price`, `source`, `market_status`, `created_at`)
- Updates Redis cache `sse:prices:current` with latest prices per ticker
- Outside market hours: uses last available price, does not fetch
- Handles provider errors gracefully (logs ERROR, retries next interval)
- Logs at INFO: each fetch cycle with ticker count, duration, market status
- Unit tests: mock provider, verify market hours logic, verify DB writes and Redis update

---

### TASK-PRC11: Initial sentiment price bootstrapping (resolves MODERATE-5)
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC05, TASK-PRC10
**Description:** On first boot with no prior pricing history, `PricingService.calculate_sentiment_price()` receives `previous=None`. In this case, set the initial sentiment price equal to the current real market price from `real_prices`. This makes divergence start at zero, which is intuitive for users. Document this bootstrap behavior clearly in code comments and config documentation.
**Acceptance criteria:**
- When `previous=None`, initial `sentiment_price` is set to the most recent `real_price` for that ticker from `real_prices` table
- If no real price exists yet (also first boot), initial `sentiment_price` is `None` and the ticker is excluded from the homepage until both real and sentiment prices are available
- Bootstrap behavior logged at INFO: `"Bootstrapping {ticker} sentiment price to real price {price}"`
- Config key `pricing.bootstrap_to_real_price` (bool, default: true) allows disabling bootstrap if needed
- Unit tests: `previous=None` and real price exists → `sentiment_price = real_price`; `previous=None` and no real price → `None`

---

### TASK-PRC12: Health check HTTP endpoint
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC05, TASK-PRC10
**Description:** Implement `pricing/health.py` — minimal HTTP server on port 8082 serving `GET /health`. Returns JSON: `status` ("ok"/"degraded"/"down"), `last_pricing_run_at`, `tickers_priced`, `last_real_price_fetch_at`, `market_status`, `redis_connected`, `mode` ("event_driven"/"poll_only"), `seconds_since_last_pricing_run`.
**Acceptance criteria:**
- `GET /health` returns HTTP 200 with JSON body
- `status: "ok"` when last pricing run within 2× expected interval and market data is fresh
- `status: "degraded"` when Redis disconnected or pricing is stale
- `status: "down"` when no successful run completed and service up > 10 minutes
- Health server starts within 2 seconds, does not block main event loop

---

### TASK-PRC13: Main entry point and graceful shutdown
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC05, TASK-PRC06, TASK-PRC07, TASK-PRC08, TASK-PRC10, TASK-PRC12
**Description:** Implement `pricing/main.py` as service entry point. Startup: load config → init DB pool → init Redis (if configured) → init market data provider → start health server → start real price fetcher scheduler → start Redis subscriber → start DB poller → run event loop. Shutdown on SIGTERM/SIGINT: complete in-progress pricing cycle (up to 60s), close connections, exit 0.
**Acceptance criteria:**
- `python -m pricing.main` starts all components
- Startup sequence logged at INFO with component status
- SIGTERM triggers graceful shutdown within 30 seconds
- In-progress pricing cycle allowed to complete (up to 60s timeout)
- All connections closed cleanly on shutdown
- Exit code 0 on graceful shutdown, 1 on unhandled error

---

### TASK-PRC14: Structured logging for Pricing Engine
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC01
**Description:** Configure structured JSON logging consistent with other services (TASK-S25, TASK-PROC10, TASK-OPS27). Every entry includes `service: "pricing"`, `run_id` (during pricing cycles), `timestamp`, `level`. Pricing audit trail: log every computed sentiment price with ticker, price value, and `parameters_version` at INFO level.
**Acceptance criteria:**
- All log calls use structured logger (no bare `print()`)
- Pricing computations logged for audit trail
- Log level configurable via `LOG_LEVEL` env var
- JSON format compatible with Docker json-file log driver

---

### TASK-PRC15: Dockerfile reference and integration with TASK-OPS07
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC13, TASK-OPS07
**Description:** Verify the Dockerfile from TASK-OPS07 correctly builds and runs the pricing service. Entry point: `CMD ["python", "-m", "pricing.main"]`. Health check: `CMD curl -f http://localhost:8082/health || exit 1`. No ML dependencies needed — this container should be lightweight.
**Acceptance criteria:**
- `docker build -f pricing/Dockerfile .` succeeds
- `docker run` starts the service and health endpoint responds on port 8082
- Non-root user `app_pricing_engine` (per TASK-OPS03)
- Container size < 500MB (no transformers/ML dependencies)

---

### TASK-PRC16: Integration test — full event-driven pricing cycle
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC13
**Description:** Integration test exercising: Redis publishes `sse:sentiment:run_complete` → pricing engine subscribes → queries test DB for fixture sentiment data → computes sentiment prices → writes to `sentiment_prices` → updates Redis cache → publishes `sse:pricing:run_complete`. Uses real PostgreSQL and Redis via testcontainers.
**Acceptance criteria:**
- Marked `@pytest.mark.integration`, skipped unless `RUN_INTEGRATION_TESTS=true`
- Fixture: `ticker_sentiment_snapshot` rows for 3 tickers, `real_prices` rows, active `pricing_parameters` row
- Asserts: `sentiment_prices` rows created with correct values
- Asserts: Redis cache `sse:prices:current` and `sse:ticker:{symbol}:latest` updated
- Asserts: `sse:pricing:run_complete` published with correct payload
- Test DB and Redis torn down after run (no state leakage)

---

### TASK-PRC17: Integration test — real price fetcher cycle
**Domain:** Pricing Engine Service
**Depends on:** TASK-PRC10
**Description:** Integration test for `RealPriceFetcher`: mock market data provider returns known prices → fetcher writes to `real_prices` table → updates Redis cache. Verify market hours logic with time mocking.
**Acceptance criteria:**
- Marked `@pytest.mark.integration`
- Mock provider returns deterministic prices for all test tickers
- Asserts: `real_prices` rows written with correct `source` and `market_status`
- Asserts: Redis cache `sse:prices:current` updated with correct values
- Time-mocked tests verify: fetches during market hours, idles outside market hours
- Test DB and Redis torn down after run

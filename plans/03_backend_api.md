# Backend API, Database, Pricing Engine & Real-Time Updates — Atomic Implementation Plan

## Domain: FastAPI, PostgreSQL/TimescaleDB, Redis, SSE, Pricing Engine, Market Data

---

### TASK-BE01: Initialize FastAPI project structure
**Domain:** Backend / API
**Depends on:** none
**Description:** Create the FastAPI application directory under `backend/` with standard layout: `backend/app/main.py`, `backend/app/api/`, `backend/app/core/`, `backend/app/models/`, `backend/app/schemas/`, `backend/app/services/`, `backend/app/db/`. Set up `pyproject.toml` with FastAPI, uvicorn, pydantic, pydantic-settings as initial dependencies.
**Acceptance criteria:**
- `backend/` directory exists with described sub-package structure
- `pyproject.toml` lists FastAPI, uvicorn, pydantic, pydantic-settings
- Running `uvicorn app.main:app` starts without errors
- All directories contain `__init__.py`

---

### TASK-BE02: Implement application configuration system (pydantic-settings)
**Domain:** Backend / API
**Depends on:** TASK-BE01
**Description:** Create `backend/app/core/config.py` using pydantic-settings `BaseSettings` to load all configuration from environment variables. Sections: database URL, Redis URL, API rate limits, market data provider selection (dev/prod), Finnhub API key, pricing engine parameters path, CORS origins, debug mode, version.
**Acceptance criteria:**
- `Settings` class loads from env vars with `.env` file support
- All required config keys defined with types and defaults
- Singleton `get_settings()` function for dependency injection
- `.env.example` documents every variable

---

### TASK-BE03: Set up API versioning structure under /api/v1/
**Domain:** Backend / API
**Depends on:** TASK-BE01
**Description:** Create an `APIRouter` at `backend/app/api/v1/router.py` aggregating all v1 sub-routers. Mount under `/api/v1` prefix in `main.py`. Each resource (tickers, health) gets its own router file under `backend/app/api/v1/endpoints/`.
**Acceptance criteria:**
- All endpoints served under `/api/v1/` prefix
- Adding a new resource requires only creating a new router file
- Placeholder `GET /api/v1/` returns `{"version": "1.0"}`

---

### TASK-BE04: Database migrations — all tables (canonical migration ownership)
**Domain:** Backend / API
**Depends on:** TASK-BE02, TASK-OPS33
**Description:** Configure Alembic to write all migrations to `database/migrations/` (the single shared directory from TASK-OPS33). Create the initial migration covering all tables. Canonical table name is `reddit_raw` (NOT `reddit_raw_data`). Migration covers: `reddit_raw`, `sentiment_scores`, `sentiment_prices`, `real_prices`, `tickers`, `pricing_parameters`. Subsequent tasks (BE05–BE09) add their own migration files to the same directory.
**Acceptance criteria:**
- Alembic configured with `alembic.ini` pointing to `../../database/migrations/` (relative to `backend/`)
- `reddit_raw` table created with: UNIQUE constraint on `(reddit_id, ticker_mentioned)` composite — NOT `reddit_id` alone; `content_fingerprint VARCHAR(64)` column; `is_duplicate BOOLEAN DEFAULT FALSE` column
- Indexes on `(ticker_mentioned)`, `(timestamp)`, `(content_fingerprint, created_at) WHERE is_duplicate = FALSE`
- All migrations run forward and backward cleanly via `alembic upgrade head` / `alembic downgrade base`
- Migrations are backward-compatible: new columns added as nullable or with defaults

---

### TASK-BE05: Database migration — `sentiment_scores` TimescaleDB hypertable
**Domain:** Backend / API
**Depends on:** TASK-BE04
**Description:** Create `sentiment_scores` table with: `time` (timestamptz NOT NULL), `ticker` (varchar), `window_start`, `window_end` (timestamptz), `avg_sentiment` (float), `weighted_sentiment` (float), `volume` (integer), `score_sum` (float), `created_at` (timestamptz). Convert to TimescaleDB hypertable partitioned on `time`. Composite index on `(ticker, time DESC)`.
**Acceptance criteria:**
- Migration calls `SELECT create_hypertable('sentiment_scores', 'time')`
- Composite index `(ticker, time DESC)` exists
- Migration is reversible

---

### TASK-BE06: Database migration — `sentiment_prices` TimescaleDB hypertable
**Domain:** Backend / API
**Depends on:** TASK-BE04
**Description:** Create `sentiment_prices` hypertable: `time` (timestamptz NOT NULL), `ticker` (varchar), `sentiment_price` (numeric(12,4)), `real_price_at_calc` (numeric(12,4), nullable), `parameters_version` (varchar), `created_at` (timestamptz). Index on `(ticker, time DESC)`.
**Acceptance criteria:**
- Hypertable created on `time` column
- `parameters_version` column allows tracing which config produced each price
- Index on `(ticker, time DESC)` exists
- Migration is reversible

---

### TASK-BE07: Database migration — `real_prices` TimescaleDB hypertable
**Domain:** Backend / API
**Depends on:** TASK-BE04
**Description:** Create `real_prices` hypertable: `time` (timestamptz NOT NULL), `ticker` (varchar), `price` (numeric(12,4) NOT NULL), `source` (varchar — 'yfinance' or 'finnhub'), `market_status` (varchar), `created_at` (timestamptz). Index on `(ticker, time DESC)`.
**Acceptance criteria:**
- Hypertable created and indexed
- `source` column tracks which provider supplied data
- Migration is reversible

---

### TASK-BE08: Database migration — `tickers` reference table and seed data
**Domain:** Backend / API
**Depends on:** TASK-BE04
**Description:** Create `tickers` table: `symbol` (varchar PK), `company_name` (varchar), `is_active` (boolean, default true), `added_at` (timestamptz). Seed with initial 4–6 tickers (TSLA, NVDA, GME, PLTR, SOFI, RIVN).
**Acceptance criteria:**
- `tickers` table exists with specified schema
- 4–6 initial tickers seeded
- `is_active` flag allows disabling a ticker without deleting data

---

### TASK-BE09: Database migration — `pricing_parameters` table
**Domain:** Backend / API
**Depends on:** TASK-BE04
**Description:** Create `pricing_parameters` table: `id` (serial PK), `version_label` (varchar, unique), `parameters` (jsonb NOT NULL), `is_active` (boolean, default false), `created_at` (timestamptz), `notes` (text, nullable). Partial unique index ensures only one active row. Seed with default parameter set.
**Acceptance criteria:**
- Table created with jsonb `parameters` column
- Partial unique index: `CREATE UNIQUE INDEX ON pricing_parameters (is_active) WHERE is_active = true`
- Default parameter row seeded with placeholder values (decay_factor, volume_weight, score_magnitude_weight, dampening_factor, high/low volume sensitivity, base_price_multiplier)
- Migration is reversible

---

### TASK-BE10: SQLAlchemy ORM models and async session management
**Domain:** Backend / API
**Depends on:** TASK-BE02, TASK-BE04
**Description:** Create SQLAlchemy ORM models in `backend/app/models/` for all six tables. Set up async engine and session factory in `backend/app/db/session.py` using `asyncpg`. Create a `get_db` dependency for FastAPI endpoints.
**Acceptance criteria:**
- All six models defined with correct column types
- `async_sessionmaker` configured with `asyncpg` driver
- `get_db()` async generator yields a session and handles cleanup
- Models importable from `app.models`

---

### TASK-BE11: Set up Redis connection and base caching utilities
**Domain:** Backend / API
**Depends on:** TASK-BE02
**Description:** Create `backend/app/db/redis.py` with an async Redis client (`redis.asyncio`). Implement: `get_redis()` dependency, `cache_get(key)`, `cache_set(key, value, ttl)`, `cache_delete(key)`, `cache_get_or_set(key, ttl, factory_fn)`. All values JSON-serialized.
**Acceptance criteria:**
- Redis client connects from URL in settings
- `cache_get_or_set` correctly calls factory on miss and caches the result
- TTL respected on all cache writes
- Connection closed on app shutdown (lifespan event)

---

### TASK-BE12: Implement rate limiting middleware
**Domain:** Backend / API
**Depends on:** TASK-BE03, TASK-BE11
**Description:** Add rate limiting to all `/api/v1/` endpoints using `slowapi` (or custom Redis-backed middleware). Limits configurable via settings (default: 60/min per IP). Returns 429 with `Retry-After` header on violation.
**Acceptance criteria:**
- All `/api/v1/` endpoints rate-limited
- Limit values configurable via env vars
- Redis is the backing store (works across multiple uvicorn workers)
- 429 response includes `Retry-After` header
- Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`) in all responses

---

### TASK-BE13: Configure CORS middleware
**Domain:** Backend / API
**Depends on:** TASK-BE02, TASK-BE03
**Description:** Add `CORSMiddleware` in `main.py` reading allowed origins from settings. Dev: allow `localhost:3000`. Prod: restrict to actual domain. Expose headers needed for SSE and rate limiting.
**Acceptance criteria:**
- CORS origins configurable via env var (comma-separated)
- Dev defaults include `http://localhost:3000`
- `Access-Control-Expose-Headers` includes rate limit headers
- Preflight requests handled correctly

---

### TASK-BE14: Define Pydantic response schemas for all API endpoints
**Domain:** Backend / API
**Depends on:** TASK-BE01
**Description:** Create Pydantic v2 models in `backend/app/schemas/` for: `TickerSummary`, `TickerListResponse`, `PricePoint`, `TickerDetail`, `SSEPriceUpdate`, `HealthResponse`. Include example values for OpenAPI docs.
**Acceptance criteria:**
- All schemas defined with proper types, validation, and JSON serialization config
- `model_config` uses `from_attributes = True` for ORM compatibility
- Example values provided via `json_schema_extra`
- Schemas importable from `app.schemas`

---

### TASK-BE15: Implement market data provider abstract interface
**Domain:** Backend / API
**Depends on:** TASK-BE02
**Description:** Create `backend/app/services/market_data/base.py` defining abstract base class `MarketDataProvider` with async methods: `get_current_price(ticker) -> Decimal`, `get_batch_prices(tickers) -> dict[str, Decimal]`, `is_market_open() -> bool`, `get_market_status() -> str`. Defines `MarketDataError` exception.
**Acceptance criteria:**
- ABC with all four abstract methods
- Type hints use `Decimal` for prices (not float)
- Docstrings document expected behavior and error cases
- `MarketDataError` custom exception defined

---

### TASK-BE16: Implement yfinance market data provider (dev)
**Domain:** Backend / API
**Depends on:** TASK-BE15
**Description:** `yfinance_provider.py` implementing `MarketDataProvider`. Handle yfinance instability with retries (tenacity, max 3 attempts) and timeouts (10s per call). Market hours check uses US Eastern time and NYSE hours.
**Acceptance criteria:**
- Implements all four abstract methods
- Retries on transient failures with exponential backoff
- Returns `Decimal` prices rounded to 4 places
- Raises `MarketDataError` on unrecoverable failures
- Market hours check accounts for weekends

---

### TASK-BE17: Implement Finnhub market data provider (prod)
**Domain:** Backend / API
**Depends on:** TASK-BE15
**Description:** `finnhub_provider.py` implementing `MarketDataProvider` using `httpx.AsyncClient`. Respects 60 calls/min rate limit via async semaphore. API key from settings. `get_batch_prices` makes concurrent requests within rate limit.
**Acceptance criteria:**
- Implements all four abstract methods
- Uses `httpx.AsyncClient` for async HTTP
- Rate limiting enforced at provider level (max 60 calls/min)
- API key from settings, never hardcoded
- Proper error handling for 401, 429, 5xx responses

---

### TASK-BE18: Implement market data provider factory
**Domain:** Backend / API
**Depends on:** TASK-BE15, TASK-BE16, TASK-BE17
**Description:** Factory function `get_market_data_provider(settings) -> MarketDataProvider` returning yfinance when `settings.market_data_provider == "yfinance"` and Finnhub when `"finnhub"`. FastAPI dependency `get_market_data()` exposes configured provider.
**Acceptance criteria:**
- Factory selects provider based on config
- Unknown provider names raise `ValueError` with clear message
- FastAPI dependency available for endpoint injection
- Provider instantiated once (singleton per app lifecycle)

---

### TASK-BE19: [MOVED → TASK-PRC03 in `02c_pricing_engine_service.md`]
**Domain:** Backend / API — MOVED
**Note:** This task has been extracted to the standalone Pricing Engine service. The API server no longer owns pricing logic. See `02c_pricing_engine_service.md` TASK-PRC03 for the implementation. Do not implement this task in the backend.

---

### TASK-BE20: [MOVED → TASK-PRC04 in `02c_pricing_engine_service.md`]
**Domain:** Backend / API — MOVED
**Note:** This task has been extracted to the standalone Pricing Engine service. See `02c_pricing_engine_service.md` TASK-PRC04 for the implementation. Do not implement this task in the backend.

---

### TASK-BE21: [MOVED → TASK-PRC05 in `02c_pricing_engine_service.md`]
**Domain:** Backend / API — MOVED
**Note:** This task has been extracted to the standalone Pricing Engine service. See `02c_pricing_engine_service.md` TASK-PRC05 for the implementation. The API server no longer runs pricing cycles. Do not implement this task in the backend.

---

### TASK-BE22: Implement Redis caching layer for ticker data
**Domain:** Backend / API
**Depends on:** TASK-BE11, TASK-BE14
**Description:** Create `backend/app/services/cache.py` with domain-specific cache functions: `get_cached_ticker_list()`, `set_cached_ticker_list(data, ttl=60)`, `get_cached_ticker_detail(ticker, timeframe)`, `set_cached_ticker_detail(...)`, `get_cached_current_prices()`, `set_cached_current_prices(prices)`. Consistent `sse:` key prefix.
**Acceptance criteria:**
- Consistent key naming: `sse:tickers:list`, `sse:ticker:{symbol}:{timeframe}`, `sse:prices:current`
- TTLs configurable with defaults (60s list, 120s detail, 30s current prices)
- Serialization uses Pydantic's `.model_dump_json()` / `.model_validate_json()`
- Cache miss returns `None`, never raises

---

### TASK-BE23: Implement GET /api/v1/tickers endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE03, TASK-BE10, TASK-BE14, TASK-BE22
**Description:** `GET /api/v1/tickers` returns all active tickers with current real and sentiment prices. Checks Redis cache first; on miss, queries DB, builds response, populates cache. Includes `last_updated` timestamp per ticker.
**Acceptance criteria:**
- Returns JSON array of `TickerSummary` objects
- Serves from Redis on cache hit
- Falls back to DB query on miss and caches result
- Handles empty database gracefully (empty list, not 500)

---

### TASK-BE24: Implement GET /api/v1/tickers/{ticker} endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE23
**Description:** `GET /api/v1/tickers/{ticker}` with `?timeframe=1D|1W|1M` query parameter (default 1D). Returns full price history for both real and sentiment prices. Uses TimescaleDB `time_bucket` for downsampling on 1W and 1M. Cached per ticker+timeframe.
**Acceptance criteria:**
- 404 if ticker not found
- Enum validation on `timeframe` query param
- Returns `TickerDetail` schema with both price histories
- Uses `time_bucket()` to reduce data points for 1W and 1M
- Cached per ticker+timeframe combination
- ISO 8601 timestamps in response

---

### TASK-BE25: Implement the SSE connection manager
**Domain:** Backend / API
**Depends on:** TASK-BE01
**Description:** Create `backend/app/services/sse.py` with `SSEManager` class managing connected clients via `asyncio.Queue` per ticker. Methods: `connect(ticker) -> Queue`, `disconnect(ticker, queue)`, `broadcast(ticker, data)`, `broadcast_all(data)`. Includes cleanup of dead connections.
**Acceptance criteria:**
- Thread-safe queue management per ticker
- `connect` returns asyncio.Queue that receives events
- `disconnect` cleanly removes the queue
- `broadcast` sends to all connected clients for a specific ticker
- `broadcast_all` sends to every connected client
- Dead/disconnected queues cleaned up

---

### TASK-BE26: Implement GET /api/v1/tickers/{ticker}/stream SSE endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE03, TASK-BE14, TASK-BE25
**Description:** SSE streaming endpoint using FastAPI `StreamingResponse` with `text/event-stream` content type. On connect, sends current price as first event. Then listens on client queue for new events. Sends keepalive comments every 30s to prevent proxy timeouts. Handles client disconnection gracefully.
**Acceptance criteria:**
- Returns `text/event-stream` content type
- First event is current prices for requested ticker
- Keepalive comments sent every 30 seconds (`:keepalive\n\n`)
- Client disconnection detected and cleaned up
- SSE format: `event: price_update\ndata: {json}\n\n`
- 404 if ticker not found

---

### TASK-BE27: SSE broadcast logic triggered by Redis pricing event
**Domain:** Backend / API
**Depends on:** TASK-BE25, TASK-BE36
**Description:** The broadcast logic invoked by `PricingEventSubscriber` (TASK-BE36) when a `sse:pricing:run_complete` Redis event is received. On event: reads latest prices from Redis cache (`sse:prices:current`), calls `SSEManager.broadcast(ticker, data)` for each ticker in `tickers_priced`, then calls `SSEManager.broadcast_all(summary_event)`. The API server no longer runs pricing — it only reacts to pricing events from the Pricing Engine service.
**Acceptance criteria:**
- Broadcast payload matches `SSEPriceUpdate` schema
- Summary `data_refresh` event broadcast to all clients after per-ticker broadcasts
- SSE manager failures caught and logged — do not crash the API server and do not abort other ticker broadcasts
- Broadcast is async and non-blocking relative to Redis event receipt
- If Redis cache `sse:prices:current` is unavailable: logs WARNING, skips broadcast for affected tickers
- Unit tests mock SSEManager and Redis cache; verify `broadcast` called once per ticker in event payload

---

### TASK-BE28: Implement GET /api/v1/health endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE03, TASK-BE10, TASK-BE11, TASK-BE14
**Description:** Health endpoint checking: DB connectivity, Redis connectivity, last scrape timestamp, last sentiment calculation timestamp, data freshness (seconds since last events). Returns composite status: "healthy", "degraded" (data stale), or "unhealthy" (DB/Redis down).
**Acceptance criteria:**
- Returns `HealthResponse` schema including `staleness_level: "fresh" | "warning" | "critical" | "unavailable"` per ticker using thresholds from `sse_common.constants` (30 min / 60 min / 4 hr)
- Checks DB and Redis connectivity
- Reports `last_scrape_time` and `last_sentiment_calc_time` as ISO 8601
- Returns `data_age_seconds` alongside `staleness_level` for precise frontend display
- Status logic: healthy if all up and data < 30 min old (`STALENESS_WARN_SECONDS`); degraded if stale or Redis down; unhealthy if DB down
- Never raises exceptions — always returns a response

---

### TASK-BE29: Implement data staleness tracking service
**Domain:** Backend / API
**Depends on:** TASK-BE11, TASK-BE28
**Description:** Create `backend/app/services/staleness.py` with `StalenessTracker` maintaining timestamps in Redis for key events: `sse:staleness:last_scrape`, `sse:staleness:last_sentiment_calc`, `sse:staleness:last_market_price_fetch`. Methods: `record_event(event_name)` and `get_staleness_report() -> dict`.
**Acceptance criteria:**
- Timestamps stored in Redis with `sse:staleness:` prefix
- `record_event` writes current UTC timestamp
- `get_staleness_report` returns dict with event names, timestamps, and seconds-since
- SSE stream includes staleness info in periodic heartbeat events

---

### TASK-BE30: Implement FastAPI lifespan events (startup/shutdown)
**Domain:** Backend / API
**Depends on:** TASK-BE10, TASK-BE11, TASK-BE25, TASK-BE36
**Description:** Implement the FastAPI `lifespan` async context manager in `main.py`. Startup sequence: initialize DB engine → Redis pool → SSEManager → `PricingEventSubscriber` (as background asyncio.Task). All stored on `app.state`. Shutdown: cancel subscriber task, close SSE connections, close Redis pool, dispose DB engine.
**Acceptance criteria:**
- DB engine created on startup, disposed on shutdown
- Redis pool created on startup, closed on shutdown (TASK-BE34)
- SSEManager created on startup, all connections closed on shutdown
- `PricingEventSubscriber` (TASK-BE36) started as background `asyncio.Task` stored on `app.state.pricing_subscriber_task`
- Lifespan shutdown cancels the subscriber task and awaits it (catches `asyncio.CancelledError` cleanly)
- Unexpected subscriber task exit logged at CRITICAL — does NOT auto-restart (surfaces to Uptime Kuma monitoring)
- All resources accessible via `request.app.state` or dependency injection
- Startup logs sanitized config summary at INFO level

---

### TASK-BE31: Create database user privilege SQL scripts
**Domain:** Backend / API
**Depends on:** TASK-BE04
**Description:** SQL scripts in `database/scripts/` setting up separate PostgreSQL users per service with minimal privileges: `sse_api` (SELECT all), `sse_scraper` (SELECT+INSERT on `reddit_raw`), `sse_processor` (SELECT on `reddit_raw`; SELECT+INSERT on `comment_sentiment`, `ticker_sentiment_snapshot`), `sse_pricing` (SELECT on sentiment/tickers/params/real_prices; SELECT+INSERT on `sentiment_prices`), `sse_admin` (ALL, for migrations).
**Acceptance criteria:**
- Scripts create all five users against the `reddit_raw` table (not `reddit_raw_data`)
- Each user has minimum required privileges only
- `sse_api` cannot INSERT or UPDATE anything
- Scripts are idempotent
- `database/scripts/README.md` explains the user permission model

---

### TASK-BE32: Add OpenAPI documentation customization
**Domain:** Backend / API
**Depends on:** TASK-BE03, TASK-BE14
**Description:** Customize FastAPI auto-generated OpenAPI docs: set title, description, version, contact info. Add endpoint grouping tags ("Tickers", "Health", "Streaming"). Ensure all endpoints have summary and description strings. Document error responses (404, 429, 500).
**Acceptance criteria:**
- `/docs` shows branded documentation
- Endpoints grouped by tags
- Each endpoint has summary and description
- Error responses documented with example bodies
- SSE endpoint notes it returns `text/event-stream`

---

### TASK-BE33: Integration test scaffolding for all API endpoints
**Domain:** Backend / API
**Depends on:** TASK-BE23, TASK-BE24, TASK-BE26, TASK-BE28, TASK-BE38
**Description:** Set up `pytest` with `pytest-asyncio` and `httpx` for async API testing. Create `conftest.py` with fixtures: test DB (testcontainers-python for PostgreSQL+TimescaleDB), test Redis, async API client. Write skeleton test files for each endpoint with descriptive function signatures.
**Acceptance criteria:**
- `pytest` and `pytest-asyncio` in dev dependencies
- `conftest.py` with async fixtures for DB, Redis, and API client
- Test files exist for: `test_tickers.py`, `test_ticker_detail.py`, `test_sse_stream.py`, `test_health.py`
- At minimum one working test: health endpoint returns 200 with expected schema
- `pyproject.toml` configures asyncio mode for pytest

---

### TASK-BE34: Redis connection pool configuration
**Domain:** Backend / API
**Depends on:** TASK-BE11, TASK-BE02
**Description:** Update `backend/app/db/redis.py` to initialize a `redis.asyncio.ConnectionPool` with configurable `max_connections`. Pool created in lifespan startup (TASK-BE30), stored on `app.state.redis_pool`. All Redis clients in the application share this pool.
**Acceptance criteria:**
- `redis.asyncio.ConnectionPool(max_connections=N, decode_responses=True)` where `N` is from `REDIS_MAX_CONNECTIONS` env var (default: 50)
- `Redis` client constructed from pool: `redis.asyncio.Redis(connection_pool=pool)`
- Pool created at lifespan startup, stored on `app.state.redis_pool`
- Pool closed at lifespan shutdown: `await pool.aclose()`
- `REDIS_MAX_CONNECTIONS` documented in `.env.example` with sizing note relative to uvicorn worker count
- Integration test: 50 concurrent `cache_get` calls all succeed without connection errors

---

### TASK-BE35: TimescaleDB continuous aggregate for 1-hour sentiment price buckets
**Domain:** Backend / API
**Depends on:** TASK-BE06
**Description:** Create a TimescaleDB continuous aggregate `sentiment_prices_1h` pre-computing 1-hour `time_bucket` aggregates automatically. Update the `GET /api/v1/tickers/{ticker}` endpoint (TASK-BE24) to query the aggregate for 1W and 1M timeframes instead of rescanning the raw hypertable.
**Acceptance criteria:**
- Migration adds the continuous aggregate:
  ```sql
  CREATE MATERIALIZED VIEW sentiment_prices_1h
  WITH (timescaledb.continuous) AS
  SELECT time_bucket('1 hour', time) AS bucket, ticker,
         last(sentiment_price, time) AS sentiment_price,
         last(real_price_at_calc, time) AS real_price
  FROM sentiment_prices GROUP BY bucket, ticker;

  SELECT add_continuous_aggregate_policy('sentiment_prices_1h',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
  ```
- TASK-BE24 endpoint selects from `sentiment_prices_1h` for `1W`/`1M`, raw `sentiment_prices` for `1D`
- Migration reversible (drops policy then view on downgrade)
- EXPLAIN plan for a 1W query shows index scan on aggregate, not sequential scan on raw hypertable

---

### TASK-BE36: Redis subscriber for `sse:pricing:run_complete`
**Domain:** Backend / API
**Depends on:** TASK-BE11, TASK-BE25, TASK-BE27
**Description:** Create `backend/app/subscriber.py` with `PricingEventSubscriber` class. Subscribes to Redis channel `sse:pricing:run_complete`. On message: parses JSON payload, reads latest prices from Redis cache (`sse:prices:current`), delegates to TASK-BE27 broadcast logic. Handles Redis disconnection with exponential backoff identical to the processor and pricing engine subscribers.
**Acceptance criteria:**
- `PricingEventSubscriber` in `backend/app/subscriber.py`
- Subscribes to `sse:pricing:run_complete` (constant from `sse_common.constants.CHANNEL_PRICING_DONE`)
- On message: parses JSON, reads `sse:prices:current` from Redis, calls `SSEManager.broadcast()` per ticker in `tickers_priced`
- On Redis disconnect: logs WARNING, retries with exponential backoff (1s → 60s cap)
- On invalid JSON: logs ERROR, does not crash, does not broadcast stale data
- Runs as a background `asyncio.Task` — does NOT block request handling
- Unit tests mock Redis and SSEManager; verify `SSEManager.broadcast` called once per ticker in `tickers_priced`; verify reconnect loop on simulated disconnect

---

### TASK-BE37: Auth-readiness dependency stub
**Domain:** Backend / API
**Depends on:** TASK-BE01
**Description:** Create `backend/app/auth.py` with a `get_current_user` FastAPI dependency stub that always returns `None` in V1. Inject into all API route handlers so that adding real auth later requires only replacing this function's implementation, not touching every route.
**Acceptance criteria:**
- `get_current_user(request: Request) -> None` in `backend/app/auth.py`
- Type annotation: `Optional[User]` where `User` is a placeholder dataclass `User(id: Optional[str] = None)`
- All API route handlers in TASK-BE23, TASK-BE24, TASK-BE26, TASK-BE28, TASK-BE38 accept `current_user: Optional[User] = Depends(get_current_user)` (even if unused)
- Stub has zero performance overhead (returns immediately)
- Code comment explains: "Replace `get_current_user` implementation to add JWT/session auth. No route changes needed."
- Existing unit tests unaffected

---

### TASK-BE38: Implement GET /api/v1/tickers/stream — global SSE endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE03, TASK-BE14, TASK-BE25
**Description:** Global SSE streaming endpoint at `GET /api/v1/tickers/stream`. Streams price updates for ALL active tickers to a single connection. Used by the homepage. Must be registered BEFORE `GET /api/v1/tickers/{ticker}/stream` in the router to prevent FastAPI from matching "stream" as a ticker symbol.
**Acceptance criteria:**
- Route path: `GET /api/v1/tickers/stream`
- Returns `text/event-stream` content type
- On connect: sends current prices for ALL active tickers as an initial `all_tickers_snapshot` event
- Subsequent events: per-ticker `price_update` events as new prices arrive via `SSEManager.broadcast_all()`
- Keepalive comments every 30 seconds to prevent proxy timeout
- Client disconnection detected and cleaned up from SSEManager
- Route registered before `/api/v1/tickers/{ticker}/stream` in router initialization — verified by a test that `GET /api/v1/tickers/stream` does not match the per-ticker route
- SSE event format: `event: price_update\ndata: {json}\n\n` matching `SSEPriceUpdate` schema

---

### TASK-BE39: Per-config scenario series on chart history endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE24, TASK-BE41
**Description:** Extend `GET /api/v1/tickers/{ticker}/history` with an optional `configs` query parameter that returns "what-if" sentiment price series computed from named pricing configurations (TASK-BE41). This powers the scenario comparison overlay on the Ticker Detail chart (TASK-FE28), letting users see side-by-side how different weighting concoctions would have priced a ticker over time.

**How it works:** The `sentiment_prices` table stores prices computed from the live/primary config. For alternative configs, the API re-applies each config's formula against the stored `ticker_sentiment_snapshot` rows (aggregate scores and volume weights already persisted) — no re-scraping or re-NLP needed. Formula: `sentiment_price = real_price + (agg_score_current - agg_score_prev) * volume_weight * sensitivity`, where `sensitivity` and other multipliers come from the config's `params` JSONB.

**Query parameter:**
- `configs: str | None` — comma-separated config slugs (e.g., `?configs=upvote-heavy,volume-heavy`). Default: omit field from response (primary config only). If provided, returns additional `scenario_series` field.
- Maximum 3 configs per request.
- Unknown slug → 422 with message listing all valid slugs from `pricing_configurations`.

**Response schema extension:**
```python
class ScenarioDataPoint(BaseModel):
    time: datetime
    sentiment_price: float  # what-if price under this config's formula

class HistoryResponse(BaseModel):
    # ... existing fields ...
    scenario_series: dict[str, list[ScenarioDataPoint]] | None = None
    # key = config slug, value = time-ordered list of what-if prices
```

**Query logic:**
1. Fetch `ticker_sentiment_snapshot` rows (same rows used by primary history query)
2. Fetch `real_prices` for the same time window
3. For each requested config: load its `params` JSONB from `pricing_configurations`, apply formula row-by-row to produce `sentiment_price = real_price + computed_delta`
4. Pair by nearest timestamp; return as `scenario_series[slug]`

**Acceptance criteria:**
- `GET /api/v1/tickers/TSLA/history?timeframe=1D` returns no `scenario_series` field (unchanged behavior)
- `GET /api/v1/tickers/TSLA/history?timeframe=1D&configs=upvote-heavy,volume-heavy` returns `scenario_series: {"upvote-heavy": [{time, sentiment_price}, ...], "volume-heavy": [...]}`
- Unknown config slug returns 422 with message listing valid slugs
- More than 3 configs returns 422
- `scenario_series` uses the same time range as the primary series
- `shift` parameter (TASK-BE40) applies to scenario series timestamps identically to the primary series
- Integration test: two configs with different `sensitivity` values produce diverging `sentiment_price` values for the same underlying snapshot data

---

### TASK-BE40: Time-shift (lag) parameter on chart history endpoint
**Domain:** Backend / API
**Depends on:** TASK-BE24, TASK-BE39
**Description:** Add a `shift` integer query parameter to `GET /api/v1/tickers/{ticker}/history` that offsets all sentiment data timestamps forward in time by N units. This enables the user to explore whether Reddit sentiment leads or lags stock price movements by a configurable amount. Applied to both the primary sentiment series and any `algorithm_series` from TASK-BE39.

**Shift semantics:** A positive `shift` moves sentiment timestamps FORWARD — i.e., a `shift=3` on a 1D chart means the sentiment signal from 3 hours ago is aligned with the current price. This answers "did sentiment 3 hours ago predict today's price?".

**Query parameter:**
- `shift: int = 0` — number of units to offset sentiment timestamps (default: 0 = no shift)
- Unit is inferred from `timeframe`:
  - `1D` → hours (range: 0 – 23)
  - `1W` → days (range: 0 – 6)
  - `1M` → days (range: 0 – 29)
- Out-of-range value → 422 with message: `"shift must be 0–{max} for timeframe {tf}"`
- Negative values → 422

**Implementation:**
- Sentiment timestamps shifted in the SQL query: `window_start + INTERVAL '{shift} hours'` (for 1D) or `+ INTERVAL '{shift} days'` (for 1W/1M). Applied to `ticker_sentiment_snapshot` queries.
- Price data timestamps are NOT shifted — only sentiment data moves.
- After shifting, some sentiment points may extend beyond the chart's time window; truncate to the same end-time boundary as the price series.

**Response metadata:**
```python
class HistoryResponse(BaseModel):
    # ... existing fields ...
    shift_applied: int      # mirrors the input shift value (0 if not specified)
    shift_unit: str         # "hours" | "days" — inferred from timeframe
```

**Acceptance criteria:**
- `GET /api/v1/tickers/TSLA/history?timeframe=1D&shift=3` returns sentiment timestamps each offset by +3 hours; price timestamps unchanged
- `shift=0` (default) produces identical results to omitting the parameter
- `shift=24` with `timeframe=1D` returns 422
- `shift=-1` returns 422
- Response always includes `shift_applied` and `shift_unit` fields (even when shift=0)
- `scenario_series` data (TASK-BE39) also has its timestamps shifted when `shift > 0`
- Unit test: given raw snapshots at T+0h, T+1h, T+2h and `shift=2`, returned timestamps are T+2h, T+3h, T+4h
- Integration test: `shift=1` with `timeframe=1W` shifts all sentiment points by 1 day, verified against DB fixture

---

### TASK-BE41: Named pricing configuration presets
**Domain:** Backend / API
**Depends on:** TASK-BE04, TASK-PRC03
**Description:** Introduce a `pricing_configurations` table storing named, versioned parameter sets for the pricing formula. This is the foundational data model for the scenario comparison feature (TASK-BE39, TASK-FE28). Each row is an independent "concoction" — a named combination of weighting coefficients that can be applied to historical sentiment snapshots to produce a what-if price series.

**Database schema (new migration):**
```sql
CREATE TABLE pricing_configurations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(64) UNIQUE NOT NULL,  -- URL-safe name, e.g. "upvote-heavy"
    name        VARCHAR(128) NOT NULL,        -- display name, e.g. "Upvote-Heavy"
    description TEXT,
    params      JSONB NOT NULL,              -- formula coefficients (see below)
    is_active   BOOLEAN DEFAULT TRUE,        -- soft-delete / hide from UI
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

**`params` JSONB structure** (all keys required; unknown keys ignored for forward-compatibility):
```json
{
  "sensitivity":                  1.0,   // overall delta magnitude multiplier
  "max_delta_pct":                0.10,  // max sentiment_delta as fraction of real_price
  "upvote_weight_multiplier":     1.0,   // scales engagement_weight() in NLP12
  "volume_scaling_function":      "log", // "log" | "sqrt" | "linear" (NLP15)
  "volume_weight_multiplier":     1.0,   // scales the computed volume_weight
  "min_mentions":                 3      // minimum post count to include ticker
}
```

**Seed data (migration includes 3 starter configs):**

| slug | name | key differences |
|---|---|---|
| `balanced` | Balanced | All multipliers at 1.0 — the default "live" config |
| `upvote-heavy` | Upvote-Heavy | `upvote_weight_multiplier: 2.0` — Reddit karma drives more of the signal |
| `volume-heavy` | Volume-Heavy | `volume_weight_multiplier: 2.0, volume_scaling_function: "linear"` — mention count amplified |

**Management API endpoint:**
- `GET /api/v1/pricing/configs` — returns all active configs: `[{ id, slug, name, description, params }]`
- No create/update/delete endpoints in V1 — configs are managed via DB migration only
- Response cached in Redis with 5-minute TTL (configs change rarely)

**Relationship to live pricing:** The live pricing engine (TASK-PRC03) reads its parameters from `pricing_parameters` (a separate config file / env vars). The `pricing_configurations` table is an analytical overlay — it does NOT affect live prices. The `balanced` seed row's params should match the live config defaults so users can see "Balanced = current live behavior."

**Acceptance criteria:**
- Migration creates table and seeds 3 rows; reversible (drops table on downgrade)
- `GET /api/v1/pricing/configs` returns all 3 seed configs with correct slugs and params
- `params` JSONB validated on read: missing required keys logged as WARNING, defaults substituted
- Slug column has UNIQUE index; `is_active=false` rows excluded from API response
- `balanced` seed row params match the live `pricing_parameters` defaults exactly
- Unit test: endpoint returns 3 items after migration; adding a 4th via direct DB insert appears in response after cache TTL

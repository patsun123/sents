# Sentiment Processor Service — Atomic Implementation Plan

## Domain: Standalone Service, Redis Pub/Sub, Pipeline Orchestration, Health Check

> This service wraps the NLP pipeline from `02_sentiment_analysis.md` in a runnable process
> that listens for scraper completion events and triggers sentiment analysis.
> Resolves CRITICAL-2 and part of CRITICAL-3 from gap analysis.

---

### TASK-PROC01: Project scaffolding and package structure
**Domain:** Sentiment Processor Service
**Depends on:** TASK-NLP19, TASK-NLP17
**Description:** Create the `processor/` directory with package structure: `processor/main.py` (entry point), `processor/subscriber.py`, `processor/runner.py`, `processor/health.py`, `processor/config.py`, `processor/db/`, `processor/tests/`. Create `pyproject.toml` with dependencies: redis, psycopg2-binary (or asyncpg), httpx, structlog, uvicorn. The processor imports sentiment pipeline modules from a shared path or installed package.
**Acceptance criteria:**
- `pip install -e .` succeeds in a clean virtualenv
- `python -m processor.main` starts without import errors (exits cleanly if DB/Redis unavailable)
- Config loaded from environment variables with documented defaults
- `processor/` is independent of `backend/` — no imports from `backend.app.*`
- Shares sentiment pipeline code via a common installed package (e.g., `sse-sentiment`) or sys.path configuration

---

### TASK-PROC02: Service configuration and environment variables
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC01
**Description:** Create `processor/config.py` using pydantic-settings `BaseSettings`. Required variables: `DATABASE_URL`, `REDIS_URL` (optional), `POLL_INTERVAL_SECONDS` (default: 300), `SENTIMENT_CONFIG_PATH` (path to sentiment YAML config from TASK-NLP17), `HEALTH_PORT` (default: 8081), `LOG_LEVEL` (default: INFO).
**Acceptance criteria:**
- Missing `DATABASE_URL` raises clear error at startup
- Missing `REDIS_URL` logs WARNING and enables poll-only mode
- All defaults documented in `.env.example` section for processor
- Config is a singleton, importable from `processor.config`

---

### TASK-PROC03: Redis subscriber for `sse:scraper:run_complete`
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC02
**Description:** Implement `processor/subscriber.py` with a `ScraperEventSubscriber` class subscribing to Redis pub/sub channel `sse:scraper:run_complete`. On receiving a message, parses JSON payload (`run_id`, `items_stored`, `timestamp`, `subreddits`) and invokes a callback. Handles Redis disconnection with automatic reconnection using exponential backoff (max 60s).
**Acceptance criteria:**
- Subscribes to `sse:scraper:run_complete` channel
- Parses JSON payload and validates required fields
- Invokes registered callback with parsed payload
- On Redis disconnect: logs WARNING, retries with exponential backoff (1s, 2s, 4s, ... 60s cap)
- On invalid JSON: logs ERROR with raw message, does not crash
- Unit tests mock Redis and verify callback invocation with correct payload
- Unit tests verify reconnection logic on simulated disconnect

---

### TASK-PROC04: Database query for unprocessed reddit_raw rows
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC02, TASK-NLP18
**Description:** Implement `processor/db/queries.py` with `fetch_unprocessed_items(db_conn, since_timestamp) -> list[RawComment]` querying `reddit_raw` for rows where `timestamp > since_timestamp` and whose `(reddit_id, ticker_mentioned)` does not exist in `comment_sentiment`. Also implement `get_last_processed_timestamp(db_conn) -> Optional[datetime]` reading the max `analyzed_at` from `comment_sentiment`.
**Acceptance criteria:**
- Query uses LEFT JOIN or NOT EXISTS subquery to find unprocessed items
- Returns `RawComment` objects compatible with `run_sentiment_pipeline()` input
- `get_last_processed_timestamp` returns `None` if `comment_sentiment` is empty
- Both queries use parameterized statements
- Performance: query completes in under 500ms for 100K rows (verified by EXPLAIN plan)
- Unit tests mock DB and verify correct SQL construction

---

### TASK-PROC05: Pipeline runner — bridge between subscriber and sentiment pipeline
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC03, TASK-PROC04, TASK-NLP19
**Description:** Implement `processor/runner.py` with `SentimentPipelineRunner` class. On trigger, it: (1) queries unprocessed items via TASK-PROC04, (2) extracts unique tickers, (3) loads sentiment config via TASK-NLP17, (4) calls `run_sentiment_pipeline()` from TASK-NLP19, (5) records run result. Tracks `last_run_timestamp`, `last_run_items_count`, `last_run_tickers` for health reporting.
**Acceptance criteria:**
- Calls `run_sentiment_pipeline()` with correct arguments
- Handles zero unprocessed items gracefully (logs INFO "No new items", does not call pipeline)
- Failed pipeline execution logs ERROR with traceback, does not crash the service
- Updates internal state: `last_run_at`, `items_analyzed`, `tickers_processed`
- Logs at INFO: run start, items found, tickers extracted, pipeline duration, items analyzed
- Unit tests mock pipeline and DB, verify correct orchestration sequence

---

### TASK-PROC06: Redis publisher for `sse:sentiment:run_complete`
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC05
**Description:** After `SentimentPipelineRunner` completes a successful run, publish a JSON message to Redis channel `sse:sentiment:run_complete`. Payload: `{"run_id": "<uuid>", "tickers_processed": ["TSLA", ...], "items_analyzed": 42, "timestamp": "2026-03-01T12:00:00Z"}`. If Redis is unavailable, log WARNING and continue (same resilience pattern as TASK-S20).
**Acceptance criteria:**
- Publishes to `sse:sentiment:run_complete` after each successful pipeline run
- Payload contains all four fields with correct types
- `run_id` is a UUID4 generated at run start
- `timestamp` is ISO 8601 UTC
- If Redis unavailable: logs WARNING, does not raise, does not abort
- If pipeline produced zero results: still publishes with `items_analyzed: 0`
- Channel name is a constant in shared constants module
- Unit tests verify: correct payload on success, graceful skip on Redis failure

---

### TASK-PROC07: Poll-based fallback trigger
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC04, TASK-PROC05
**Description:** Implement `processor/poller.py` with `DatabasePoller` checking periodically for unprocessed data when Redis is unavailable. Runs every `POLL_INTERVAL_SECONDS` (default: 300). On each poll: calls `get_last_processed_timestamp()`, then `fetch_unprocessed_items()`. If items found, triggers `SentimentPipelineRunner`. Resets its timer when Redis subscriber triggers a run.
**Acceptance criteria:**
- Polls every `POLL_INTERVAL_SECONDS` (configurable, default 300)
- Skips poll if a pipeline run is already in progress (mutex/lock)
- Resets poll timer when Redis subscriber triggers a run (avoids redundant processing)
- Runs as a background asyncio task alongside the subscriber
- If both Redis and poll detect new data simultaneously, only one run executes
- Logs at DEBUG each poll check; logs at INFO when poll triggers a run
- Unit tests verify: poll triggers on schedule, poll skipped during active run, timer reset on Redis trigger

---

### TASK-PROC08: Health check HTTP endpoint
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC05
**Description:** Implement `processor/health.py` — a minimal HTTP server (using uvicorn or aiohttp) serving `GET /health` on configurable port (default 8081). Returns JSON: `status` ("ok"/"degraded"/"down"), `last_run_at`, `items_analyzed`, `tickers_processed`, `seconds_since_last_run`, `redis_connected`, `mode` ("event_driven"/"poll_only").
**Acceptance criteria:**
- `GET /health` returns HTTP 200 with JSON body when service is running
- `status: "ok"` when last run within 2× expected interval and Redis connected
- `status: "degraded"` when Redis disconnected (poll-only mode) or last run is stale
- `status: "down"` when no successful run ever completed and service up > 10 minutes
- Health server starts within 2 seconds
- Does not block subscriber or poller
- Unit tests verify all three status cases

---

### TASK-PROC09: Main entry point and graceful shutdown
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC03, TASK-PROC05, TASK-PROC06, TASK-PROC07, TASK-PROC08
**Description:** Implement `processor/main.py` as the service entry point (`python -m processor.main`). Startup: load config → init DB pool → init Redis (if configured) → start health server → start Redis subscriber → start DB poller → run event loop. Shutdown on SIGTERM/SIGINT: stop accepting new events, wait for in-progress run (up to 120s), close connections, exit 0.
**Acceptance criteria:**
- `python -m processor.main` starts all components
- Startup sequence logged at INFO with component status
- SIGTERM triggers graceful shutdown within 30 seconds
- In-progress pipeline run allowed to complete (up to 120s timeout)
- If pipeline exceeds shutdown timeout: force-cancel and log WARNING
- DB and Redis connections closed cleanly
- Exit code 0 on graceful shutdown, 1 on unhandled error
- Works in both event-driven and poll-only modes

---

### TASK-PROC10: Structured logging for Sentiment Processor
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC01
**Description:** Configure structured JSON logging consistent with other services (TASK-S25, TASK-OPS27). Every log entry includes: `service: "processor"`, `run_id` (during pipeline runs), `timestamp`, `level`. Format compatible with Docker json-file log driver.
**Acceptance criteria:**
- All log calls use structured logger (no bare `print()`)
- `run_id` threaded through all log entries during a pipeline run
- Log level configurable via `LOG_LEVEL` env var
- JSON output format compatible with Docker json-file log driver
- Startup banner logs config summary (sanitized — no credentials) and mode

---

### TASK-PROC11: Dockerfile reference and integration with TASK-OPS06
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC09, TASK-OPS06
**Description:** Verify the Dockerfile from TASK-OPS06 correctly builds and runs the processor service. Entry point: `CMD ["python", "-m", "processor.main"]`. Health check: `CMD curl -f http://localhost:8081/health || exit 1`.
**Acceptance criteria:**
- `docker build -f processor/Dockerfile .` succeeds
- `docker run` starts the service and health endpoint responds on port 8081
- Non-root user `app_processor` used (per TASK-OPS03)
- All NLP dependencies installed (VADER, TextBlob, optionally transformers)
- Container size documented (target: < 1.5GB without FinBERT, < 3GB with)

---

### TASK-PROC12: Integration test — full event-driven cycle
**Domain:** Sentiment Processor Service
**Depends on:** TASK-PROC09
**Description:** Integration test (`processor/tests/integration/test_event_cycle.py`) exercising: Redis publishes `sse:scraper:run_complete` → processor picks up event → queries test DB for fixture data → runs sentiment pipeline → writes to `comment_sentiment` and `ticker_sentiment_snapshot` → publishes `sse:sentiment:run_complete`.
**Acceptance criteria:**
- Marked `@pytest.mark.integration`, skipped unless `RUN_INTEGRATION_TESTS=true`
- Fixture: 10 `reddit_raw` rows across 3 tickers pre-inserted in test DB
- Asserts: `comment_sentiment` rows created, `ticker_sentiment_snapshot` rows created
- Asserts: `sse:sentiment:run_complete` published with correct payload
- Asserts: health endpoint reports successful run
- Test DB and Redis torn down after run (no state leakage)

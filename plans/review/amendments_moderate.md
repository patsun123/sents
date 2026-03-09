# Moderate Amendments to Existing Plans
# SSE — Sentiment Stock Exchange
# Covers: RISK-5, RISK-6, RISK-7, RISK-8, MODERATE-5, MODERATE-6, MODERATE-7,
#         MODERATE-8, MODERATE-9, ARCH-2, ARCH-3, AMBIG-1, AMBIG-2, AMBIG-3, AMBIG-4

> This document records confirmed findings and their resolutions.
> Existing plan files are NOT rewritten — this file is the amendment record.
> All findings confirmed by reading the actual task IDs cited.

---

## 1. Confirmation of Findings

### RISK-5: Rate Limiting Duplication
**Tasks checked:** TASK-BE12, TASK-OPS19
**Finding:** TASK-BE12 (`03_backend_api.md`) implements rate limiting via `slowapi` as a FastAPI middleware. TASK-OPS19 (`05_infrastructure.md`) defines a separate Nginx-level rate limit. Both apply to the same requests. The Nginx one is a blunt instrument with no per-IP logic; the app-level one (slowapi) is more precise and already accounts for the SSE endpoint.
**CONFIRMED**

---

### RISK-6: No Schema Evolution Strategy
**Tasks checked:** TASK-BE04, TASK-S02, TASK-OPS14
**Finding:** Alembic is mentioned in TASK-BE04 for backend migrations. TASK-S02 defines DDL statements directly in the scraper plan. TASK-OPS14 mentions PostgreSQL setup but no shared migration directory. There is no documented Alembic configuration, autogenerate setup, or rollback procedure. Multiple services own overlapping schema definitions.
**CONFIRMED**

---

### RISK-7: Logging Defined Three Times
**Tasks checked:** TASK-S25, TASK-OPS18, TASK-OPS27, TASK-PROC10, TASK-PRC14
**Finding:** TASK-S25 defines structured logging for the scraper. TASK-OPS18 defines a log rotation policy. TASK-OPS27 defines log aggregation with a sidecar. TASK-PROC10 and TASK-PRC14 each re-define the same JSON logging setup. Five tasks define logging independently. No shared package or configuration exists.
**CONFIRMED**

---

### RISK-8: No Load Testing
**Tasks checked:** TASK-OPS23, TASK-OPS24, TASK-OPS30
**Finding:** TASK-OPS23 defines Uptime Kuma monitoring. TASK-OPS24 defines a monitoring runbook. TASK-OPS30 is a security checklist. None of these tasks establish a baseline performance profile or test concurrent SSE connections before go-live. The system has no verified capacity limit.
**CONFIRMED**

---

### MODERATE-5: No Initial Sentiment Price Seeding
**Tasks checked:** TASK-BE19, TASK-BE21, TASK-NLP16
**Finding:** TASK-NLP16 defines `compute_sentiment_price_delta()` which handles `previous=None`, but the initial return value is unspecified. The pricing formula receives no real price anchor on first boot. A user seeing the homepage on day one would see no data.
**CONFIRMED — Partially resolved by TASK-PRC11 in `02c_pricing_engine_service.md`**
(TASK-PRC11 sets `sentiment_price = real_price` when `previous=None`)

---

### MODERATE-6: No Market Price Fetching Scheduler
**Tasks checked:** TASK-BE16, TASK-BE17, TASK-BE18, TASK-BE21
**Finding:** TASK-BE16/17 implement yfinance and Finnhub providers. TASK-BE18 is the provider factory. TASK-BE21 calls the provider during a pricing cycle. But no task schedules periodic real price fetches independently of the pricing cycle — real prices are only updated when sentiment pricing runs.
**CONFIRMED — Resolved by TASK-PRC10 in `02c_pricing_engine_service.md`**
(TASK-PRC10 adds `RealPriceFetcher` that fetches every 5 min during NYSE hours)

---

### MODERATE-7: SSE Endpoint Path Inconsistency
**Tasks checked:** TASK-BE25, TASK-BE26, TASK-FE15, TASK-FE16
**Finding:** TASK-BE26 defines `GET /api/v1/tickers/{ticker}/stream` (per-ticker SSE). TASK-FE15 hook `useSSEPrices` connects to `/api/v1/tickers/stream` (global, no ticker param). These two paths are different endpoints. Neither the backend plan nor the frontend plan explicitly defines the global endpoint. TASK-BE25 (SSEManager) does not specify which endpoints it serves.
**CONFIRMED**

---

### MODERATE-8: No Duplicate Content Detection
**Tasks checked:** TASK-S17, TASK-S15, TASK-S18
**Finding:** TASK-S17 defines data quality filtering: spam heuristics (regex keyword matching), score thresholds, text length checks. There is no fingerprinting or near-duplicate detection. A copy-pasted pump message posted to 4 subreddits simultaneously would pass through as 4 distinct posts, artificially amplifying its sentiment signal.
**CONFIRMED**

---

### MODERATE-9: No Auth-Readiness Hooks
**Tasks checked:** TASK-BE01, TASK-BE05, TASK-BE29, TASK-FE01
**Finding:** Spec §4.7 explicitly says "no accounts in v1 but architecture should consider them." No task adds a `get_current_user` stub, reserves the `users` table name, or adds nullable `user_id` fields to schemas. Adding auth later would require touching every API endpoint.
**CONFIRMED**

---

### ARCH-2: Dual Schema Definitions
**Tasks checked:** TASK-S02, TASK-BE04
**Finding:** TASK-S02 (`01_scraping_pipeline.md`) creates `reddit_raw` with DDL embedded in the scraper plan. TASK-BE04 (`03_backend_api.md`) creates `reddit_raw_data` with different column types, a different name, and an Alembic migration. These are the same table with two different owners. The composite unique constraint amendment (CRITICAL-4) must be applied to whichever survives.
**CONFIRMED**

---

### ARCH-3: Async vs Sync DB Drivers Undocumented
**Tasks checked:** TASK-S06, TASK-S07, TASK-BE08, TASK-PROC01, TASK-PRC01
**Finding:** The scraper uses `psycopg2` (sync, `pyproject.toml` in TASK-S01). The backend uses `asyncpg` via SQLAlchemy async (TASK-BE08). The processor and pricing service each specify `psycopg2-binary` or `asyncpg` in their scaffolding tasks but do not document the architectural decision or its implications. No shared ORM models exist between services.
**CONFIRMED** (intentional design but undocumented)

---

### AMBIG-1: Sentiment Price Base Value
**Tasks checked:** TASK-NLP16, TASK-BE20, TASK-BE21
**Finding:** TASK-NLP16 computes `sentiment_delta`. TASK-BE20 applies temporal decay and volume weighting. Neither task defines how `sentiment_price` is calculated from `sentiment_delta`. The spec says "sentiment-derived price" but never defines the mathematical relationship to real price.
**CONFIRMED**

---

### AMBIG-2: Multi-Ticker Post Handling
**Tasks checked:** TASK-S04, TASK-S02, TASK-BE04, TASK-S15
**Finding:** Spec §5.5 defines `ticker_mentioned` as `string` (singular). TASK-S04 defines `List[str]`. This ambiguity has cascading effects on deduplication, DB schema, and all downstream queries.
**CONFIRMED — Resolved by `amendments_critical.md` (CRITICAL-4)**
(One row per ticker; UNIQUE constraint on `(reddit_id, ticker_mentioned)`)

---

### AMBIG-3: Score Update → Sentiment Recomputation
**Tasks checked:** TASK-S03, TASK-NLP14, TASK-NLP19, TASK-PROC05
**Finding:** TASK-S03 upserts scores on re-scrape via `ON CONFLICT DO UPDATE`. If a post's upvote score changes from 50 to 500, the stored sentiment was computed using the old magnitude weight. No task specifies whether the sentiment pipeline should recompute on score change, or use the latest score at the time of the next scheduled run.
**CONFIRMED**

---

### AMBIG-4: Maximum Stale Data Age Thresholds
**Tasks checked:** TASK-BE28, TASK-FE22
**Finding:** TASK-BE28 (staleness tracker) exposes `is_stale` as a boolean with no defined threshold. TASK-FE22 (staleness indicator) mentions showing a staleness indicator but defines no color coding or hide logic. The spec says "hold last price, show staleness indicator" but provides no time values.
**CONFIRMED**

---

## 2. Resolutions

### Amendment for RISK-5: Supersede TASK-OPS19
**File:** `05_infrastructure.md`
**Change:** TASK-OPS19 is superseded by TASK-BE12

**Before:** TASK-OPS19 defines Nginx rate limiting as an infra concern.

**After:** TASK-OPS19 is SUPERSEDED. Rate limiting is entirely the application's concern (TASK-BE12 using `slowapi`). The Nginx config (TASK-OPS15) should NOT include `limit_req_zone` or `limit_req` directives — doing so creates double-counting where legitimate requests can be rejected by Nginx before the app's own logic runs.

In `05_infrastructure.md`, mark TASK-OPS19: `[SUPERSEDED → TASK-BE12: app-level rate limiting via slowapi]`

In TASK-OPS30 (security checklist), replace "verify Nginx rate limiting" with "verify API rate limiting returns HTTP 429 with `Retry-After` header" (test against the app, not Nginx).

---

### New Task TASK-MGMT01: Shared database migrations directory
**Resolves:** RISK-6
**File:** New task; references `03_backend_api.md`

**Description:** Establish a single canonical location for all DDL: `database/migrations/`. Configure Alembic (`backend/alembic.ini`, `backend/alembic/env.py`) to generate migrations under `../../database/migrations/` (relative to backend root). All schema changes — whether originally in the scraper plan, backend plan, or any service plan — are implemented ONLY as Alembic migration files here.

**Rules:**
1. No raw DDL `CREATE TABLE` statements in application startup code. All schema is migration-managed.
2. Every migration must be backward-compatible:
   - Add columns as nullable (or with a default) — never NOT NULL without a default
   - Never rename a column in place — add new column, migrate data, drop old column in a later migration
   - Never drop a column in the same migration that removes its application code reference
3. Migration naming: `YYYYMMDD_HHMMSS_{description}.py` (e.g., `20260301_120000_add_composite_unique_reddit_raw.py`)
4. Each migration must have a working `downgrade()` function
5. Rollback procedure documented in migration header comments

**Canonical table name decisions** (resolves ARCH-2 conflict):
- Table is named `reddit_raw` (from scraper plan, matches spec §5.5)
- TASK-BE04 in `03_backend_api.md` amended to use `reddit_raw` — NOT `reddit_raw_data`
- The UNIQUE constraint on `(reddit_id, ticker_mentioned)` (from CRITICAL-4 amendments) is the authoritative constraint

**Acceptance criteria:**
- `database/migrations/` directory exists with an initial migration creating all tables
- `alembic upgrade head` from a clean DB creates the full schema without errors
- `alembic downgrade base` cleanly reverses all migrations
- No `CREATE TABLE` statements exist in application startup/lifespan code for schema-managed tables
- TASK-S02 in `01_scraping_pipeline.md` marked: `[SUPERSEDED → database/migrations/ via TASK-MGMT01]`
- TASK-BE04 in `03_backend_api.md` marked: `[TABLE RENAMED: reddit_raw_data → reddit_raw. Migrations in database/migrations/]`

---

### New Task TASK-MGMT02: sse-common shared Python package
**Resolves:** RISK-7
**File:** New task; references `01_scraping_pipeline.md`, `02b_sentiment_processor_service.md`, `02c_pricing_engine_service.md`, `03_backend_api.md`

**Description:** Create a `sse-common/` package at repo root containing shared utilities. All four application services depend on it. Package contents:

`sse_common/logging_config.py`:
- `configure_logging(service_name: str, log_level: str) -> None`
- Configures structlog with JSON renderer (Docker json-file compatible)
- Injects `service`, `timestamp`, `level` into every log entry
- Accepts `log_level` from env var

`sse_common/constants.py`:
- Redis channel names: `CHANNEL_SCRAPER_DONE = "sse:scraper:run_complete"`, `CHANNEL_SENTIMENT_DONE = "sse:sentiment:run_complete"`, `CHANNEL_PRICING_DONE = "sse:pricing:run_complete"`
- Redis key patterns: `CACHE_PRICES_CURRENT = "sse:prices:current"`, `CACHE_TICKER_LATEST = "sse:ticker:{symbol}:latest"`
- Staleness thresholds (from AMBIG-4 resolution): `STALENESS_WARN_SECONDS = 1800`, `STALENESS_CRITICAL_SECONDS = 3600`, `STALENESS_HIDE_SECONDS = 14400`

`sse_common/env.py`:
- `require_env(key: str) -> str` — raises `ValueError` with clear message if missing
- `optional_env(key: str, default: str) -> str`

**Acceptance criteria:**
- `pip install -e sse-common/` succeeds
- All four services import from `sse_common` (not from each other's packages)
- TASK-S25 in `01_scraping_pipeline.md` marked: `[SUPERSEDED → use sse_common.logging_config]`
- TASK-OPS18 in `05_infrastructure.md` (log rotation) remains — it is infra-level and not superseded
- TASK-OPS27 in `05_infrastructure.md` (log aggregation sidecar) remains — it is infra-level
- TASK-PROC10 in `02b_sentiment_processor_service.md` amended: call `configure_logging("processor", ...)` from `sse_common`
- TASK-PRC14 in `02c_pricing_engine_service.md` amended: call `configure_logging("pricing", ...)` from `sse_common`
- Redis channel name constants used in all pub/sub tasks — no raw string literals

---

### New Task TASK-MGMT03: Load testing with Locust
**Resolves:** RISK-8
**File:** New task; references `05_infrastructure.md`

**Description:** Create `load_tests/locustfile.py` defining a load test scenario. Scenarios:
1. **REST load:** 50 concurrent virtual users hitting `GET /api/v1/tickers` every 2s (simulates homepage)
2. **SSE connections:** 20 concurrent SSE connections to `GET /api/v1/tickers/stream` held open for 60s each, counting events received
3. **Detail page:** 20 concurrent users hitting `GET /api/v1/tickers/{ticker}` for random tickers from the active list

Run against the Docker Compose stack on the target droplet before go-live. Document baseline in `docs/performance-baseline.md`.

**Target thresholds** (fail load test if exceeded):
- REST endpoints: p50 < 100ms, p95 < 500ms, p99 < 1000ms at 50 concurrent users
- SSE connections: 20 concurrent clients sustained for 60s without server-side disconnect
- Error rate: < 0.1% of requests return 5xx

**Acceptance criteria:**
- `locust -f load_tests/locustfile.py --headless -u 50 -r 5 --run-time 2m --host http://localhost` runs without Python errors
- Locust added to `requirements-dev.txt` (not a service dependency)
- Target thresholds defined as assertions in locustfile (fail fast if exceeded)
- `make load-test` target added to Makefile (TASK-CI11)
- Results documented in `docs/performance-baseline.md` after first successful run on target hardware
- Load test is NOT part of CI (runs manually before release, documented in deploy runbook TASK-OPS29)

---

### Amendment for MODERATE-5: Initial sentiment price seeding
**Status:** RESOLVED BY TASK-PRC11 in `02c_pricing_engine_service.md`

TASK-PRC11 defines: when `PricingService.calculate_sentiment_price()` receives `previous=None` (first boot), `sentiment_price` is set equal to the most recent `real_price` for that ticker. If no real price exists yet, the ticker is excluded from the homepage until both are available.

No additional amendments needed to existing tasks. TASK-NLP16 in `02_sentiment_analysis.md` should be annotated: `[Bootstrap behavior on previous=None defined in TASK-PRC11]`

---

### Amendment for MODERATE-6: Market price fetching scheduler
**Status:** RESOLVED BY TASK-PRC10 in `02c_pricing_engine_service.md`

TASK-PRC10 defines `RealPriceFetcher` in the Pricing Engine service: fetches batch real prices every `MARKET_HOURS_FETCH_INTERVAL_SECONDS` (default: 300) during NYSE hours, idles outside market hours. Writes to `real_prices` hypertable and updates Redis cache.

No additional amendments needed. TASK-BE18 (provider factory) in `03_backend_api.md` should be annotated: `[Provider also used by TASK-PRC10 in pricing service — no API server scheduling needed]`

---

### Amendment for MODERATE-7: Both SSE endpoints explicitly defined
**File:** `03_backend_api.md`
**Change:** TASK-BE26 amended; global SSE endpoint added

**Before:** TASK-BE26 defines only `GET /api/v1/tickers/{ticker}/stream` (per-ticker).

**After:** Two SSE endpoints are defined:

**Endpoint 1 — Global stream (add as new task or expand TASK-BE26):**
- `GET /api/v1/tickers/stream`
- Streams updates for ALL active tickers
- Event format: `data: {"type":"price_update","ticker":"TSLA","sentiment_price":212.34,"real_price":210.00,"divergence":2.34,"timestamp":"2026-03-01T12:00:00Z"}`
- Used by: homepage (`useSSEPrices` hook in TASK-FE15)
- SSEManager broadcasts to this endpoint via `SSEManager.broadcast_all()`

**Endpoint 2 — Per-ticker stream (existing TASK-BE26):**
- `GET /api/v1/tickers/{ticker}/stream`
- Streams updates for a single ticker
- Event format: same schema as global but filtered to one ticker
- Used by: detail page (`useTickerSSE(ticker)` hook added by TASK-PERF06 in amendments_performance.md)
- SSEManager broadcasts to this endpoint via `SSEManager.broadcast(ticker, data)`

**Route ordering note:** In FastAPI, `/tickers/stream` must be registered BEFORE `/tickers/{ticker}/stream` to prevent FastAPI from treating "stream" as a ticker symbol. Use explicit route ordering in the router or prefix the global endpoint differently.

**Frontend reconciliation:**
- TASK-FE15 `useSSEPrices` hook connects to `/api/v1/tickers/stream` (global) — CORRECT, no change needed
- Per-ticker SSE hook (TASK-PERF06 in amendments_performance.md) connects to `/api/v1/tickers/{ticker}/stream` — CORRECT
- TASK-FE16 (SSE integration on detail page) should use the per-ticker endpoint — amend if it references the global endpoint

---

### Amendment for MODERATE-8: Near-duplicate content detection
**File:** `01_scraping_pipeline.md`
**Change:** TASK-S17 expanded with fingerprinting

**Before:** TASK-S17 filters by spam keywords (regex), minimum score, minimum text length, author blacklist.

**After:** Add a 6th filter step: **content fingerprinting for near-duplicate detection.**

Implementation in `scraper/pipeline/quality_filter.py`:
```python
import hashlib

def content_fingerprint(text: str) -> str:
    """SHA-256 of first 200 chars (normalized: lowercase, whitespace collapsed)."""
    normalized = " ".join(text[:200].lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
```

Filter logic:
1. Compute fingerprint for each item's `source_text`
2. Check `reddit_raw` for any row with the same fingerprint in the last `DUPLICATE_WINDOW_HOURS` (default: 24)
3. If a duplicate exists from a DIFFERENT `reddit_id` (cross-posted content), mark the newer item as `is_duplicate = True`
4. Items marked `is_duplicate = True` are excluded from sentiment pipeline input
5. Items with the SAME `reddit_id` (score updates) are NOT duplicates — they are upserts

**Schema change** (add to migration in `database/migrations/`):
```sql
ALTER TABLE reddit_raw ADD COLUMN content_fingerprint VARCHAR(64);
ALTER TABLE reddit_raw ADD COLUMN is_duplicate BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX ON reddit_raw (content_fingerprint, created_at)
    WHERE is_duplicate = FALSE;
```

**Config key:** `DUPLICATE_WINDOW_HOURS` (default: 24, env var)

**Acceptance criteria:**
- `content_fingerprint()` tested with known near-duplicate texts
- Cross-posted identical text detected when fingerprints match across different `reddit_id` values
- Score updates (same `reddit_id`) never flagged as duplicates
- `is_duplicate` column indexed for fast filter in sentiment pipeline query (TASK-PROC04)
- Deduplication stats logged at INFO after each scrape run

---

### Amendment for MODERATE-9: Auth-readiness stubs
**File:** `03_backend_api.md`
**Change:** Add auth stub task

**New task (insert after TASK-BE01 scaffolding):**

**TASK-BE-AUTH-STUB: Optional authentication dependency stub**
- Create `backend/app/auth.py` with `get_current_user(request: Request) -> None` that always returns `None` in V1
- Type: `Optional[User]` where `User` is a placeholder dataclass with `id: Optional[str] = None`
- Import and inject this dependency into all API route handlers as `current_user: Optional[User] = Depends(get_current_user)`
- Adding real auth later = replacing `get_current_user` implementation only, no route changes
- Add comment to `database/migrations/` initial migration: `-- users table reserved for future auth. Do not use this name.`
- Add `user_id VARCHAR REFERENCES users(id)` as nullable column stubs where relevant (none in V1 — leave commented out)
- Document in `docs/architecture.md`: "Auth is intentionally stubbed. Replace `get_current_user` to add JWT/session auth."

**Acceptance criteria:**
- All API route handlers accept `current_user` dependency (even if unused)
- `get_current_user` returns `None` in V1 with no overhead
- Auth stub does not affect any existing test
- `users` table name reserved in schema comments

---

### Amendment for ARCH-2: Single schema source of truth
**Files:** `01_scraping_pipeline.md`, `03_backend_api.md`
**Change:** Canonical table name, migration ownership

**Canonical decision:**
- Table name: `reddit_raw` (matches spec §5.5 notation, matches scraper plan)
- Schema ownership: `database/migrations/` (TASK-MGMT01 above)
- All foreign keys from `comment_sentiment`, `ticker_sentiment_snapshot` reference `reddit_raw`

**Amendments:**
- TASK-S02 in `01_scraping_pipeline.md`: `[SUPERSEDED → table created by Alembic migration in database/migrations/. Scraper references schema, does not own it. Table name: reddit_raw]`
- TASK-BE04 in `03_backend_api.md`: `[TABLE NAME CHANGED: reddit_raw_data → reddit_raw. Migration moved to database/migrations/. Unique constraint changed to (reddit_id, ticker_mentioned) per CRITICAL-4 amendment]`
- NLP plan references to `reddit_raw_data` (if any): update to `reddit_raw`

**No other functional changes** — this is purely a naming and ownership clarification.

---

### Amendment for ARCH-3: Document async vs sync driver choice
**Files:** `01_scraping_pipeline.md`, `03_backend_api.md`, `02b_sentiment_processor_service.md`, `02c_pricing_engine_service.md`

**Add the following note to the scaffolding task of each service:**

```
# Architecture Decision Record: DB Driver Choice
# ADR-001: Each service uses the DB driver appropriate for its execution model.
#   - scraper/: psycopg2 (sync) — scraping is inherently I/O-bound with
#     sequential fallback logic; sync driver is simpler and sufficient.
#   - backend/: asyncpg via SQLAlchemy async — FastAPI is async-first;
#     asyncpg avoids blocking the event loop on DB calls.
#   - processor/: psycopg2 (sync) — pipeline runs as a one-shot batch job,
#     not a concurrent server; sync is simpler.
#   - pricing/: asyncpg or psycopg2 — either is acceptable. Use psycopg2
#     unless performance profiling shows a bottleneck.
# No ORM models are shared between services. Each service has its own
# DB interface layer. Sharing models would couple service deployments.
```

This note should appear in:
- TASK-S01 (scraper scaffolding)
- TASK-BE01 or TASK-BE08 (backend DB setup)
- TASK-PROC01 (processor scaffolding)
- TASK-PRC01 (pricing scaffolding)

Full ADR written to `docs/adr/ADR-001-db-driver-choice.md`.

---

### Resolution for AMBIG-1: Sentiment price formula codified
**Files:** `02_sentiment_analysis.md`, `02c_pricing_engine_service.md`

**Canonical formula:**
```
sentiment_price = real_price + sentiment_delta
divergence = sentiment_price - real_price = sentiment_delta
```

Where `sentiment_delta` is the output of `compute_sentiment_price_delta()` (TASK-NLP16), subject to temporal decay, volume weighting, score magnitude weighting, dampening, and per-ticker sensitivity (TASK-PRC04).

**Rationale:** Anchoring sentiment price to real price means:
1. On first boot, divergence = 0 (clean start)
2. If sentiment pipeline is down, `sentiment_price` tracks real price (safe fallback)
3. Divergence is directly meaningful to users (not an abstract index)
4. The formula is simple to explain: "we add market sentiment to the real price"

**Amendments:**
- TASK-NLP16 in `02_sentiment_analysis.md`: add to acceptance criteria: "`compute_sentiment_price_delta()` returns a signed Decimal representing the additive delta. This is NOT a standalone price — it is added to real_price to produce sentiment_price.`"
- TASK-PRC05 in `02c_pricing_engine_service.md`: add to acceptance criteria: "`sentiment_price = real_price + sentiment_delta` is the canonical calculation. Log both components and the result at DEBUG level for auditability.`"
- TASK-BE22/BE23 (price history endpoint, historical data): ensure `sentiment_price`, `real_price`, and `divergence` are all returned in responses so the frontend can display both lines

---

### Resolution for AMBIG-2: Multi-ticker post handling
**Status:** FULLY RESOLVED in `amendments_critical.md` (CRITICAL-4)

See CRITICAL-4 amendment: one row per `(reddit_id, ticker_mentioned)` pair. `detect_tickers()` returns `List[str]`; pipeline iterates and emits one `RawRedditItem` per ticker per post.

No additional amendments needed here.

---

### Resolution for AMBIG-3: Score update → sentiment recomputation policy
**Files:** `01_scraping_pipeline.md`, `02_sentiment_analysis.md`, `02b_sentiment_processor_service.md`

**Canonical policy:** Sentiment is NOT recomputed in real-time when a post's upvote score changes.

**Rationale:** Reddit upvote scores fluctuate rapidly (especially in the first hours after posting). Recomputing sentiment on every score change would:
1. Cause excessive DB writes and model inference calls
2. Produce noisy price signals (price would bounce as votes come in)
3. Violate the window-based design of the sentiment pipeline

**Instead:**
- `score` column in `reddit_raw` is updated on re-scrape (TASK-S03 upsert)
- `weighted_sentiment` in `comment_sentiment` uses `score` as the magnitude weight
- On the NEXT sentiment pipeline run (TASK-NLP14), `score` is read fresh from `reddit_raw`, so the weighting uses the latest vote count
- There is NO trigger from score change → immediate pipeline recompute

**Amendment to TASK-NLP14** (comment sentiment computation):
Add to acceptance criteria: "Query `score` from `reddit_raw` at pipeline run time — do NOT use any cached score value from a previous pipeline run. This ensures the latest vote count is always used as the magnitude weight."

**Amendment to TASK-S03** (upsert): Add note: "Score upsert does not trigger sentiment recomputation. The next scheduled pipeline run (TASK-PROC03/PROC07) picks up the latest score."

---

### Resolution for AMBIG-4: Stale data age thresholds
**Files:** `03_backend_api.md`, `04_frontend_ui.md`

**Canonical thresholds** (defined as constants in `sse_common/constants.py` from TASK-MGMT02):

| Threshold | Value | Default env var |
|---|---|---|
| Fresh → Warning | 30 min | `STALENESS_WARN_SECONDS=1800` |
| Warning → Critical | 60 min | `STALENESS_CRITICAL_SECONDS=3600` |
| Critical → Hide | 4 hours | `STALENESS_HIDE_SECONDS=14400` |

**Backend (TASK-BE28 staleness tracker):**
- Return `staleness_level: "fresh" | "warning" | "critical" | "unavailable"` in API responses
- `"unavailable"` when age > `STALENESS_HIDE_SECONDS` — no sentiment price is returned
- Frontend should treat `staleness_level: "unavailable"` as "hide sentiment price, show Data unavailable"

**Frontend (TASK-FE22 staleness indicator):**
- Fresh (< 30 min): green indicator, no label
- Warning (30–60 min): yellow indicator, label "Stale"
- Critical (60 min – 4 hr): red indicator, label "Data may be outdated"
- Unavailable (> 4 hr): hide `sentiment_price` display, show "Sentiment data unavailable" in muted text

**Amendment to TASK-BE28:** Replace boolean `is_stale` with `staleness_level` enum. Return numeric `data_age_seconds` alongside it for precise display on the frontend.

**Amendment to TASK-FE22:** Use `staleness_level` from API response (not client-side timestamp comparison). Implement the four visual states listed above using Tailwind classes.

---

## 3. Summary — All Moderate Findings Resolved

| Finding | Resolution | Task/Amendment |
|---|---|---|
| RISK-5: Rate limiting duplication | TASK-OPS19 superseded by TASK-BE12 | Amendment above |
| RISK-6: No schema evolution | Single `database/migrations/` dir, Alembic rules | TASK-MGMT01 |
| RISK-7: Logging defined 3× | `sse-common` shared package | TASK-MGMT02 |
| RISK-8: No load testing | Locust test suite with thresholds | TASK-MGMT03 |
| MODERATE-5: No price seeding | `sentiment_price = real_price` on first boot | TASK-PRC11 (02c) |
| MODERATE-6: No real price scheduler | `RealPriceFetcher` in pricing service | TASK-PRC10 (02c) |
| MODERATE-7: SSE path inconsistency | Both endpoints defined; route order fixed | Amendment to TASK-BE26 |
| MODERATE-8: No duplicate detection | SHA-256 fingerprint + `is_duplicate` column | Amendment to TASK-S17 |
| MODERATE-9: No auth-readiness | `get_current_user` stub in all routes | TASK-BE-AUTH-STUB |
| ARCH-2: Dual schema definitions | `reddit_raw` canonical; `database/migrations/` | TASK-MGMT01 + amendments |
| ARCH-3: Async/sync undocumented | ADR-001 written; per-service rationale added | ADR-001 |
| AMBIG-1: Price formula | `sentiment_price = real_price + sentiment_delta` | Amendment to TASK-NLP16, TASK-PRC05 |
| AMBIG-2: Multi-ticker posts | One row per `(reddit_id, ticker_mentioned)` | Already in amendments_critical.md |
| AMBIG-3: Score update policy | No real-time recompute; next scheduled run uses latest score | Amendment to TASK-NLP14, TASK-S03 |
| AMBIG-4: Staleness thresholds | 30min/60min/4hr, configurable via env vars | Amendment to TASK-BE28, TASK-FE22 |

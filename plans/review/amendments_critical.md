# Critical Amendments to Existing Plans
# SSE — Sentiment Stock Exchange
# Covers: CRITICAL-1, CRITICAL-2, CRITICAL-3, CRITICAL-4, ARCH-1

> This document records required changes to existing task plans.
> Existing plan files are NOT rewritten — this file is the amendment record.
> All findings confirmed by reading the actual task IDs cited.

---

## 1. Confirmation of Findings

### CRITICAL-1: Pricing Engine Is Not a Separate Service
**Tasks checked:** TASK-BE19, TASK-BE20, TASK-BE21, TASK-OPS07
**Finding:** TASK-BE19/20/21 all define code under `backend/app/services/pricing/` — embedded inside the FastAPI API server codebase. TASK-OPS07 defines a Dockerfile for a standalone Pricing Engine, but no service entry point exists to run. The Dockerfile has nothing to build against as a standalone service.
**CONFIRMED**

---

### CRITICAL-2: Sentiment Processor Has No Runnable Service
**Tasks checked:** TASK-NLP19, TASK-OPS06
**Finding:** TASK-NLP19 defines `run_sentiment_pipeline()` as a pure function. No task defines a `main.py`, event loop, Redis subscriber, or scheduler that calls this function. TASK-OPS06 defines a Dockerfile for the processor but has no service code to containerize.
**CONFIRMED**

---

### CRITICAL-3: No Event-Driven Pipeline Trigger Chain
**Tasks checked:** TASK-S20, TASK-BE27
**Finding:** TASK-S20 publishes to `sse:scraper:run_complete` but no task subscribes. No task publishes `sse:sentiment:run_complete`. TASK-BE27 couples SSE broadcasting directly to `PricingService`, which assumes pricing runs in-process with the API — an architecture that no longer exists after CRITICAL-1 is resolved.
**CONFIRMED**

---

### CRITICAL-4: `ticker_mentioned` Schema Mismatch
**Tasks checked:** TASK-S04, TASK-S02, TASK-BE04, TASK-S03, TASK-S18
**Finding:**
- TASK-S04: `ticker_mentioned` defined as `List[str]`
- TASK-S02: single `ticker_mentioned` varchar column with UNIQUE on `reddit_id`
- TASK-BE04: `ticker_mentioned` varchar with UNIQUE on `reddit_id`
- TASK-S03: `ON CONFLICT (reddit_id) DO UPDATE SET score`
A `List[str]` cannot be stored in a single varchar column without serialization, and the UNIQUE constraint on `reddit_id` alone prevents the normalized multi-ticker row approach.
**CONFIRMED**

---

### ARCH-1: Service Boundary Violations
**Tasks checked:** TASK-OPS13
**Finding:** TASK-OPS13 lists "All 8 services" but the spec requires 4 distinct application services (Scraper, Sentiment Processor, Pricing Engine, API) plus infrastructure. Processor and Pricing Engine have Dockerfiles (OPS06, OPS07) but no service code. Uptime Kuma (TASK-OPS20) is defined but not counted in TASK-OPS13.
**CONFIRMED**

---

## 2. Amendments to Existing Tasks

### Amendment to TASK-S04
**File:** `01_scraping_pipeline.md`
**Change:** `ticker_mentioned` type change

**Before:** `ticker_mentioned` is `List[str]` to support multiple tickers per item

**After:** `ticker_mentioned` is `str` (singular). When a post mentions multiple tickers (e.g., TSLA and NVDA), the pipeline emits one `RawRedditItem` per ticker. A post mentioning 3 tickers produces 3 `RawRedditItem` objects sharing the same `reddit_id` but with different `ticker_mentioned` values.

**Rationale:** Aligns with spec §5.5 (`ticker_mentioned: string`). Eliminates array-column complexity. Simplifies all downstream joins between `reddit_raw` and `comment_sentiment`.

**Impact on other tasks:**
- TASK-S15/S16: `detect_tickers()` still returns `List[str]`, but the caller (pipeline) now iterates and creates one item per detected ticker per post
- TASK-NLP14: `compute_ticker_sentiment()` filter by `ticker_mentioned = ticker` becomes a simple equality check, not an array containment check

---

### Amendment to TASK-S02
**File:** `01_scraping_pipeline.md`
**Change:** UNIQUE constraint change

**Before:** `reddit_id` has a UNIQUE constraint

**After:** UNIQUE constraint changed to `(reddit_id, ticker_mentioned)` composite. A single Reddit post can have multiple rows if it mentions multiple tickers.

**SQL change:**
```sql
-- Before:
CREATE UNIQUE INDEX ON reddit_raw (reddit_id);

-- After:
CREATE UNIQUE INDEX ON reddit_raw (reddit_id, ticker_mentioned);
```

**Note:** Posts mentioning zero tickers produce no rows — ticker detection is required before insertion.

---

### Amendment to TASK-S03
**File:** `01_scraping_pipeline.md`
**Change:** Upsert conflict target

**Before:** `INSERT ... ON CONFLICT (reddit_id) DO UPDATE SET score = EXCLUDED.score`

**After:** `INSERT ... ON CONFLICT (reddit_id, ticker_mentioned) DO UPDATE SET score = EXCLUDED.score`

**Rationale:** Conflict target must match the UNIQUE constraint.

---

### Amendment to TASK-S18
**File:** `01_scraping_pipeline.md`
**Change:** Deduplication key

**Before:** Deduplication keyed on `reddit_id` alone

**After:** Deduplication keyed on `(reddit_id, ticker_mentioned)` composite. The same `reddit_id` with different `ticker_mentioned` values are treated as distinct items. Count invariant still holds: `inserted + score_updated + unchanged == len(items)`, where `len(items)` is now the post-expansion count (after splitting multi-ticker posts).

---

### Amendment to TASK-BE04
**File:** `03_backend_api.md`
**Change:** UNIQUE constraint change (mirrors TASK-S02)

**Before:** UNIQUE constraint on `reddit_id`

**After:** UNIQUE constraint changed to `(reddit_id, ticker_mentioned)` composite.

**SQL change:**
```sql
-- Before:
ALTER TABLE reddit_raw_data ADD CONSTRAINT uq_reddit_id UNIQUE (reddit_id);

-- After:
ALTER TABLE reddit_raw_data ADD CONSTRAINT uq_reddit_ticker UNIQUE (reddit_id, ticker_mentioned);
```

**Note on table name:** TASK-S02 uses `reddit_raw` and TASK-BE04 uses `reddit_raw_data` — this is the ARCH-2 dual schema issue tracked separately in `amendments_moderate.md`. Whichever name is chosen, the composite unique constraint applies.

---

### Amendment to TASK-BE19, TASK-BE20, TASK-BE21
**File:** `03_backend_api.md`
**Change:** All three tasks MOVED to Pricing Engine service

| Original Task | Status | New Task | New Location |
|---|---|---|---|
| TASK-BE19 | MOVED | TASK-PRC03 | `02c_pricing_engine_service.md` |
| TASK-BE20 | MOVED | TASK-PRC04 | `02c_pricing_engine_service.md` |
| TASK-BE21 | MOVED | TASK-PRC05 | `02c_pricing_engine_service.md` |

In `03_backend_api.md`, these tasks should be marked: `[MOVED → 02c_pricing_engine_service.md: TASK-PRC03/04/05]`

**Impact:** Any task in `03_backend_api.md` depending on BE19/20/21 must update its dependency to the corresponding TASK-PRC task.

---

### Amendment to TASK-BE27
**File:** `03_backend_api.md`
**Change:** SSE notification trigger mechanism

**Before:** "Add hook in `PricingService` so after writing new sentiment prices to DB and Redis, it calls `SSEManager.broadcast(ticker, update_data)` per ticker." Depends on TASK-BE21 (pricing service) and TASK-BE25 (SSEManager).

**After:** The API server no longer runs pricing. Instead:
1. At startup (lifespan), API server subscribes to Redis channel `sse:pricing:run_complete`
2. On receiving the event, API server reads latest prices from Redis cache (populated by Pricing Engine in TASK-PRC05)
3. API server calls `SSEManager.broadcast(ticker, update_data)` for each ticker in `tickers_priced`
4. API server calls `SSEManager.broadcast_all(data_refresh_event)` with a summary event

**New dependencies:** TASK-BE27 depends on TASK-BE25 (SSEManager) and TASK-PRC07 (the Redis event it subscribes to).

**New acceptance criteria:**
- API server subscribes to `sse:pricing:run_complete` Redis channel at startup (lifespan event)
- On event received: reads latest prices from Redis cache `sse:prices:current`
- Broadcasts per-ticker SSE updates matching `SSEPriceUpdate` schema
- SSE manager failures caught and logged — do not crash the API server
- If Redis unavailable: no SSE broadcasts occur; clients fall back to polling REST endpoints
- Broadcast is async and non-blocking relative to Redis event receipt

---

### New Task TASK-BE-SUB: Dedicated pricing event subscriber for the API server
**File:** `03_backend_api.md`
**Resolves:** Explicit subscriber module required by the TASK-BE27 amendment

The TASK-BE27 amendment states the API server "subscribes to Redis channel `sse:pricing:run_complete` at startup" but no existing task creates that subscriber module. The processor and pricing engine each have a dedicated `subscriber.py` with reconnection logic (TASK-PROC03, TASK-PRC06). The API server needs the same treatment — the subscription logic must live somewhere concrete.

**New task to add to `03_backend_api.md` (insert between TASK-BE27 and TASK-BE28):**

**TASK-BE-SUB: Redis subscriber for `sse:pricing:run_complete` in the API server**
- **Domain:** Backend / API
- **Depends on:** TASK-BE11 (Redis client), TASK-BE25 (SSEManager), TASK-BE27 (amended broadcast logic)
- **Description:** Create `backend/app/subscriber.py` with a `PricingEventSubscriber` class. On `sse:pricing:run_complete` message: parse JSON payload (`run_id`, `tickers_priced`, `timestamp`), read latest prices from Redis cache (`sse:prices:current`), call `SSEManager.broadcast(ticker, data)` for each ticker in `tickers_priced`, call `SSEManager.broadcast_all(summary_event)`. Reconnection and error handling identical to TASK-PROC03.
- **Acceptance criteria:**
  - `PricingEventSubscriber` lives in `backend/app/subscriber.py`
  - Subscribes to `sse:pricing:run_complete` using `redis.asyncio` pub/sub
  - On message: parses JSON, reads `sse:prices:current` from Redis, calls `SSEManager.broadcast()` per ticker
  - On Redis disconnect: logs WARNING, retries with exponential backoff (1s → 60s cap)
  - On invalid JSON: logs ERROR, does not crash, does not broadcast stale data
  - Subscriber runs as a background `asyncio.Task` — does NOT block the request event loop
  - Unit tests mock Redis and SSEManager; verify `SSEManager.broadcast` called once per ticker in `tickers_priced`; verify reconnect loop on simulated disconnect

**Amendment to TASK-BE30** (lifespan events):

**Before:** "Startup: initialize DB engine, Redis pool, SSEManager (stored on `app.state`)."

**After:** "Startup: initialize DB engine → Redis pool → SSEManager → `PricingEventSubscriber` (all stored on `app.state`). Subscriber started as a background `asyncio.Task` on `app.state.pricing_subscriber_task`."

Add to TASK-BE30 acceptance criteria:
- `PricingEventSubscriber` started as background task during lifespan startup
- Task stored on `app.state.pricing_subscriber_task` for shutdown reference
- Lifespan shutdown cancels the task and awaits it (catches `asyncio.CancelledError`)
- Unexpected task exit (unhandled exception) is logged at CRITICAL; the API server does NOT auto-restart it — this surfaces the failure to monitoring (Uptime Kuma health check will catch it on next poll)

---

### Amendment to TASK-OPS13
**File:** `05_infrastructure.md`
**Change:** Docker Compose service list updated to 9 services

**Before:** "All 8 services defined (Scraper, Processor, Pricing Engine, API, Frontend, PostgreSQL, Redis, Certbot)"

**After:** All 9 services:
1. `scraper` — Python scraper service (plan 01)
2. `processor` — Sentiment Processor service (plan 02b — NEW)
3. `pricing` — Pricing Engine service (plan 02c — NEW, extracted from plan 03)
4. `api` — FastAPI API server (plan 03, slimmed — no pricing logic)
5. `frontend` — React app served by Nginx (plan 04)
6. `postgres` — PostgreSQL + TimescaleDB (plan 05)
7. `redis` — Redis cache + pub/sub (plan 05)
8. `certbot` — Let's Encrypt (plan 05)
9. `uptime-kuma` — Monitoring (plan 05, TASK-OPS20)

**Service dependency chain in docker-compose.yml:**
```yaml
services:
  postgres:
    # No application depends_on
  redis:
    # No application depends_on
  scraper:
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
  processor:
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
  pricing:
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
  api:
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
  frontend:
    depends_on:
      api: { condition: service_healthy }
  certbot:
    depends_on:
      frontend: { condition: service_started }
  uptime-kuma:
    depends_on:
      api: { condition: service_healthy }
```

**Network topology update (amends TASK-OPS04):**
- `db-net`: postgres, scraper, processor, pricing, api
- `cache-net`: redis, scraper, processor, pricing, api
- `web-net`: api, frontend, certbot, uptime-kuma

---

## 3. Event-Driven Pipeline Trigger Chain (Resolves CRITICAL-3)

The full event chain is now defined across four services:

```
Plan 01 (Scraping)             Plan 02b (Processor)              Plan 02c (Pricing)            Plan 03 (API)
──────────────────             ────────────────────              ──────────────────            ─────────────
TASK-S13 (orchestrator)        TASK-PROC03 (subscriber)          TASK-PRC06 (subscriber)       TASK-BE27 (amended)
    │                              │                                 │                              │
    ▼                              │                                 │                              │
TASK-S20 ──publish──►              │                                 │                              │
sse:scraper:run_complete ──────────►                                 │                              │
                               TASK-PROC05 ──calls──►               │                              │
                               run_sentiment_pipeline()              │                              │
                                   │                                 │                              │
                               TASK-PROC06 ──publish──►              │                              │
                               sse:sentiment:run_complete ───────────►                              │
                                                                 TASK-PRC05 ──computes──►           │
                                                                 sentiment prices                   │
                                                                     │                              │
                                                                 TASK-PRC07 ──publish──►            │
                                                                 sse:pricing:run_complete ──────────►
                                                                                               SSEManager.broadcast()
                                                                                                   │
                                                                                                   ▼
                                                                                           Frontend receives
                                                                                           real-time price updates
```

**Poll-based fallbacks** (for Redis unavailability):
- TASK-PROC07: Processor polls DB for unprocessed `reddit_raw` rows every 5 min
- TASK-PRC08: Pricing Engine polls DB for unpriced `ticker_sentiment_snapshot` rows every 5 min

---

## 4. New Plan Files Created

| File | Resolves | Tasks |
|---|---|---|
| `02b_sentiment_processor_service.md` | CRITICAL-2, part of CRITICAL-3 | TASK-PROC01–PROC12 |
| `02c_pricing_engine_service.md` | CRITICAL-1, part of CRITICAL-3, MODERATE-5, MODERATE-6 | TASK-PRC01–PRC17 |

---

## 5. Summary — All CRITICAL Findings Resolved

| Finding | Resolution |
|---|---|
| CRITICAL-1: Pricing Engine not separate | TASK-PRC01–17 in `02c_pricing_engine_service.md`. TASK-BE19/20/21 moved to TASK-PRC03/04/05. |
| CRITICAL-2: Sentiment Processor has no service | TASK-PROC01–12 in `02b_sentiment_processor_service.md`. |
| CRITICAL-3: No event trigger chain | Full chain defined: S20→PROC03→PROC06→PRC06→PRC07→BE27. Poll fallbacks in TASK-PROC07, TASK-PRC08. |
| CRITICAL-4: ticker_mentioned mismatch | Normalized to one row per ticker. Composite `(reddit_id, ticker_mentioned)` unique constraint. Amendments to TASK-S02/S03/S04/S18/BE04. |
| ARCH-1: Service boundaries | Docker Compose updated to 9 services. Full dependency chain defined. Amendment to TASK-OPS13. |

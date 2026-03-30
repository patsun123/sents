# Architecture Spec — V1 Gap Closure

**Author:** Elrond (System Architect)
**Date:** 2026-03-30
**Status:** APPROVED

---

## 1. Architecture Overview

This spec defines the technical changes needed to close the 16 must-have gaps identified in the requirements. The existing architecture (scraper → processor → pricing engine → backend → frontend, orchestrated via Redis pub/sub) remains unchanged. All changes are additive or in-place modifications to existing services.

### Change Classification

| Category | REQs | Nature |
|----------|------|--------|
| Data pipeline (scraper + processor) | REQ-01, 02, 03, 04 | New code + modifications |
| Service resilience | REQ-05, 06, 07 | New endpoints + behavioral changes |
| Frontend | REQ-08 | New components + modifications |
| Testing & CI | REQ-09, 10, 11, 12 | New files only (no production changes) |
| Hardening | REQ-13, 14, 15, 16 | Config changes + new scripts |

---

## 2. REQ-01: Comment Scraping

### Current State
- `RedditClient.fetch_new_posts()` fetches `/r/{subreddit}/new.json` — post titles + selftext only
- `reddit_raw` table stores posts with `post_type VARCHAR(10) DEFAULT 'post'`
- `comment_sentiment` table exists but references `reddit_raw.id` via `reddit_comment_id` — misleading name, currently stores post-level sentiment

### Design

#### 2.1.1 Reddit Comment Fetching

Add `RedditClient.fetch_comments(post_reddit_id: str, limit: int = 50) -> list[RedditComment]`:
- Endpoint: `GET https://www.reddit.com/comments/{post_reddit_id}.json`
- Returns top-level comments (no recursive threading in V1)
- Extracts: `comment_id`, `body`, `author`, `score`, `created_utc`
- Rate limiting: reuse existing 1-second delay between requests

New dataclass:
```python
@dataclass
class RedditComment:
    reddit_id: str              # comment's Reddit ID (e.g., "t1_abc123")
    parent_post_id: str         # parent post's reddit_id
    ticker_mentioned: str
    author: str
    content: str                # comment body text
    score: int
    upvote_ratio: float | None  # comments don't have this; set to None
    subreddit: str
    post_url: str               # parent post URL
    created_utc: datetime
    content_fingerprint: str    # SHA-256 of normalized content
```

#### 2.1.2 Storage

Comments are stored in the **same `reddit_raw` table** as posts, with `post_type = 'comment'`:
- This avoids schema migration and reuses existing `comment_sentiment` FK relationship
- The `reddit_id` field stores the comment ID (e.g., `t1_abc123`)
- The `title` field is NULL for comments
- The `content` field stores the comment body
- Existing UNIQUE constraint `(reddit_id, ticker_mentioned)` prevents duplicates

#### 2.1.3 Scheduler Integration

Modify `run_scrape_cycle()`:
1. Fetch posts (existing)
2. Store posts (existing)
3. **NEW:** For each stored post with `num_comments > 0`, fetch comments (up to 50 per post)
4. **NEW:** Store comments in `reddit_raw` with `post_type = 'comment'`
5. Publish `CHANNEL_SCRAPER_DONE` (existing)

**Throttling:** Fetch comments for at most 10 posts per cycle to avoid Reddit rate limits. Prioritize posts with highest `num_comments`.

#### 2.1.4 Impact on Downstream

- **Processor:** No changes needed — already queries `reddit_raw` for unprocessed rows regardless of `post_type`
- **Pricing engine:** No changes — works from `ticker_sentiment_snapshot` aggregates
- **Backend API:** `mention_count_24h` query already counts all `reddit_raw` rows — now includes comments automatically

---

## 3. REQ-02: NLP Weighting Model

### Current State
- Processor aggregates sentiment as `AVG(cs.compound_score)` into `ticker_sentiment_snapshot.avg_sentiment_compound`
- `weighted_mention_count` exists but is just `COUNT(*)`
- No temporal decay, no upvote weighting, no delta tracking
- Pricing engine uses `avg_sentiment_compound` directly

### Design

#### 3.1 Weighted Aggregation (Processor)

Replace the simple AVG with a weighted aggregation in `aggregate_sentiment_snapshot()`:

```sql
SELECT
    -- Weighted average: each post's compound score weighted by upvote_weight * recency_weight
    SUM(cs.compound_score * weight) / NULLIF(SUM(weight), 0) AS avg_sentiment_compound,
    -- Weighted mention count (sum of weights, not raw count)
    SUM(weight) AS weighted_mention_count,
    -- Average upvote score (unweighted, for reference)
    AVG(r.score) AS avg_upvote_score
FROM comment_sentiment cs
JOIN reddit_raw r ON r.id = cs.reddit_comment_id
CROSS JOIN LATERAL (
    SELECT
        -- Upvote weight: ln(1 + score) clamped to [0.1, 10]
        GREATEST(0.1, LEAST(10.0, LN(1 + GREATEST(r.score, 0)))) *
        -- Temporal decay: exp(-lambda * hours_old), lambda = ln(2)/decay_halflife_hours
        EXP(-0.693 / {decay_halflife_hours} * EXTRACT(EPOCH FROM (NOW() - r.created_utc)) / 3600)
    AS weight
) w
WHERE r.ticker_mentioned = $1
  AND cs.backend = $2
  AND r.created_utc >= NOW() - INTERVAL '{window_hours} hours'
```

**Weighting parameters** (stored in `pricing_configurations.params` JSONB):

| Param | Default | Description |
|-------|---------|-------------|
| `decay_halflife_hours` | 12 | Hours until a post's weight halves |
| `upvote_weight_min` | 0.1 | Minimum upvote weight (prevents zero-weight) |
| `upvote_weight_max` | 10.0 | Maximum upvote weight (prevents runaway) |

These parameters are read by the processor from a new `sse:processor:config` Redis key (or hardcoded defaults if unavailable).

#### 3.2 Delta-Based Pricing (Pricing Engine)

The pricing engine already computes `delta = agg_score(t) - agg_score(t-1)`. This is preserved.

**Change:** The `agg_score(t)` value is now the **weighted** average from the snapshot, so delta naturally reflects the weighted model.

The `weighted_mention_count` in the snapshot is now a true weighted count (sum of weights), making the volume weighting in the pricing formula work correctly with the new aggregation.

#### 3.3 Scenario Series SQL (Backend)

Update the LATERAL join query in `tickers.py` to use the same weighting formula when computing scenario series. The weighting parameters come from the `pricing_configurations.params` JSONB, making each scenario independently configurable.

**New params in `pricing_configurations.params`:**
```json
{
    "sensitivity": 1.0,
    "max_delta_pct": 0.10,
    "upvote_weight_multiplier": 1.0,
    "volume_scaling_function": "log",
    "volume_weight_multiplier": 1.0,
    "min_mentions": 3,
    "decay_halflife_hours": 12,
    "upvote_weight_min": 0.1,
    "upvote_weight_max": 10.0
}
```

Update `database/init.sql` seed data to include the new params in all three presets.

---

## 4. REQ-03: Quality Filtering

### Design

#### 4.1 Filter Location

Quality filtering happens in **two stages**:

1. **Scraper (at ingestion):** Skip obviously bad content before storing
2. **Processor (before analysis):** Filter rows that slipped through or were retroactively flagged

#### 4.2 Scraper-Side Filtering

In `RedditClient`, before returning posts/comments:

```python
def _should_skip(self, item: dict) -> bool:
    # Deleted/removed
    if item.get('author') in ('[deleted]', '[removed]', 'AutoModerator'):
        return True
    if item.get('selftext') in ('[deleted]', '[removed]'):
        return True
    # Bot accounts (configurable list)
    if item.get('author', '').lower() in self._bot_usernames:
        return True
    # Minimum content length
    text = (item.get('title', '') + ' ' + item.get('selftext', '')).strip()
    if len(text) < self._min_content_length:
        return True
    return False
```

**Configuration:**
- `bot_usernames`: list in scraper config (default: `['automoderator', 'snapshillbot', 'remindmebot']`)
- `min_content_length`: integer (default: `20` characters)

#### 4.3 Processor-Side Filtering

In `get_unprocessed_posts()` query, add WHERE clauses:

```sql
AND r.content NOT IN ('[deleted]', '[removed]')
AND r.author NOT IN (SELECT unnest($bot_list::text[]))
AND LENGTH(COALESCE(r.title, '') || ' ' || COALESCE(r.content, '')) >= $min_length
AND r.is_duplicate = FALSE
```

#### 4.4 Duplicate Detection

The `content_fingerprint` column (SHA-256 of normalized content) already exists in `reddit_raw`.

Add to `store_posts()`:
```sql
UPDATE reddit_raw SET is_duplicate = TRUE
WHERE content_fingerprint IN (
    SELECT content_fingerprint FROM reddit_raw
    GROUP BY content_fingerprint HAVING COUNT(*) > 1
)
AND id NOT IN (
    SELECT MIN(id) FROM reddit_raw GROUP BY content_fingerprint
)
```

Run this dedup query after each batch insert. Only the first occurrence of each fingerprint is kept as non-duplicate.

---

## 5. REQ-04: Financial Text Preprocessor

### Design

New module: `processor/src/processor/text/preprocessor.py`

#### 5.1 Pipeline

```python
def preprocess(text: str) -> str:
    text = normalize_cashtags(text)       # $AAPL → AAPL
    text = expand_slang(text)             # "bullish af" → "very bullish"
    text = map_emojis(text)               # 🚀 → "(positive_sentiment)"
    text = normalize_whitespace(text)     # collapse multiple spaces/newlines
    return text
```

#### 5.2 Slang Dictionary

Static dictionary in `processor/src/processor/text/slang_dict.py`:

```python
FINANCIAL_SLANG = {
    "bullish af": "very bullish strongly positive",
    "bearish af": "very bearish strongly negative",
    "to the moon": "strongly positive rising",
    "diamond hands": "holding strong positive conviction",
    "paper hands": "selling weak negative conviction",
    "tendies": "profits gains positive",
    "apes": "retail investors",
    "yolo": "high risk investment all in",
    "fud": "fear uncertainty doubt negative",
    "hodl": "hold strong positive",
    "bag holder": "losing position negative",
    "short squeeze": "rapid price increase positive",
    "pump and dump": "manipulation negative",
    "dd": "due diligence research analysis",
    "wsb": "wallstreetbets",
    "lfg": "very positive excited",
    "rip": "negative declining",
    "mooning": "rising strongly positive",
    "tanking": "falling strongly negative",
    "dip": "price decrease buy opportunity",
    "btfd": "buy the dip positive",
}
```

Case-insensitive matching. Applied as whole-word replacements to avoid substring matches.

#### 5.3 Emoji Mapping

Static dictionary in `processor/src/processor/text/emoji_map.py`:

```python
EMOJI_SENTIMENT = {
    "🚀": "(positive_sentiment rising)",
    "💎": "(positive_sentiment strong)",
    "🙌": "(positive_sentiment)",
    "🐂": "(bullish positive)",
    "🐻": "(bearish negative)",
    "💀": "(negative_sentiment declining)",
    "🤡": "(negative_sentiment foolish)",
    "📈": "(positive_sentiment rising)",
    "📉": "(negative_sentiment declining)",
    "🔥": "(positive_sentiment strong)",
    "💰": "(positive_sentiment profit)",
    "🗑️": "(negative_sentiment worthless)",
    "😂": "(neutral_sentiment)",
    "🤝": "(positive_sentiment agreement)",
}
```

#### 5.4 Integration

In `pipeline.py`, call `preprocess(text)` before passing to any sentiment backend:

```python
from processor.text.preprocessor import preprocess

raw_text = f"{post.title} {post.content}"
cleaned_text = preprocess(raw_text)
result = backend.analyze(cleaned_text)
```

---

## 6. REQ-05: Service Health Endpoints

### Design

Each pipeline service (scraper, processor, pricing_engine) gets a minimal HTTP health server.

#### 6.1 Implementation Pattern

Use `aiohttp.web` (already available via `aiohttp` dependency) to run a tiny HTTP server alongside the main loop:

```python
# health_server.py (shared pattern, one per service)
from aiohttp import web
import time

class HealthServer:
    def __init__(self, service_name: str, port: int):
        self.service_name = service_name
        self.port = port
        self.start_time = time.time()
        self.last_success: float | None = None
        self.status = "healthy"

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "service": self.service_name,
            "status": self.status,
            "uptime_seconds": int(time.time() - self.start_time),
            "last_successful_run": self.last_success,
        })

    async def start(self):
        app = web.Application()
        app.router.add_get("/health", self.handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
```

#### 6.2 Port Assignments

| Service | Health Port |
|---------|------------|
| Scraper | 8001 |
| Processor | 8002 |
| Pricing Engine | 8003 |

#### 6.3 Docker Healthcheck

Add to each service in `docker-compose.yml`:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:800X/health"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 30s
```

Install `curl` in each Dockerfile (add `apk add --no-cache curl` for Alpine-based images, or use Python `urllib` for a dependency-free option).

#### 6.4 Status Logic

- **healthy:** Last successful run within expected interval (scraper: 2x scrape_interval, processor: 5 min, pricing: 5 min)
- **degraded:** Last successful run beyond expected interval but within 15 min
- **unhealthy:** No successful run in 15+ min, or critical dependency (DB) unreachable

---

## 7. REQ-06: Processor Redis Resilience

### Current State
- `processor/main.py` calls `subscriber_loop()` which blocks on Redis pub/sub
- If Redis connection fails, the exception propagates and the service exits

### Design

#### 7.1 Dual-Mode Loop

```python
async def main():
    pool = await create_db_pool()
    redis = await try_connect_redis()  # returns None on failure

    if redis:
        # Primary mode: event-driven
        asyncio.create_task(subscriber_loop(pool, redis))
    else:
        logger.warning("Redis unavailable — running in poll-only mode")

    # Always run poll loop as fallback
    asyncio.create_task(poll_loop(pool, poll_interval=60))

    # Periodically try to reconnect Redis
    asyncio.create_task(redis_reconnect_loop(reconnect_interval=30))
```

#### 7.2 Poll Loop

```python
async def poll_loop(pool: asyncpg.Pool, poll_interval: int = 60):
    while True:
        await asyncio.sleep(poll_interval)
        try:
            await run_pipeline(pool, ...)
        except Exception as e:
            logger.error(f"Poll pipeline failed: {e}")
```

#### 7.3 Redis Reconnect

```python
async def redis_reconnect_loop(reconnect_interval: int = 30):
    while True:
        await asyncio.sleep(reconnect_interval)
        if not redis_connected():
            redis = await try_connect_redis()
            if redis:
                logger.info("Redis reconnected — resuming pub/sub mode")
                asyncio.create_task(subscriber_loop(pool, redis))
```

---

## 8. REQ-07: API Rate Limiting

### Design

#### 8.1 Library

Use `slowapi` (already in requirements as a dependency candidate):

```
pip install slowapi
```

#### 8.2 Configuration

In `backend/app/main.py`:

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

#### 8.3 Rate Limits

| Endpoint Pattern | Limit |
|-----------------|-------|
| `/api/v1/*` (general) | 60/minute |
| `/api/v1/tickers/stream` | 10/minute |
| `/api/v1/tickers/*/stream` | 10/minute |

Applied via decorator:

```python
@router.get("/market/overview")
@limiter.limit("60/minute")
async def market_overview(request: Request):
    ...
```

#### 8.4 Response Headers

slowapi automatically adds `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers. The 429 response includes `Retry-After`.

#### 8.5 Storage Backend

Use in-memory storage (single-process, single-user prototype). No Redis backend needed for rate limiting.

---

## 9. REQ-08: Frontend Chart Components

### Design

Detailed in the design spec. Technical additions:

#### 9.1 New API Field: `sparkline`

Add to `MarketOverviewResponse.tickers[].sparkline: number[]`:

Backend query change in `market.py`:

```sql
-- Subquery to get last 24 sentiment prices per ticker
SELECT array_agg(sp.sentiment_price ORDER BY sp.time)
FROM (
    SELECT sentiment_price, time
    FROM sentiment_prices
    WHERE ticker = t.symbol
    ORDER BY time DESC
    LIMIT 24
) sp
```

Returns the most recent 24 sentiment prices as an array. If fewer than 24 exist, returns whatever is available.

#### 9.2 TypeScript Type Update

Add to `TickerSummary`:
```typescript
sparkline: number[]  // last 24 sentiment prices
```

#### 9.3 New Components

| Component | File | Library |
|-----------|------|---------|
| SparklineChart | `frontend/src/components/SparklineChart.tsx` | Canvas 2D API (no library) |
| DivergenceGauge | `frontend/src/components/DivergenceGauge.tsx` | Pure CSS + Tailwind |
| ChartLegend | `frontend/src/components/ChartLegend.tsx` | Pure CSS + Tailwind |

#### 9.4 SSE Chart Updates

In `TickerChart.tsx`, when `useTickerSSE` delivers a new price event:

```typescript
// In the useTickerSSE callback:
if (seriesRef.current['sentiment'] && newData.sentiment_price) {
    seriesRef.current['sentiment'].update({
        time: toTimestamp(newData.time),
        value: newData.sentiment_price,
    })
}
```

Use `update()` (not `setData()`) for incremental append.

---

## 10. REQ-09: Service Test Coverage

### Design

#### 10.1 Test Structure

```
scraper/tests/
├── conftest.py              # shared fixtures (mock HTTP, mock DB pool)
├── test_reddit_client.py    # fetch_new_posts, fetch_comments, _should_skip
├── test_comment_parsing.py  # RedditComment dataclass construction
├── test_quality_filter.py   # deleted/bot/spam/min-length filtering
└── test_storage.py          # store_posts batch insert, dedup

processor/tests/
├── conftest.py
├── test_vader.py            # VADER backend analyze()
├── test_textblob.py         # TextBlob backend analyze()
├── test_preprocessor.py     # slang expansion, emoji mapping, cashtag normalization
├── test_weighting.py        # weighted aggregation SQL logic
└── test_pipeline.py         # end-to-end pipeline (mocked DB)

pricing_engine/tests/
├── conftest.py
├── test_formula.py          # FormulaEngine.compute() with various params
├── test_config_loading.py   # load pricing_configurations from DB
└── test_publisher.py        # Redis publish event shape
```

#### 10.2 Testing Approach

- **Unit tests** with `pytest` + `pytest-asyncio`
- **Mock external dependencies**: HTTP responses (via `respx` or `aioresponses`), database (via mock asyncpg pool), Redis (via `fakeredis`)
- **No Docker required** for unit tests — all I/O mocked
- **Fixtures** shared via `conftest.py` per service

#### 10.3 Dependencies

Add to each service's `pyproject.toml` under `[project.optional-dependencies]` → `dev`:

```toml
[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-asyncio>=0.21", "aioresponses>=0.7", "fakeredis[aioredis]>=2.0"]
```

---

## 11. REQ-10: GitHub Actions CI

### Design

#### 11.1 Workflow File

`.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  test-backend:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [scraper, processor, pricing_engine, backend]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: |
          cd ${{ matrix.service }}
          uv pip install -e ".[dev]"
          uv pip install -e ../sse_common
      - run: pytest ${{ matrix.service }}/tests/ -v

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: cd frontend && npm ci && npm run test -- --run

  build-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: cd frontend && npm ci && npm run build
```

#### 11.2 Ruff Configuration

Add `ruff.toml` at project root (or section in `pyproject.toml`):

```toml
[lint]
select = ["E", "F", "I", "W"]
ignore = ["E501"]  # line length handled by formatter

[format]
line-length = 100
```

---

## 12. REQ-11: Frontend Tests

### Design

#### 12.1 Test Setup

Install Vitest + React Testing Library:

```json
"devDependencies": {
    "@testing-library/react": "^14.0",
    "@testing-library/jest-dom": "^6.0",
    "vitest": "^1.0",
    "jsdom": "^24.0"
}
```

Add to `vite.config.ts`:

```typescript
test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
}
```

#### 12.2 Test Files

```
frontend/src/
├── test/
│   └── setup.ts                    # jsdom + jest-dom matchers
├── components/
│   ├── __tests__/
│   │   ├── MarketTable.test.tsx    # renders tickers, click selects
│   │   ├── SparklineChart.test.tsx # renders canvas, handles empty data
│   │   ├── DivergenceGauge.test.tsx# renders gauge, null states
│   │   └── ChartLegend.test.tsx    # renders legend items
│   └── ...
└── hooks/
    └── __tests__/
        └── useSSE.test.ts          # SSE connection, reconnect, event parsing
```

#### 12.3 Test Strategy

- **Component tests:** Render with mock data via `@testing-library/react`, assert DOM output
- **Hook tests:** Use `renderHook` from `@testing-library/react` with mock `EventSource`
- **No E2E tests** in V1 (Playwright deferred)

---

## 13. REQ-12: Continuous Aggregate Optimization

### Current State
- `sentiment_prices_1h` continuous aggregate exists (1-hour buckets)
- History queries in `tickers.py` scan the raw `sentiment_prices` hypertable for all timeframes

### Design

#### 13.1 Query Changes

Update `tickers.py` history queries:

| Timeframe | Current Source | New Source |
|-----------|---------------|------------|
| 1d (hourly buckets) | `sentiment_prices` raw | `sentiment_prices_1h` continuous aggregate |
| 1w (daily buckets) | `sentiment_prices` raw | `time_bucket('1 day', ...)` on `sentiment_prices_1h` |
| 1m (weekly buckets) | `sentiment_prices` raw | `time_bucket('1 week', ...)` on `sentiment_prices_1h` |

#### 13.2 Continuous Aggregate Verification

Verify in `init.sql` that the materialized view is correctly defined:

```sql
CREATE MATERIALIZED VIEW sentiment_prices_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    ticker,
    last(sentiment_price, time) AS sentiment_price,
    last(real_price_at_calc, time) AS real_price,
    last(sentiment_delta, time) AS sentiment_delta
FROM sentiment_prices
GROUP BY bucket, ticker;
```

Add a refresh policy if not present:

```sql
SELECT add_continuous_aggregate_policy('sentiment_prices_1h',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
```

---

## 14. REQ-13: Documentation

### Design

```
docs/
├── architecture-overview.md    # System diagram, service descriptions, data flow
├── local-dev-setup.md         # Prerequisites, docker compose up, environment vars
├── operations-runbook.md      # Common operations: reset DB, restart services, check logs, backups
└── security.md                # Security model: DB roles, Redis auth, container hardening, network
```

Written as markdown. No auto-generation tools needed.

---

## 15. REQ-14: Container Read-Only Filesystems

### Design

Add to each application service in `docker-compose.yml`:

```yaml
read_only: true
tmpfs:
  - /tmp
  - /var/log
```

**Service-specific writable mounts:**

| Service | Additional tmpfs |
|---------|-----------------|
| Scraper | None |
| Processor | `/root/.cache` (HuggingFace model cache — but FinBERT deferred, so maybe not needed) |
| Pricing Engine | None |
| Backend | None |
| Frontend (nginx) | `/var/cache/nginx`, `/var/run` |

**Note:** PostgreSQL and Redis containers are NOT set to read_only (they need persistent writes to data volumes).

---

## 16. REQ-15: Redis Authentication

### Design

#### 16.1 Redis Configuration

In `docker-compose.yml`, add `requirepass` via command:

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --requirepass ${REDIS_PASSWORD}
  environment:
    - REDIS_PASSWORD=${REDIS_PASSWORD}
```

#### 16.2 Environment Variable

Add to `.env` (and `.env.example`):

```
REDIS_PASSWORD=sse_redis_dev_password
```

#### 16.3 Client Updates

Every service that connects to Redis must include the password in the connection URL:

```
redis://:{password}@redis:6379/0
```

Update each service's config to read `REDIS_PASSWORD` from environment and construct the URL accordingly.

**Files to update:**
- `scraper/src/scraper/config.py`
- `processor/src/processor/config.py`
- `pricing_engine/src/pricing_engine/config.py`
- `backend/app/config.py` (or equivalent)

#### 16.4 Health Check Update

Redis healthcheck in `docker-compose.yml`:

```yaml
healthcheck:
  test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
```

---

## 17. REQ-16: Automated DB Backups

### Design

#### 17.1 Backup Script

New file: `database/backup.sh`

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/backups"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="sse_backup_${TIMESTAMP}.sql.gz"

pg_dump -h postgres -U sse_admin -d sse \
  | gzip > "${BACKUP_DIR}/${FILENAME}"

# Prune old backups
find "${BACKUP_DIR}" -name "sse_backup_*.sql.gz" \
  -mtime +${RETENTION_DAYS} -delete

echo "Backup complete: ${FILENAME}"
```

#### 17.2 Docker Service

Add a backup service to `docker-compose.yml`:

```yaml
db-backup:
  image: timescale/timescaledb:latest-pg16
  entrypoint: /bin/bash
  command: ["-c", "while true; do /backup.sh; sleep ${BACKUP_INTERVAL_SECONDS:-86400}; done"]
  volumes:
    - ./database/backup.sh:/backup.sh:ro
    - db_backups:/backups
  environment:
    - PGPASSWORD=${POSTGRES_ADMIN_PASSWORD}
    - BACKUP_RETENTION_DAYS=7
    - BACKUP_INTERVAL_SECONDS=86400
  depends_on:
    - postgres
```

New volume:
```yaml
volumes:
  db_backups:
```

#### 17.3 Restore Procedure

Documented in `docs/operations-runbook.md`:

```bash
# List available backups
docker compose exec db-backup ls -la /backups/

# Restore a specific backup
docker compose exec -T postgres \
  psql -U sse_admin -d sse < <(docker compose exec db-backup zcat /backups/sse_backup_YYYYMMDD_HHMMSS.sql.gz)
```

---

## 18. Database Schema Changes Summary

### New Columns: None
All needed columns already exist in the schema.

### New Seed Data
Update `pricing_configurations` params to include new weighting fields:

```sql
UPDATE pricing_configurations SET params = params || '{
    "decay_halflife_hours": 12,
    "upvote_weight_min": 0.1,
    "upvote_weight_max": 10.0
}'::jsonb;
```

### New Materialized Views: None
`sentiment_prices_1h` already exists. Just verify and add refresh policy.

---

## 19. Dependency Changes

### Python (all services)
| Package | Version | REQ | Notes |
|---------|---------|-----|-------|
| `slowapi` | ^0.1 | REQ-07 | API rate limiting |
| `aiohttp` | ^3.9 | REQ-05 | Health server (may already be installed) |

### Python (dev only)
| Package | Version | REQ |
|---------|---------|-----|
| `pytest` | ^7.0 | REQ-09 |
| `pytest-asyncio` | ^0.21 | REQ-09 |
| `aioresponses` | ^0.7 | REQ-09 |
| `fakeredis[aioredis]` | ^2.0 | REQ-09 |
| `ruff` | ^0.4 | REQ-10 |

### Frontend (dev only)
| Package | Version | REQ |
|---------|---------|-----|
| `vitest` | ^1.0 | REQ-11 |
| `@testing-library/react` | ^14.0 | REQ-11 |
| `@testing-library/jest-dom` | ^6.0 | REQ-11 |
| `jsdom` | ^24.0 | REQ-11 |

---

## 20. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Reddit rate limiting on comment fetches | Comment scraping fails | Throttle to 10 posts/cycle, 1s delay between requests |
| Weighted aggregation SQL performance | Slow market overview | Aggregation runs at snapshot time, not query time |
| slowapi in-memory storage lost on restart | Rate limit counters reset | Acceptable for single-user prototype |
| Health server port conflicts | Service startup fails | Use dedicated ports (8001-8003) not exposed to host |

---

## Sign-Off

- [x] Lead Engineer (Gandalf) — approved 2026-03-30
- [x] Product Manager (Aragorn) — approved 2026-03-30
- [x] Stakeholder (User) — approved 2026-03-30

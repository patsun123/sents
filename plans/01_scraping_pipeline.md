# Scraping & Data Pipeline — Atomic Implementation Plan

## Domain: Reddit Scraper, Ticker Detection, Data Quality, Deduplication, Retention

---

### TASK-S01: Project scaffolding and Python package structure
**Domain:** Scraping
**Depends on:** none
**Description:** Create the Python package layout for the scraper service: directories (`scraper/`, `scraper/reddit/`, `scraper/pipeline/`, `scraper/db/`, `scraper/tests/`), `pyproject.toml` with all required dependencies (BeautifulSoup4, Playwright, psycopg2-binary, redis, httpx, tenacity, pytest), and a base `config.py` that reads all settings from environment variables with documented defaults.
**Acceptance criteria:**
- `pip install -e .` succeeds in a clean virtualenv
- All dependency groups (scraping, db, cache, dev/test) declared separately
- `config.py` raises a clear error at startup if required env vars (DB URL, proxy credentials) are missing
- Package imports cleanly with no circular dependencies

---

### TASK-S02: PostgreSQL + TimescaleDB schema for raw Reddit data
**Domain:** Scraping
**Depends on:** TASK-OPS33
**Description:** Define the `reddit_raw` hypertable schema. The actual migration lives in `database/migrations/` (owned by TASK-OPS33 — the scraper references it but does not own the DDL). Schema fields: `reddit_id`, `ticker_mentioned`, `content_fingerprint` (varchar 64, nullable), `is_duplicate` (boolean, default false), `source_text`, `item_type` (post/comment enum), `subreddit`, `timestamp` (NOT NULL, partitioning column), `score`, `parent_post_id`. No author column.
**Acceptance criteria:**
- Migration in `database/migrations/` runs cleanly against fresh Postgres + TimescaleDB
- `reddit_raw` is a TimescaleDB hypertable partitioned by `timestamp`
- UNIQUE constraint is on `(reddit_id, ticker_mentioned)` composite — NOT on `reddit_id` alone
- `content_fingerprint` and `is_duplicate` columns exist (used by TASK-S32 duplicate detection)
- Index on `(content_fingerprint, created_at) WHERE is_duplicate = FALSE`
- `timestamp` has a NOT NULL constraint
- `item_type` uses CHECK constraint restricting to `'post'` and `'comment'`
- No `author` or user-identifying column exists

---

### TASK-S03: Database connection pool and repository layer
**Domain:** Scraping
**Depends on:** TASK-S02
**Description:** Implement `scraper/db/repository.py` wrapping psycopg2 with a connection pool. Expose: `upsert_raw_item(item: RawRedditItem)` — inserts or updates only `score` on conflict with the composite key — and `get_staleness_seconds() -> int`. The batch variant lives in TASK-S27.
**Acceptance criteria:**
- `upsert_raw_item` uses `INSERT ... ON CONFLICT (reddit_id, ticker_mentioned) DO UPDATE SET score = EXCLUDED.score`
- Conflict target is `(reddit_id, ticker_mentioned)` composite — NOT `reddit_id` alone
- Never updates `source_text`, `ticker_mentioned`, or other fields on conflict
- Score updates do NOT trigger immediate sentiment recomputation — next scheduled pipeline run will pick up latest score (AMBIG-3 resolution)
- `get_staleness_seconds` executes in under 5ms with a proper index on `timestamp`
- Connection pool size configurable via env var (`DB_POOL_SIZE`, default: 5)
- All DB errors re-raised as typed application exceptions (not raw psycopg2 exceptions)
- Unit tests mock the DB and verify the upsert SQL including conflict target

---

### TASK-S04: `RawRedditItem` dataclass and validation
**Domain:** Scraping
**Depends on:** none
**Description:** Define the canonical `RawRedditItem` dataclass (or Pydantic model) that all scraper outputs must conform to. Field-level validation: `reddit_id` non-empty, `timestamp` timezone-aware datetime, `item_type` is `"post"` or `"comment"`, `score` defaults to 0 if absent, `source_text` non-empty.
**Acceptance criteria:**
- Instantiating with invalid data raises `ValidationError` with clear field-level message
- `ticker_mentioned` is `str` (singular) — NOT `List[str]`. A post mentioning multiple tickers is represented as multiple `RawRedditItem` objects sharing the same `reddit_id` with different `ticker_mentioned` values. `detect_tickers()` (TASK-S15) still returns `List[str]`; the pipeline iterates and creates one item per detected ticker.
- `content_fingerprint: Optional[str] = None` field exists (populated by quality filter TASK-S32)
- Model importable without any DB or network dependency
- Unit tests cover: missing `timestamp`, empty `reddit_id`, invalid `item_type`, missing `source_text`, multi-ticker post expansion (one source post → N `RawRedditItem` objects)

---

### TASK-S05: HTTP client with proxy rotation and user-agent rotation
**Domain:** Scraping
**Depends on:** TASK-S01
**Description:** Build `scraper/http_client.py` — a wrapper around `httpx` that transparently applies rotating residential proxies and rotates user-agent strings on every request. Proxy credentials are read from config. User-agent pool must contain at least 20 realistic desktop browser strings.
**Acceptance criteria:**
- Each `get(url)` call selects a proxy and user-agent at random from their respective pools
- Empty proxy list raises `ConfigurationError` at construction time, not request time
- User-agent pool stored in a constants file, not inline
- Unit tests use a mock transport asserting `User-Agent` and proxy headers are set on every request

---

### TASK-S06: Request jitter and exponential backoff middleware
**Domain:** Scraping
**Depends on:** TASK-S05
**Description:** Add request-level jitter (randomized delay between configurable `JITTER_MIN_MS` and `JITTER_MAX_MS`) and exponential backoff (via `tenacity`) to the HTTP client. Backoff triggers on HTTP 429, 503, and connection errors. Retry count and base delay are configurable.
**Acceptance criteria:**
- Jitter applied before every request, including retries
- Backoff uses exponential wait with full jitter
- After exhausting retries raises `ScraperExhaustedError`
- Retry attempts and wait times logged at DEBUG level
- Unit tests assert retry count and jitter call count (mock `random.uniform`)

---

### TASK-S07: Reddit HTML scraper for subreddit listing pages
**Domain:** Scraping
**Depends on:** TASK-S05, TASK-S06
**Description:** Implement `scraper/reddit/listing_scraper.py` — fetches HTML listing page for a given subreddit from `old.reddit.com` (stable HTML, no JS required) and parses post metadata (reddit_id, title, score, timestamp, permalink) using BeautifulSoup.
**Acceptance criteria:**
- Returns list of `PostMetadata` objects (reddit_id, title, score, permalink, subreddit, timestamp)
- `timestamp` parsed from `<time>` element's `datetime` attribute as timezone-aware UTC
- Handles 0-post listing pages without raising
- Does not follow post permalinks
- Tested against a locally saved real `old.reddit.com` listing page fixture file

---

### TASK-S08: Reddit HTML scraper for individual post and comment pages
**Domain:** Scraping
**Depends on:** TASK-S07
**Description:** Implement `scraper/reddit/post_scraper.py` — fetches individual post pages from `old.reddit.com` and extracts post body and all comment levels using BeautifulSoup. Each item includes reddit_id, source_text, score, parent_post_id, subreddit, timestamp.
**Acceptance criteria:**
- Post body and all comment levels extracted (not just top-level)
- Deleted/removed text (`[deleted]`, `[removed]`) captured as-is (filtered downstream)
- `parent_post_id` for comments is always the root post's reddit_id
- Pagination detected and flagged (not followed in this task)
- Tested against a locally saved real post page with nested comments fixture

---

### TASK-S09: Comment pagination and `load more` traversal
**Domain:** Scraping
**Depends on:** TASK-S08
**Description:** Extend `post_scraper.py` to follow Reddit's `?after=` comment pagination. Each paginated request uses the same HTTP client (with jitter/backoff). Traversal depth capped at configurable `MAX_COMMENT_DEPTH`.
**Acceptance criteria:**
- Paginated comments merged without duplicates (keyed on `reddit_id`)
- Traversal stops at `MAX_COMMENT_DEPTH` (default: 3, configurable)
- Each pagination request subject to same jitter/backoff
- Unit test verifies `MAX_COMMENT_DEPTH=1` prevents nested reply fetching

---

### TASK-S10: Playwright-based fallback scraper for JS-rendered pages
**Domain:** Scraping
**Depends on:** TASK-S05, TASK-S06
**Description:** Implement `scraper/reddit/playwright_scraper.py` — fallback for when `old.reddit.com` is blocked or returns a CAPTCHA. Uses Playwright (headless Chromium) to render `www.reddit.com` pages and extract the same fields as TASK-S07/S08. Invoked only when BeautifulSoup scraper fails.
**Acceptance criteria:**
- Implements same interface and return types as BeautifulSoup scrapers
- Browser context uses randomized user-agent from same pool as TASK-S05
- Playwright initialized with `--no-sandbox` and configurable `PLAYWRIGHT_TIMEOUT_MS`
- If Playwright also fails, raises `ScraperExhaustedError`
- Integration test (marked `@pytest.mark.integration`) verifies parsing a saved HTML fixture via Playwright

---

### TASK-S11: Reddit RSS feed fallback scraper
**Domain:** Scraping
**Depends on:** TASK-S05, TASK-S06
**Description:** Implement `scraper/reddit/rss_scraper.py` — last-resort fallback fetching subreddit RSS feeds (post titles only, no comments or scores). Used when both BeautifulSoup and Playwright fail.
**Acceptance criteria:**
- Returns list of `PostMetadata` objects with fields available from RSS (title, permalink, reddit_id from URL, timestamp from `<pubDate>`)
- Score set to `None` (not available from RSS)
- Comment text not fetched
- Unit tested against a fixture RSS XML file

---

### TASK-S12: Pushshift fallback scraper
**Domain:** Scraping
**Depends on:** TASK-S05, TASK-S06, TASK-S31
**⚠️ BLOCKED:** Do NOT implement until TASK-S31 (Pushshift availability research spike) completes with a written recommendation. TASK-S31 may result in this task being replaced by a Reddit OAuth API scraper or removed entirely.
**Description:** Implement `scraper/reddit/pushshift_scraper.py` querying the Pushshift API (or community replacement confirmed working by TASK-S31) for recent posts and comments. Used as a fallback when all live Reddit scraping fails. Logs a WARNING when this fallback is used.
**Acceptance criteria:**
- Target API endpoint confirmed by TASK-S31 research (not assumed)
- Parses JSON response into `RawRedditItem` objects
- Logs WARNING with reason for Pushshift fallback
- Raises `ScraperExhaustedError` if API is unavailable
- Unit tested with a fixture JSON response file

---

### TASK-S13: Scraper orchestrator with fallback chain
**Domain:** Scraping
**Depends on:** TASK-S07, TASK-S08, TASK-S10, TASK-S11, TASK-S12
**Description:** Implement `scraper/orchestrator.py` coordinating scraping of all four target subreddits. For each subreddit, tries scrapers in order: BeautifulSoup → Playwright → RSS → Pushshift. If all fail, logs CRITICAL and enters degraded mode (TASK-S21).
**Acceptance criteria:**
- Fallback chain tried in strict order; next fallback attempted only after previous raises `ScraperExhaustedError`
- Each subreddit scraped independently — failure of one does not abort others
- Returns combined list of `RawRedditItem` objects from all successful subreddit scrapes
- Subreddit list read from config, not hard-coded in this module
- Logs which scraper was used for each subreddit at INFO level

---

### TASK-S14: Scheduler for 15–30 minute scrape intervals
**Domain:** Scraping
**Depends on:** TASK-S13
**Description:** Implement `scraper/scheduler.py` using APScheduler (or asyncio loop) to invoke the orchestrator on a randomized interval between `SCRAPE_INTERVAL_MIN` and `SCRAPE_INTERVAL_MAX` (default 15–30 min). Runs 24/7.
**Acceptance criteria:**
- Interval randomized anew after each run (not fixed at startup)
- `SCRAPE_INTERVAL_MIN` and `SCRAPE_INTERVAL_MAX` configurable via env vars (defaults: 15 and 30 min)
- Unhandled orchestrator exceptions are logged; scheduler does not exit
- Scheduler startup and each run start/end logged at INFO with timestamps
- Unit test verifies interval is within `[MIN, MAX]` and failed orchestrator call does not halt scheduler

---

### TASK-S15: Ticker detection — regex engine with word boundaries
**Domain:** Scraping
**Depends on:** TASK-S04
**Description:** Implement `scraper/pipeline/ticker_detector.py` with `detect_tickers(text: str) -> List[str]` using regex with strict `\b` word boundaries to find stock tickers (1–5 uppercase letters, optionally preceded by `$`). Returns a deduplicated, sorted list of matched tickers.
**Acceptance criteria:**
- `$AAPL` and `AAPL` both matched
- `AAPL` embedded in `SNAPCHAT` not matched
- Case-sensitive: `aapl` not matched
- Ticker list is configurable (loaded from file/DB), not hard-coded
- Unit tests cover: `$AAPL mention`, multi-ticker text, no tickers, embedded false match, mixed-case

---

### TASK-S16: Ticker detection — context validation and false-positive blacklist
**Domain:** Scraping
**Depends on:** TASK-S15
**Description:** Extend `ticker_detector.py` with two filtering layers: (1) context validation requiring at least one financial keyword within N words of the matched ticker; (2) a configurable blacklist for ambiguous tickers (`F`, `AI`, `IT`, `A`, `GM`, `I`, `BE`, `ON`, `OR`) that are filtered unless prefixed with `$`.
**Acceptance criteria:**
- Ticker without surrounding financial context words is dropped
- `$F` (dollar sign prefix) bypasses the blacklist
- `F` without `$` and without financial context is dropped
- Financial keyword list and blacklist loaded from config files
- Context window size configurable (default: 10 words)
- Unit tests cover: ambiguous ticker with/without `$`, financial context present/absent

---

### TASK-S17: Data quality filter — remove deleted, bot, spam, and duplicate content
**Domain:** Scraping
**Depends on:** TASK-S04
**Description:** Implement `scraper/pipeline/quality_filter.py` with `filter_items(items: List[RawRedditItem]) -> List[RawRedditItem]` applying sequential filters: (1) drop `[deleted]`/`[removed]` text, (2) drop bot-pattern content (AutoModerator patterns), (3) drop pump-and-dump spam patterns, (4) drop items below `MIN_COMMENT_LENGTH` (default: 20 chars), (5) compute SHA-256 content fingerprint and mark near-duplicates.

**Filter 5 — near-duplicate detection:**
```python
import hashlib
def content_fingerprint(text: str) -> str:
    normalized = " ".join(text[:200].lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
```
Items with matching fingerprints from a DIFFERENT `reddit_id` within `DUPLICATE_WINDOW_HOURS` (default: 24) are marked `is_duplicate = True` and excluded from pipeline output. Same `reddit_id` score updates are never duplicates.
**Acceptance criteria:**
- Each filter is a separate, independently-testable function; `filter_items` composes them
- Items dropped at each stage logged at DEBUG with reason
- Count of items dropped per stage returned alongside filtered list (including duplicate count)
- Bot patterns, spam regexes, and min length all configurable
- `content_fingerprint` set on all items passing filters (before duplicate check)
- Cross-post duplicates (same fingerprint, different `reddit_id`) marked `is_duplicate = True`; excluded from output
- `DUPLICATE_WINDOW_HOURS` configurable via env var (default: 24)
- Unit tests cover each filter in isolation; duplicate detection: same fingerprint different `reddit_id` → marked duplicate; same `reddit_id` → NOT duplicate

---

### TASK-S18: Deduplication — batch upsert with composite key
**Domain:** Scraping
**Depends on:** TASK-S03, TASK-S04, TASK-S27
**Description:** Implement `scraper/pipeline/deduplicator.py` with `deduplicate_and_store(items: List[RawRedditItem], repo: Repository) -> DeduplicationResult`. Calls `repo.upsert_raw_items_batch()` (from TASK-S27) for the full batch in a single SQL statement. Returns counts of `inserted`, `score_updated`, and `unchanged`.
**Acceptance criteria:**
- Calls `upsert_raw_items_batch` once per run (not once per item — N roundtrips replaced by 1)
- Dedup key is `(reddit_id, ticker_mentioned)` composite — the same `reddit_id` with different `ticker_mentioned` values are distinct rows, not conflicts
- `inserted + score_updated + unchanged == len(items)` where `len(items)` is the post-expansion count (after multi-ticker splitting in the pipeline)
- `score_updated` detected via `RETURNING xmax`
- Unit tests mock the repository and verify correct counts for all three cases including multi-ticker expansion

---

### TASK-S19: 30-day data retention job
**Domain:** Scraping
**Depends on:** TASK-S02, TASK-S03
**Description:** Implement `scraper/pipeline/retention.py` with `apply_retention_policy(repo: Repository, retention_days: int)` deleting rows from `reddit_raw` where `timestamp < NOW() - INTERVAL '{retention_days} days'`. Invoked by the scheduler after each scrape run.
**Acceptance criteria:**
- Uses a parameterized query (no string interpolation of `retention_days`)
- Logs the number of rows deleted at INFO level
- Does not delete rows within the retention window
- `retention_days` configurable via `RETENTION_DAYS` env var (default: 30)
- Unit test verifies correct SQL for both 30-day and 7-day configs

---

### TASK-S20: Redis pub/sub between scraper and sentiment processor
**Domain:** Scraping
**Depends on:** TASK-S13, TASK-S17, TASK-S18
**Description:** Implement `scraper/messaging.py` publishing a JSON notification to Redis channel `sse:scraper:run_complete` after each successful scrape-and-store cycle. Payload: `{"run_id": str, "items_stored": int, "timestamp": str, "subreddits": [str]}`. System must function correctly if Redis is unavailable.
**Acceptance criteria:**
- If `REDIS_URL` env var absent, publish step silently skipped with DEBUG log
- If Redis configured but publish fails, logged as WARNING and scrape run not aborted
- Channel name is a constant in `constants.py`
- Unit tests verify: publish called with correct payload when Redis available; skipped when unconfigured; run continues when publish fails

---

### TASK-S21: Degraded mode — staleness detection and hold-last-price behavior
**Domain:** Scraping
**Depends on:** TASK-S03, TASK-S14
**Description:** Implement `scraper/degraded_mode.py` with `check_and_report_staleness(repo: Repository) -> StalenessStatus`. Returns `is_stale: bool`, `seconds_since_last_update: int`, `stale_since: Optional[datetime]`. Writes result to Redis key `sse:scraper:staleness` for the frontend. Staleness threshold configurable (`STALENESS_THRESHOLD_SECONDS`, default: 3600).
**Acceptance criteria:**
- `is_stale` is `True` when `seconds_since_last_update >= STALENESS_THRESHOLD_SECONDS`
- Redis write skipped if Redis unavailable (same pattern as TASK-S20)
- No synthetic or fabricated sentiment data generated under any circumstances
- Unit tests cover: fresh data, stale data, Redis unavailable

---

### TASK-S22: Scraper health check endpoint
**Domain:** Scraping
**Depends on:** TASK-S21, TASK-S03
**Description:** Minimal HTTP health check server (`scraper/healthcheck.py`). `GET /health` returns JSON with staleness status, last successful run time, and top-level `status` field: `"ok"`, `"degraded"`, or `"down"`. Runs in a background thread alongside the scheduler.
**Acceptance criteria:**
- Returns HTTP 200 `{"status": "ok"}` when healthy
- Returns HTTP 200 `{"status": "degraded", "stale_since": "..."}` when stale
- Returns HTTP 503 `{"status": "down"}` when `seconds_since_last_update > 2 * STALENESS_THRESHOLD_SECONDS`
- Health server starts in under 2 seconds and does not block the scheduler
- Integration test hits the endpoint and verifies all three status cases

---

### TASK-S23: Ticker detection validated against real Reddit data
**Domain:** Scraping
**Depends on:** TASK-S15, TASK-S16
**Description:** Collect 50+ real Reddit post/comment texts from each of the four target subreddits as test fixtures in `tests/fixtures/real_reddit_samples.json`. Write a parametrized pytest suite that runs `detect_tickers()` against every sample and asserts expected tickers (manually verified ground truth) are found with no false positives.
**Acceptance criteria:**
- At least 50 samples total, at least 10 from each target subreddit
- Each sample: raw text, expected tickers (may be empty), subreddit source
- Precision and recall computed and printed in test output
- Test fails if precision < 0.95 or recall < 0.90
- All fixture data anonymized (no usernames)
- Fixture file committed alongside the test file

---

### TASK-S24: End-to-end pipeline integration test
**Domain:** Scraping
**Depends on:** TASK-S13, TASK-S17, TASK-S18, TASK-S19
**Description:** End-to-end integration test (`tests/integration/test_pipeline_e2e.py`) exercising the full path from HTML fixture files through scraper → ticker detector → quality filter → deduplicator → real PostgreSQL + TimescaleDB instance.
**Acceptance criteria:**
- Uses real (Docker-based) PostgreSQL + TimescaleDB, not mocks
- Marked `@pytest.mark.integration`, skipped unless `RUN_INTEGRATION_TESTS=true`
- Runs full orchestrator with fixture HTML files (no live network calls)
- Asserts row counts after first run (insert) and second run (score update, no new rows)
- Asserts retention deletes only rows older than the configured window
- Test database torn down after each run (no state leakage)

---

### TASK-S25: Scrape run metrics and observability
**Domain:** Scraping
**Depends on:** TASK-S01, TASK-OPS34
**Description:** Configure structured JSON logging for the scraper service using `sse_common.logging_config.configure_logging("scraper", log_level)` from the shared `sse-common` package (TASK-OPS34). Define `scraper/metrics.py` tracking per-run counters: `items_scraped`, `items_filtered`, `items_inserted`, `items_score_updated`, `items_duplicate`, `fallback_used`. Counters logged at INFO at end of each run. Separate metrics HTTP endpoint lives in TASK-S26 (health check server).
**Acceptance criteria:**
- All log calls use `sse_common.logging_config.configure_logging()` — no custom logging setup in this file
- Every log entry automatically includes `service: "scraper"` from the shared config
- `run_id` is a UUID generated at scheduler run start and threaded through all downstream calls via structlog context variable
- `items_filtered + items_inserted + items_score_updated + items_duplicate <= items_scraped`
- `items_duplicate` counter tracks items marked `is_duplicate = True` by TASK-S17
- Unit test verifies metric counters produce correct totals for a mock run

---

### TASK-S26: Docker container and docker-compose configuration for scraper service
**Domain:** Scraping
**Depends on:** TASK-S01, TASK-S22
**Description:** `Dockerfile` for the scraper service and `docker-compose.yml` service entry bringing up scraper alongside PostgreSQL + TimescaleDB and Redis. Playwright browser binaries installed in image. All env vars documented in `.env.example`.
**Acceptance criteria:**
- `docker compose up scraper` starts service without errors
- Playwright browsers installed and functional inside container
- Scraper health check endpoint accessible from host on configurable port
- All required env vars in `.env.example` with descriptions and example values
- Container runs as non-root user
- `docker compose up db` starts working TimescaleDB instance with schema from `database/migrations/` applied via init script

---

### TASK-S27: Batch upsert repository method
**Domain:** Scraping
**Depends on:** TASK-S03
**Description:** Add `upsert_raw_items_batch(items: list[RawRedditItem]) -> DeduplicationResult` to `scraper/db/repository.py` using `psycopg2.extras.execute_values()` with a single `INSERT ... ON CONFLICT (reddit_id, ticker_mentioned) DO UPDATE SET score = EXCLUDED.score, content_fingerprint = EXCLUDED.content_fingerprint, is_duplicate = EXCLUDED.is_duplicate RETURNING xmax` statement. Replaces the per-item loop in TASK-S18.
**Acceptance criteria:**
- `upsert_raw_items_batch` issues exactly one SQL statement regardless of batch size
- Uses `psycopg2.extras.execute_values()` with `page_size` from `DB_BATCH_PAGE_SIZE` env var (default: 500)
- Returns `DeduplicationResult` with correct `inserted`, `score_updated`, `unchanged` counts derived from `xmax` values
- Empty list input executes no SQL and returns zeroed `DeduplicationResult`
- Singular `upsert_raw_item` retained as thin wrapper calling the batch method with a single-item list
- Unit tests: 500-item batch issues one SQL call; correct counts for mixed insert/update/unchanged; empty batch returns zeros; conflict target verified as `(reddit_id, ticker_mentioned)`

---

### TASK-S28: CAPTCHA detection and fallback skip in Playwright scraper
**Domain:** Scraping
**Depends on:** TASK-S10
**Description:** Add CAPTCHA detection to `PlaywrightScraper` by checking page content for known CAPTCHA indicators after page load. On detection, log WARNING and raise `CaptchaDetectedError` immediately so the orchestrator advances to the RSS fallback.
**Acceptance criteria:**
- `CaptchaDetectedError(ScraperExhaustedError)` defined in `scraper/exceptions.py`
- Checks after page load: `iframe[src*="recaptcha"]` selector present, URL containing `captcha`, page title containing "Access Denied" or "Robot"
- On detection: logs `WARNING "CAPTCHA detected on {url} for subreddit {subreddit} — skipping Playwright fallback"` and raises `CaptchaDetectedError` with no retry budget consumed
- `SCRAPER_CAPTCHA_SERVICE_URL` env var: when set and non-empty, forward to service and inject solved token; when empty, immediately raise `CaptchaDetectedError`
- Orchestrator (TASK-S13) treats `CaptchaDetectedError` identically to `ScraperExhaustedError` for fallback advancement
- Unit test: mock page with reCAPTCHA iframe → `CaptchaDetectedError` with no retry attempts; mock clean page → normal scraping

---

### TASK-S29: Concurrent subreddit scraping with two-tier semaphore
**Domain:** Scraping
**Depends on:** TASK-S13, TASK-S28
**Description:** Replace the sequential per-subreddit loop in `scraper/orchestrator.py` with `asyncio.gather()`. All subreddits scrape concurrently (HTML/RSS path) but Playwright instances are serialized via a separate inner semaphore to prevent memory spikes on the target droplet.

**Two-tier semaphore design:**
- **Outer semaphore (`MAX_CONCURRENT_SUBREDDITS`, default: 4):** Controls full fallback-chain concurrency. HTML/BeautifulSoup and RSS scrapers are lightweight at this level.
- **Inner semaphore (`PLAYWRIGHT_MAX_CONCURRENT`, default: 1):** Shared across all subreddit tasks. Only one headless Chromium process runs at a time (~300–500MB each), preventing OOM on a 4GB droplet shared with 8 other services.
**Acceptance criteria:**
- `asyncio.gather(*tasks, return_exceptions=True)` runs one task per subreddit concurrently
- `MAX_CONCURRENT_SUBREDDITS` (default: 4, min: 1) controls outer `asyncio.Semaphore`
- `PLAYWRIGHT_MAX_CONCURRENT` (default: 1, max: 2) controls a shared inner semaphore injected into `PlaywrightScraper` at construction
- `PlaywrightScraper.scrape()` acquires and releases inner semaphore around browser launch (including on exception)
- Exceptions from `gather` logged at ERROR; other subreddits continue unaffected
- Wall-clock time for 4 subreddits on HTML/RSS path ≤ 1.25× slowest single subreddit; Playwright serialization is expected
- Unit test: 4 subreddits all reaching Playwright → runs serialized, not concurrent

---

### TASK-S30: Adaptive scrape interval with health-score backoff
**Domain:** Scraping
**Depends on:** TASK-S14
**Description:** Track a rolling `health_score` (0.0–1.0) based on the success rate of the last N scrape runs. When health drops, multiply the next interval by a backoff factor; when health recovers, return to normal.
**Acceptance criteria:**
- Scheduler maintains a fixed-length deque of last `HEALTH_WINDOW_SIZE` run outcomes (bool), default 10
- `health_score = successes / HEALTH_WINDOW_SIZE`
- `health_score < HEALTH_THRESHOLD_LOW` (default: 0.5): next interval = `random.uniform(MIN, MAX) * BACKOFF_FACTOR` (default: 2.0), capped at `SCRAPE_INTERVAL_MAX_BACKOFF` (default: 60 min)
- `health_score > HEALTH_THRESHOLD_HIGH` (default: 0.8): return to normal randomized interval
- Interval changes logged at INFO: `"health_score={:.2f} — interval adjusted to {:.0f}s ({:.1f}x backoff)"`
- All thresholds configurable: `HEALTH_WINDOW_SIZE`, `HEALTH_THRESHOLD_LOW`, `HEALTH_THRESHOLD_HIGH`, `SCRAPE_BACKOFF_FACTOR`, `SCRAPE_INTERVAL_MAX_BACKOFF`
- Unit tests: 6/10 failures → backoff applied; 9/10 successes → normal interval; interval never exceeds max

---

### TASK-S31: Research spike — verify Pushshift and alternative API availability
**Domain:** Scraping
**Depends on:** none
**Description:** Time-boxed research spike (max 4 hours) to test actual availability of Pushshift, Pullpush, and Arctic Shift APIs. Document results in `docs/pushshift_availability_report.md`. TASK-S12 is BLOCKED until this spike concludes.
**Acceptance criteria:**
- Each API tested with a concrete HTTP request to its submission search endpoint
- Report documents per API: HTTP status, authentication requirements, rate limits, most-recent post timestamp, comment endpoint availability
- Report concludes with one of three recommendations: (A) implement against a specific working API, (B) implement against Reddit's official OAuth API (free tier: 100 req/min), or (C) remove TASK-S12 and rely on RSS as last-resort fallback
- If recommendation (B): a new TASK-S33 is created for a Reddit OAuth scraper
- TASK-S12 remains BLOCKED until this task delivers its written recommendation

---

### TASK-S32: HTML structural validation and `new.reddit.com` parser
**Domain:** Scraping
**Depends on:** TASK-S07, TASK-S10
**Description:** Add structural validation to `ListingScraper` asserting expected CSS selectors exist before parsing. Raise `StructureChangedError` on mismatch. Add a secondary `new.reddit.com` JSON API parser within `PlaywrightScraper` as a lower-brittleness alternative.
**Acceptance criteria:**
- `StructureChangedError(ScraperError)` defined in `scraper/exceptions.py` with fields `url`, `expected_selector`, `page_snippet`
- `ListingScraper` validates presence of: `div.thing`, `time[datetime]`, `a.title`, `span.score`. Missing any → `StructureChangedError`
- `StructureChangedError` logged at CRITICAL (not ERROR) to distinguish Reddit HTML changes from network errors
- Orchestrator treats `StructureChangedError` as signal to skip to Playwright with an additional log entry
- `PlaywrightScraper` includes secondary parser targeting `new.reddit.com` JSON API (`/r/{subreddit}.json?raw_json=1`), activated by `PLAYWRIGHT_TARGET=new_reddit_json` env var
- `docs/scraper_structure_assumptions.md` documents all CSS selectors relied upon
- Fixture test: removing `div.thing` from saved HTML → `StructureChangedError` raised

# Requirements Spec — V1 Gap Closure

**Product:** Sentiment Stock Exchange (SSE)
**Author:** Aragorn (Product Manager)
**Date:** 2026-03-30
**Status:** APPROVED

---

## 1. Context

SSE is a prototype that calculates hypothetical "sentiment-adjusted" stock prices based on Reddit discussion. The codebase has 126 files and a working happy path, but an audit revealed that only 19% of planned tasks were fully implemented. This spec defines the V1 gap closure scope — the work needed to make the prototype credible and complete.

**Target user:** Single developer (the stakeholder). This is a working prototype, not a production-scale system. Correctness and completeness are prioritized over scalability.

---

## 2. Scope

### 2.1 In Scope (Must-Have)

#### Tier 1 — Core Functionality

**REQ-01: Comment Scraping**
- Scraper must fetch Reddit comments in addition to post titles/selftext
- Comments must be stored in the existing `comment_sentiment` table schema
- Comment content must flow through the same sentiment pipeline as posts
- Unique constraint on `(reddit_comment_id, backend)` must be respected

**REQ-02: NLP Weighting Model**
- Sentiment aggregation must replace raw `AVG(compound)` with a weighted model
- Four weighting factors required:
  - **Upvote magnitude:** Higher-upvoted posts/comments contribute more to the aggregate
  - **Temporal decay:** Recent posts weighted more heavily than older ones
  - **Volume weighting:** Tickers with more mentions get a volume-scaled signal
  - **Delta-based pricing:** Price adjustment proportional to sentiment delta (change over time), not absolute sentiment
- Weighting parameters must be configurable per pricing configuration (stored in `pricing_configurations` JSONB)

**REQ-03: Quality Filtering**
- Scraper/processor must filter out:
  - Deleted posts/comments (`[deleted]`, `[removed]`)
  - Known bot accounts (configurable bot username list)
  - Spam (duplicate content detection)
  - Below minimum content length (configurable threshold)
- Filtered items must be excluded before sentiment calculation, not after

**REQ-04: Financial Text Preprocessor**
- Pre-processing step before sentiment analysis that handles:
  - Reddit financial slang expansion (e.g., "bullish af" → "very bullish", "to the moon" → "strongly positive")
  - Emoji sentiment mapping (e.g., rocket → positive, skull → negative)
  - Ticker symbol isolation (e.g., "$AAPL" → strip "$" before NLP, preserve for matching)
  - Cashtag and hashtag normalization
- Must be applied to all text before passing to VADER/TextBlob backends

#### Tier 2 — Resilience & Operations

**REQ-05: Service Health Endpoints**
- Each pipeline service (scraper, processor, pricing_engine) must expose a `GET /health` endpoint
- Health response must include: service name, status (healthy/degraded/unhealthy), uptime, last successful run timestamp
- Docker healthcheck must be configured to use these endpoints

**REQ-06: Processor Redis Resilience**
- Processor must not hard-exit when Redis is unavailable
- Fallback behavior: switch to poll-only mode (check database on interval instead of listening to Redis pub/sub)
- Log a warning when falling back, and attempt to reconnect to Redis periodically
- Resume pub/sub mode when Redis becomes available again

**REQ-07: API Rate Limiting**
- Backend API must enforce rate limits using slowapi (or equivalent)
- Default limits: 60 requests/minute per IP for general endpoints, 10 requests/minute for SSE stream connections
- Rate limit headers must be included in responses (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset)
- 429 response with Retry-After header when limit exceeded

#### Tier 3 — Frontend

**REQ-08: Frontend Chart Components**
- Implement per-ticker price history chart (line chart showing real price vs sentiment-adjusted price over time)
- Implement scenario comparison visualization (overlay multiple pricing configs on same chart)
- Implement SparklineChart for the market overview table (inline mini-charts per ticker)
- Implement DivergenceGauge showing gap between real and sentiment price
- Charts must update when new data arrives via SSE

#### Tier 4 — Testing & CI/CD

**REQ-09: Service Test Coverage**
- Scraper: unit tests for Reddit client, comment parsing, quality filtering, storage
- Processor: unit tests for VADER pipeline, TextBlob pipeline, weighting model, text preprocessor
- Pricing engine: unit tests for formula calculation, config loading, pub/sub handling
- All new code must have corresponding tests

**REQ-10: GitHub Actions CI**
- CI pipeline that runs on push to main and on pull requests
- Steps: lint (ruff), type check (mypy for Python), test (pytest for backend services), frontend build + test
- Pipeline must fail on any test failure or lint error

**REQ-11: Frontend Tests**
- Unit tests with Vitest + React Testing Library for key components
- At minimum: market overview table, chart components, SSE connection handling
- Tests must run as part of CI pipeline

**REQ-12: Continuous Aggregate Optimization**
- 1-week and 1-month history queries must read from TimescaleDB continuous aggregates instead of scanning raw hypertable
- Verify the existing continuous aggregate is correctly defined and queryable

#### Tier 5 — Documentation & Hardening

**REQ-13: Documentation**
- `docs/` directory with:
  - README/overview of the system architecture
  - Runbook for local development setup
  - Runbook for common operations (reset DB, restart services, check logs)
  - Security considerations document

**REQ-14: Container Read-Only Filesystems**
- All application containers must run with `read_only: true` in docker-compose
- Writable tmpfs mounts for directories that need write access (e.g., `/tmp`, log dirs)

**REQ-15: Redis Authentication**
- Redis must require password authentication
- Password configured via environment variable, not hardcoded
- All services that connect to Redis must use the password

**REQ-16: Automated DB Backups**
- pg_dump-based backup script or container
- Runs on a configurable schedule (default: daily)
- Retains last N backups (configurable, default: 7)
- Backup location: mounted volume

---

### 2.2 Nice-to-Have

These may be included if time permits, but are not required for V1 sign-off:

- **NH-01:** SentimentAnalyzer ABC abstraction with factory/registry
- **NH-02:** Market hours awareness (detect open/closed, adjust fetch frequency)
- **NH-03:** Pricing subscriber exponential backoff on Redis disconnect
- **NH-04:** Data retention job for reddit_raw table
- **NH-05:** React Router for URL navigation
- **NH-06:** Price flash animation on SSE updates
- **NH-07:** Locust load test

### 2.3 Out of Scope (Deferred)

- FinBERT backend (formula fix deferred; V1 ships with VADER/TextBlob only)
- Fallback scraping chain (HTML/Playwright/RSS)
- Accessibility (aria-live, keyboard nav, chart roles)
- Mobile responsiveness
- Multi-user auth / user accounts
- Horizontal scaling / load balancing

---

## 3. Success Criteria

V1 is complete when:

1. All 16 must-have requirements (REQ-01 through REQ-16) are implemented and working
2. All new code has corresponding tests that pass
3. CI pipeline runs green on main branch
4. The full stack boots with `docker compose up --build` and the happy path works end-to-end:
   - Scraper fetches posts AND comments from Reddit
   - Quality filtering removes junk before processing
   - Financial text preprocessor cleans text before NLP
   - Weighted sentiment is calculated and stored
   - Pricing engine computes sentiment-adjusted prices
   - Frontend displays charts with real vs sentiment price
   - SSE streaming delivers live updates

---

## 4. Constraints

- **Single user:** No need for auth, rate limiting is for safety, not multi-tenancy
- **Prototype:** Correctness over performance. No SLA targets.
- **Existing stack:** Must work within the current technology choices (FastAPI, asyncpg, React/Vite, TimescaleDB, Redis, Docker)
- **No timeline pressure:** Done when it's done. Quality over speed.

---

## 5. Dependencies

- Existing codebase must remain functional during incremental gap closure
- Reddit JSON API must remain accessible (no fallback chain in V1)
- Docker Compose local development environment

---

## Sign-Off

- [x] Stakeholder (User) — approved 2026-03-30
- [x] Product Manager (Aragorn) — approved 2026-03-30

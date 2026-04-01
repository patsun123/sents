# Research: Resilient Reddit Sentiment Scraping Pipeline

**Phase**: 0 — Research & Unknowns
**Date**: 2026-03-09
**Feature**: [spec.md](spec.md) | [plan.md](plan.md)

---

## R-001: Reddit Public `.json` Endpoint

**Decision**: Use Reddit's public `.json` endpoint as the primary scraping lane (e.g., `https://www.reddit.com/r/wallstreetbets/new/.json?limit=100`).

**Findings**:
- Appending `.json` to any Reddit URL returns structured JSON with no OAuth required
- Default rate limit for unauthenticated requests: ~1 request/second per IP (Reddit's informal guideline)
- Required headers: `User-Agent` must be set; Reddit blocks requests with default library User-Agents
- Pagination: use `after` parameter with the last post's `fullname` to paginate; `limit` max is 100 per request
- The `created_utc` field on each comment enables incremental collection (only fetch newer than last run)
- Subreddit `/new/.json` returns most recent posts; `/comments/{post_id}/.json` returns full comment trees

**Anti-blocking measures**:
- Rotate `User-Agent` strings across a pool of realistic browser/bot identifiers
- Enforce minimum 1-second delay between requests (configurable)
- Detect 429 responses and apply exponential backoff (2s → 4s → 8s → 16s → give up, log, continue to next source)
- Detect 403/banned responses — mark subreddit as unavailable, skip for remainder of cycle, alert operator

**Alternatives considered**:
- Pushshift API: deprecated and unreliable as of 2023
- Reddit RSS feeds: less structured, harder to parse, limited data

---

## R-002: PRAW OAuth Fallback Lane

**Decision**: Implement PRAW OAuth as a fallback lane, activated when the `.json` endpoint returns sustained errors.

**Findings**:
- PRAW with OAuth: 60 requests/minute (authenticated) vs ~1 req/sec unauthenticated — meaningfully higher
- Requires a Reddit app registration (free): client_id, client_secret, username, password
- PRAW uses OAuth2 script flow for bot accounts — straightforward to set up
- Credentials stored as environment variables, never in code
- PRAW `subreddit.new(limit=100)` is the equivalent of the `.json` endpoint
- Fallback trigger: 3 consecutive 429s or 403s from primary lane within a single cycle → switch to PRAW for that cycle

**Risk**: Reddit's API Terms of Service require apps to identify themselves. SentiX qualifies as a personal project bot — low legal risk at current scale.

**Alternatives considered**:
- Proxy rotation with residential proxies: cost (~$50–200/month) unjustified for a solo project at launch; revisit if Reddit aggressively blocks
- Multiple Reddit accounts: higher operational complexity, marginal gain over PRAW OAuth

---

## R-003: FinBERT Local Availability

**Decision**: FinBERT is NOT used as the default; VADER is default. FinBERT is supported via the pluggable interface but requires explicit configuration.

**Findings**:
- FinBERT (ProsusAI/finbert on HuggingFace): ~400MB model download, requires PyTorch
- CPU inference: ~200–500ms per comment — acceptable for a 15-minute batch pipeline
- GPU inference: ~5–20ms per comment — optional, not required at current scale
- RAM requirement: ~2GB for model + inference — feasible on standard VPS (4GB+ RAM)
- HuggingFace `transformers` library handles download and caching automatically
- FinBERT is finance-domain fine-tuned on Financial PhraseBank — handles "bull", "moon", "short squeeze" better than VADER
- **Local availability concern resolved**: FinBERT runs on CPU. No GPU required. Any standard deployment target (Fly.io, Render, Railway) can run it. Download happens once on first use; cached thereafter.

**Classifier interface design**: Both VADER and FinBERT implement the same `SentimentClassifier` Protocol. Active classifier is selected via `CLASSIFIER_BACKEND` environment variable (`vader` or `finbert`). Default: `vader`.

**Alternatives considered**:
- TextBlob: Less accurate on financial text than VADER; ruled out
- OpenAI API for classification: External dependency, costs money per call, latency unpredictable; ruled out for core pipeline
- Custom fine-tuned model: Future option once enough labeled data accumulated from signal storage

---

## R-004: Ticker Extraction and Disambiguation

**Decision**: Two-stage extraction — regex pattern match, then disambiguation via a curated false-positive blocklist.

**Findings**:
- WSB-style ticker mentions appear as `$GME`, `$AMC`, or bare `GME`, `TSLA` in all-caps
- Regex pattern: `\$[A-Z]{1,5}` for explicit mentions; `\b[A-Z]{1,5}\b` for bare caps (higher false positive rate)
- High false-positive symbols (common English words that are valid tickers): `IT`, `NOW`, `ARE`, `ON`, `FOR`, `A`, `I`, `GO`, `BE`, `AT`, `IN`, `OR`, `TO`, `DO`
- **Disambiguation approach**: Maintain a blocklist of common English words; any matched symbol in the blocklist is discarded. Explicit `$TICKER` mentions bypass the blocklist (strong signal).
- Full ticker universe reference: Use a publicly available list of NYSE/NASDAQ listed tickers (~10k symbols) to validate that extracted symbols are real tickers (prevents random all-caps words from being scored)
- Blocklist and ticker universe stored in configuration — operator-updatable without code changes

**Alternatives considered**:
- NLP-based NER for ticker detection: Overkill at this stage; regex + blocklist is simpler and faster
- Only score `$TICKER` explicit mentions: Too restrictive — misses most WSB-style organic mentions

---

## R-005: Scheduler — APScheduler vs asyncio

**Decision**: APScheduler 3.x with `AsyncIOScheduler` for the 15-minute cycle.

**Findings**:
- APScheduler `AsyncIOScheduler`: runs inside the Python asyncio event loop; no separate process or thread needed
- `IntervalTrigger(minutes=15)` with `max_instances=1` enforces sequential execution (built-in queue behaviour)
- `max_instances=1` means if a job is still running when the next interval fires, APScheduler queues it automatically — exactly matching FR-001
- Integrates naturally with `asyncio` and `httpx` for async HTTP scraping
- Celery Beat: overkill — adds Redis as a message broker dependency just for scheduling; ruled out
- Simple `asyncio.sleep()` loop: fragile, harder to observe and control; ruled out

**Persistence**: APScheduler can persist job state to PostgreSQL (survives restarts) — enable this to prevent duplicate runs after container restart.

---

## R-006: PostgreSQL Schema for Time-Series Signals

**Decision**: Standard PostgreSQL with a time-indexed `sentiment_signals` table. TimescaleDB is not used at launch.

**Findings**:
- TimescaleDB adds significant operational complexity (extension installation, chunk management)
- At initial scale (3 subreddits, 15-min cycles), standard PostgreSQL with a `BTREE` index on `(ticker_symbol, collected_at)` is sufficient
- Expected signal volume: r/wallstreetbets averages ~500–2000 comments/hour; 15-min window = ~125–500 comments; typical ticker mentions per comment: 1–3 — estimated 200–1500 signals per cycle
- Daily signal volume at steady state: ~20,000–150,000 rows — trivial for PostgreSQL
- Partitioning by month recommended at 90-day mark if query performance degrades
- TimescaleDB can be added later as a drop-in if needed (same query interface)

---

## R-007: Upvote Weight Normalization

**Decision**: Use raw upvote count as weight at launch; add time-decay normalization as a future algorithm variant.

**Findings**:
- Raw upvote count: simple, transparent, easy to explain and tune
- Problem: a 3-day-old post with 50k upvotes will dominate over a 1-hour-old post with 500 upvotes, even if both are collected in the same cycle
- Since we store raw signals (upvote weight as collected), time-decay normalization can be applied as a separate scoring algorithm without re-collection
- Launch approach: use raw upvotes — this is the simplest readable signal. Revisit in algorithm tuning phase (Priority 4 in development roadmap)
- Scores derived from signals will always reflect the algorithm's chosen weighting strategy — the stored signal itself is algorithm-agnostic

---

## Outstanding Items (Deferred to Implementation)

- **Reddit app registration**: Developer must register a Reddit app at reddit.com/prefs/apps for PRAW OAuth credentials before WP02
- **Sentry DSN**: Obtain Sentry project DSN before WP07
- **NYSE/NASDAQ ticker universe**: Download and version a current ticker list before WP03 (available from SEC EDGAR or financial data providers at no cost)
- **FinBERT evaluation**: Run WP04 classifier interface first; FinBERT evaluation is Priority 2 in the development roadmap (separate feature after pipeline is stable)

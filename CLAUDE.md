# CLAUDE.md - SentiX

> Agent context for Claude Code. Updated by /spec-kitty.plan.
> See .kittify/memory/constitution.md for full project standards.

## Project

SentiX - a web application showing real vs. sentiment-derived
stock prices based on Reddit comment analysis. Solo project.

## Active Feature: 001 - Resilient Reddit Sentiment Scraping Pipeline

**Spec**: kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/spec.md
**Plan**: kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/plan.md
**Data model**: kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/data-model.md
**Contracts**: kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/contracts/

### What this feature builds

A standalone Python worker service (`worker/`) that:
1. Scrapes Reddit comments every 15 minutes from configurable subreddits
2. Extracts ticker mentions dynamically (no pre-configured list)
3. Classifies sentiment (positive/negative) via pluggable interface (VADER default)
4. Stores raw signals to PostgreSQL - NO pre-computed scores, NO PII
5. Self-heals via Docker `restart: unless-stopped`

### Critical architectural decisions

- **Signal-first storage**: Store (ticker, polarity, upvote_weight, timestamp) only.
  Never compute scores before storing. Algorithms run against signals later.
- **Pluggable classifiers**: `SentimentClassifier` Protocol in `worker/src/classifiers/base.py`.
  VADER is default. FinBERT slots in via `CLASSIFIER_BACKEND=finbert` env var.
- **Dual-lane scraping**: Primary = Reddit public .json endpoint with User-Agent rotation.
  Fallback = PRAW OAuth after 3 consecutive rate-limit errors.
- **Sequential cycles**: APScheduler `max_instances=1` enforces no concurrent runs.
  Overflow cycles queue automatically.
- **Zero PII**: No username, comment ID, post ID, or comment text is ever persisted.

### Source structure (to be created)

```
worker/
  src/
    pipeline/      # scheduler.py, runner.py
    scrapers/      # base.py (Protocol), json_endpoint.py, praw_oauth.py
    classifiers/   # base.py (Protocol), vader.py
    tickers/       # extractor.py, disambiguator.py
    storage/       # models.py, signals.py, runs.py
    alerting/      # Sentry integration
    config.py
  tests/
    unit/
    integration/
docker-compose.yml  # root level, shared across services
```

### Tech stack

- Python 3.12+, APScheduler, httpx, PRAW, VADER, SQLAlchemy 2.x + asyncpg
- PostgreSQL (signals, runs, sources), Redis (cached scored_results for API)
- Docker + Docker Compose
- pytest 90%+, ruff, mypy, bandit

### Constitution highlights

- Keep it simple - no over-engineering
- 90%+ test coverage, all external calls mocked
- Full docstrings on all public APIs
- Zero PII at any stage
- Sentry for alerting, structured logging throughout

# Implementation Plan: Resilient Reddit Sentiment Scraping Pipeline

**Branch**: `001-resilient-reddit-sentiment-scraping-pipeline` | **Date**: 2026-03-09 | **Spec**: [spec.md](spec.md)

---

## Summary

Build a fault-tolerant, standalone Python worker service that scrapes Reddit comments from configurable subreddits on a 15-minute schedule, extracts ticker mentions dynamically, classifies sentiment via a pluggable classifier interface (VADER default, FinBERT-ready), and persists only algorithm-agnostic raw signals (ticker, polarity, upvote weight, timestamp) to PostgreSQL. The pipeline uses Reddit's public `.json` endpoint as primary scraping lane, falling back to PRAW OAuth when blocked. All cycles are sequential (no concurrent runs), self-healing via Docker `restart: unless-stopped`, and observable via structured logging and Sentry alerting.

---

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: APScheduler (scheduling), httpx (async HTTP for `.json` endpoint), PRAW (OAuth fallback), VADER (default classifier), SQLAlchemy 2.x + asyncpg (storage), Sentry SDK (alerting), ruff + mypy + bandit (CI quality)
**Storage**: PostgreSQL (sentiment signals, collection runs, data sources) + Redis (cached scored results consumed by API layer)
**Testing**: pytest with pytest-asyncio, 90%+ line coverage; 100% on classifier interface, scraper interface, and signal storage; all external calls mocked
**Target Platform**: Linux Docker container (standalone worker service)
**Project Type**: Standalone background worker (no HTTP server — data consumed via shared PostgreSQL/Redis)
**Performance Goals**: Complete full collection cycle across 3 subreddits within 15 minutes; signal write throughput sufficient for r/wallstreetbets volume peaks
**Constraints**: Zero PII stored at any stage; sequential cycle execution (no concurrency); self-healing with no manual intervention; p95 collection latency < 15 minutes
**Scale/Scope**: Initial 3 subreddits (r/wallstreetbets, r/stocks, r/investing); extensible to N sources via config; signals retained indefinitely as source of truth

---

## Constitution Check

*GATE: Must pass before Phase 0 research.*

| Requirement | Status | Notes |
|-------------|--------|-------|
| Python 3.12+ | ✅ Pass | Worker is Python 3.12+ |
| FastAPI | ✅ N/A | Worker has no HTTP layer; FastAPI used in API service (separate feature) |
| PostgreSQL | ✅ Pass | Primary signal store |
| Redis | ✅ Pass | Scored results cache for API layer |
| Docker + Docker Compose | ✅ Pass | Standalone container with `restart: unless-stopped` |
| pytest 90%+ coverage | ✅ Pass | Planned; all external calls mocked |
| ruff + mypy + bandit | ✅ Pass | Included in CI pipeline |
| Zero PII | ✅ Pass | Core non-negotiable; FR-005 |
| Sentry alerting | ✅ Pass | Error threshold alerts |
| Keep it simple | ✅ Pass | No message queues, no orchestration frameworks; just a scheduler + async tasks |
| VADER/Transformers | ✅ Pass | VADER as default; pluggable interface accommodates Transformers/FinBERT |

**Complexity Tracking**: No violations. No additional justification required.

---

## Project Structure

### Documentation (this feature)

```
kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/
├── plan.md              ← This file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/           ← Phase 1 output
│   ├── classifier-interface.md
│   ├── scraper-interface.md
│   └── schema.sql
└── tasks.md             ← Phase 2 output (/spec-kitty.tasks)
```

### Source Code (repository root)

```
worker/                          # Standalone scraping pipeline service
├── src/
│   ├── pipeline/                # Core orchestration
│   │   ├── __init__.py
│   │   ├── scheduler.py         # APScheduler 15-min cycle + sequential queue
│   │   └── runner.py            # Single cycle executor (collect → extract → classify → store)
│   ├── scrapers/                # Pluggable Reddit data sources
│   │   ├── __init__.py
│   │   ├── base.py              # RedditScraper Protocol (interface)
│   │   ├── json_endpoint.py     # Primary: Reddit public .json + User-Agent rotation
│   │   └── praw_oauth.py        # Fallback: PRAW OAuth authenticated scraper
│   ├── classifiers/             # Pluggable sentiment classifiers
│   │   ├── __init__.py
│   │   ├── base.py              # SentimentClassifier Protocol (interface)
│   │   └── vader.py             # Default: VADER implementation
│   ├── tickers/                 # Ticker extraction and disambiguation
│   │   ├── __init__.py
│   │   ├── extractor.py         # Regex + $TICKER / TICKER pattern detection
│   │   └── disambiguator.py     # False-positive suppression (common English words)
│   ├── storage/                 # Persistence layer
│   │   ├── __init__.py
│   │   ├── models.py            # SQLAlchemy ORM models
│   │   ├── signals.py           # SentimentSignal CRUD
│   │   └── runs.py              # CollectionRun CRUD
│   ├── alerting/                # Sentry integration
│   │   └── __init__.py
│   └── config.py                # Settings (sources, thresholds, credentials)
├── tests/
│   ├── unit/
│   │   ├── test_classifiers/
│   │   ├── test_scrapers/
│   │   ├── test_tickers/
│   │   └── test_pipeline/
│   └── integration/
│       ├── test_pipeline_e2e.py
│       └── test_storage.py
├── Dockerfile
├── pyproject.toml
└── README.md

docker-compose.yml               # Root-level; includes worker, postgres, redis services
```

**Structure Decision**: Standalone `worker/` directory. Each concern (scraping, classification, storage) is an isolated subpackage with a Protocol-based interface at `base.py`. New scrapers or classifiers are added by implementing the Protocol — no changes to pipeline core. The `docker-compose.yml` lives at project root to be shared with future services (API, frontend).

---

## Work Package Outline

*Decomposed by the `/spec-kitty.tasks` command. Listed here for orientation.*

| WP | Name | Deliverable |
|----|------|-------------|
| WP01 | Project scaffold & CI | Docker Compose, pyproject.toml, CI pipeline, health check |
| WP02 | Scraper layer | Reddit `.json` scraper + PRAW OAuth fallback + User-Agent rotation |
| WP03 | Ticker extraction & disambiguation | Extractor + disambiguator + false-positive list |
| WP04 | Classifier interface + VADER | Protocol definition + VADER implementation |
| WP05 | Storage layer | PostgreSQL schema + SQLAlchemy models + CRUD |
| WP06 | Pipeline orchestrator | Scheduler + runner + sequential queue + cycle logging |
| WP07 | Alerting & observability | Sentry integration + structured logging |
| WP08 | Integration tests & hardening | E2E tests, mock Reddit responses, 90% coverage gate |

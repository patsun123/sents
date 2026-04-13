# SentiX

SentiX is currently being repurposed into a Reddit-driven sentiment tracker for
the Epic Games Store.

The current implementation focus is collecting Epic Games Store discussion from
gaming-related Reddit communities, classifying each relevant mention as
positive or negative, and storing those raw signals in PostgreSQL for later
analysis and visualization.

## Current Focus

- Scrapes Reddit on a schedule from Epic-relevant gaming communities
- Detects Epic Games Store discussion with keyword and context rules
- Classifies sentiment with a pluggable classifier interface
- Stores privacy-safe raw signals only
- Exposes Epic-specific JSON endpoints for overview, history, communities, and recent signals

## Core Principles

- Signal-first storage: store atomic signals, not precomputed scores
- Zero PII: no usernames, comment IDs, post IDs, or comment bodies are persisted
- Resilient ingestion: primary `.json` scraping lane with OAuth fallback
- Source isolation: one failing community should not kill the whole cycle

## Repo Layout

```text
api/          FastAPI dashboard + JSON API
worker/       Reddit ingestion worker, migrations, tests
kitty-specs/  Feature spec, plan, contracts, and task breakdown
```

## Architecture

### Worker

The worker is the main engine of the project.

On startup it:

1. Loads environment-based settings
2. Configures structured logging and optional Sentry alerting
3. Runs Alembic migrations
4. Seeds default subreddits if needed
5. Starts an APScheduler loop

On each cycle it:

1. Loads enabled subreddits from PostgreSQL
2. Computes a `since` cutoff from the last successful run
3. Scrapes Reddit comments/posts
4. Matches Epic Games Store-relevant text
5. Classifies comment sentiment
6. Bulk inserts raw sentiment signals
7. Records run metadata and health state

### API

The API serves JSON endpoints backed by PostgreSQL. The new Epic-focused
surface includes:

- `/api/epic/overview`
- `/api/epic/sentiment-history`
- `/api/epic/communities`
- `/api/epic/recent-signals`

## Data Model

The worker stores raw signals shaped like:

```text
(ticker_symbol, sentiment_polarity, upvote_weight, collected_at, source_subreddit)
```

It also stores collection run metadata such as cycle status, comments processed,
sources attempted/succeeded, and error summaries.

For the Epic-only slice, `ticker_symbol` is currently used as a synthetic entity
key with the value `EPIC_GAMES_STORE`.

Signals also carry `source_content_type` so posts and comments can be weighted
differently during Epic-specific aggregation.

The project intentionally does not persist:

- Reddit usernames
- Reddit comment IDs
- Reddit post IDs
- raw comment text

## Quick Start

### Prerequisites

- Docker
- Docker Compose

### Start The Stack

From the repo root:

```bash
docker compose up --build
```

This starts:

- `api` on `http://localhost:8000`
- `worker`
- `postgres`
- `redis`

### Optional Reddit OAuth Fallback

The primary scraper uses Reddit's public `.json` endpoint and works without
credentials. If you want the OAuth fallback lane available, set these env vars
before starting the stack:

```bash
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USERNAME=...
export REDDIT_PASSWORD=...
```

### Useful Environment Variables

The worker service supports:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://sentix:sentix@postgres:5432/sentix` | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `CLASSIFIER_BACKEND` | `vader` | Sentiment backend |
| `CYCLE_INTERVAL_MINUTES` | `15` | Collection interval |
| `ALERT_THRESHOLD` | `3` | Consecutive failures before alerting |
| `SENTRY_DSN` | `""` | Optional Sentry DSN |
| `LOG_LEVEL` | `INFO` | Worker log level |
| `VADER_NEUTRAL_THRESHOLD` | `0.05` | Neutral-zone boundary |

The compose file already wires sensible defaults for local development.

## Local Development

### Worker Tests

To work on the worker outside Docker:

```bash
cd worker
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run only unit tests:

```bash
pytest tests/unit/
```

Run integration tests:

```bash
pytest tests/integration/
```

Integration tests expect a PostgreSQL database, using
`sentix_test` by default.

### API Development

The API is a small FastAPI app in `api/`. In Docker it runs with:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Operating The Pipeline

### Add A Community

Add a source without restarting the worker:

```sql
INSERT INTO data_sources (subreddit_name) VALUES ('options');
```

### Disable A Community

```sql
UPDATE data_sources
SET enabled = false, disabled_at = NOW()
WHERE subreddit_name = 'options';
```

Changes are picked up on the next collection cycle.

## Key Design Notes

### Epic Relevance Matching

Epic Games Store sentiment uses keyword and context matching instead of ticker
extraction. Strong phrases like `Epic Games Store`, `Epic launcher`, and `EGS`
match directly. Generic uses of the word `epic` are ignored unless store
context such as `exclusive`, `free games`, `coupon`, or `launcher` is present.

### Epic Scoring

Epic endpoints now use a weighted aggregate instead of the old linear
`polarity * (upvotes + 1)` stock-style score.

The new weighting combines:

- sentiment polarity (`+1` or `-1`)
- log-scaled engagement via `ln(upvotes + 2)` to reduce viral outlier dominance
- content type weighting, with posts weighted above comments
- community weighting, with focused Epic/deal communities weighted above broader
  gaming communities and adversarial communities weighted a bit lower

### Dual-Lane Scraping

- Primary lane: Reddit public `.json` endpoint
- Fallback lane: PRAW OAuth after repeated rate limiting

### Sequential Execution

APScheduler uses a single-instance schedule, and the worker also has an
in-process queue to prevent overlapping cycles.

### Privacy Guardrails

The codebase includes both unit and integration tests that explicitly check for
PII leakage in schema definitions and stored data.

## Where To Read Next

- [worker/README.md](worker/README.md) for worker-specific setup and architecture
- `api/src/main.py` for API routes
- `worker/src/main.py` and `worker/src/pipeline/runner.py` for runtime flow
- `worker/src/topics/epic_games_store.py` for Epic relevance rules

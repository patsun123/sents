# SSE Worker

Sentiment pipeline worker for the Sentiment Stock Exchange.

Scrapes Reddit comments every 15 minutes, extracts ticker mentions, classifies
sentiment via VADER (or FinBERT), and stores raw signals to PostgreSQL.
No PII is ever stored at any stage.

## Setup

1. Copy `.env.example` to `.env` and fill in credentials:
   ```bash
   cp .env.example .env
   ```
2. (Optional) Register a Reddit app at https://www.reddit.com/prefs/apps
   to enable the PRAW OAuth fallback lane. Required fields:
   - `REDDIT_CLIENT_ID`
   - `REDDIT_CLIENT_SECRET`
   - `REDDIT_USERNAME`
   - `REDDIT_PASSWORD`
3. Start all services:
   ```bash
   docker compose up --build
   ```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://sse:sse@postgres:5432/sse` | PostgreSQL connection string |
| `REDIS_URL` | Yes | `redis://redis:6379/0` | Redis connection string |
| `REDDIT_CLIENT_ID` | No | `""` | PRAW OAuth client ID (fallback lane only) |
| `REDDIT_CLIENT_SECRET` | No | `""` | PRAW OAuth client secret |
| `REDDIT_USERNAME` | No | `""` | Reddit account username for PRAW |
| `REDDIT_PASSWORD` | No | `""` | Reddit account password for PRAW |
| `CLASSIFIER_BACKEND` | No | `vader` | Sentiment classifier: `"vader"` or `"finbert"` |
| `CYCLE_INTERVAL_MINUTES` | No | `15` | How often to run a collection cycle (minutes) |
| `ALERT_THRESHOLD` | No | `3` | Consecutive failures before Sentry alert fires |
| `SENTRY_DSN` | No | `""` | Sentry error tracking DSN |
| `LOG_LEVEL` | No | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `VADER_NEUTRAL_THRESHOLD` | No | `0.05` | VADER compound score neutral zone boundary |

## Running Tests

Start the required services first, then run the test suite:

```bash
# Start postgres + redis
docker compose up postgres redis -d

# Install dev dependencies
cd worker
pip install -e ".[dev]"

# Run all tests (unit + integration) with coverage report
pytest

# Unit tests only (no DB required)
pytest tests/unit/

# Integration tests only (requires running postgres)
pytest tests/integration/

# Coverage report with HTML output
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

## Adding a Subreddit

Add a new subreddit as a data source at runtime — no restart needed:

```sql
INSERT INTO data_sources (subreddit_name) VALUES ('options');
```

The change takes effect on the **next collection cycle** (within 15 minutes by default).

To disable a subreddit without deleting it:

```sql
UPDATE data_sources
SET enabled = false, disabled_at = NOW()
WHERE subreddit_name = 'options';
```

## Refreshing the Ticker Universe

The ticker universe is a flat text file of valid NYSE/NASDAQ symbols used to
disambiguate bare ALL-CAPS mentions (e.g. `TSLA`) from common English words:

```bash
# Refresh from SEC EDGAR (requires internet access)
python scripts/refresh_ticker_universe.py

# Commit the updated file
git add worker/src/tickers/data/ticker_universe.txt
git commit -m "chore: refresh ticker universe"
```

The file is hot-reloadable at runtime via `TickerDisambiguator.reload()`.

## Architecture

```
pipeline/scheduler.py   → APScheduler fires every CYCLE_INTERVAL_MINUTES
pipeline/queue.py       → Serialises concurrent triggers (one queued, rest dropped)
pipeline/runner.py      → Orchestrates one complete collection cycle

scrapers/
  json_endpoint.py      → Primary lane: Reddit public .json endpoint
  praw_oauth.py         → Fallback lane: PRAW OAuth (activates after 3 rate-limits)

classifiers/
  vader.py              → Default: VADER rule-based classifier
  (finbert.py)          → Optional: FinBERT transformer (requires torch)

tickers/
  extractor.py          → Regex extraction of $TICKER and BARE_CAPS mentions
  disambiguator.py      → Validates against blocklist + NYSE/NASDAQ universe

storage/
  models.py             → SQLAlchemy ORM: DataSource, CollectionRun, SentimentSignal
  runs.py               → RunStore: create/update collection run records
  signals.py            → SignalStore: bulk insert + time-window queries
  sources.py            → SourceStore: get active subreddits

alerting/
  threshold.py          → AlertThresholdTracker: consecutive-failure Sentry alerts
```

### Signal-First Storage

Signals are stored as atomic `(ticker, polarity, upvote_weight, timestamp)` tuples.
No pre-computed scores, no comment text, no PII at any stage. Scoring algorithms
run against stored signals at query time.

### Dual-Lane Scraping

Primary lane (JSON endpoint) requires no credentials. After 3 consecutive
rate-limit errors, the pipeline switches to the PRAW OAuth fallback lane.
The counter resets on the next successful source.

### Source Isolation

A permanently unavailable subreddit (503/404) does not abort the cycle for other
subreddits. The run is marked `partial` if at least one source succeeds.

## Full spec

See `kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/` for the
complete feature specification, data model, and API contracts.

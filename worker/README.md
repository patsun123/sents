# SSE Worker

Sentiment pipeline worker for the Sentiment Stock Exchange.

Scrapes Reddit comments, extracts ticker mentions, classifies sentiment,
and stores raw signals to PostgreSQL every 15 minutes.

## Quick Start

```bash
cp .env.example .env    # fill in credentials
docker compose up --build
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| DATABASE_URL | Yes | postgresql+asyncpg://sse:sse@postgres:5432/sse | PostgreSQL connection |
| REDIS_URL | Yes | redis://redis:6379/0 | Redis connection |
| REDDIT_CLIENT_ID | No | "" | PRAW OAuth client ID (fallback lane) |
| REDDIT_CLIENT_SECRET | No | "" | PRAW OAuth client secret |
| REDDIT_USERNAME | No | "" | Reddit account username for PRAW |
| REDDIT_PASSWORD | No | "" | Reddit account password for PRAW |
| CLASSIFIER_BACKEND | No | vader | Sentiment classifier: "vader" or "finbert" |
| CYCLE_INTERVAL_MINUTES | No | 15 | How often to scrape (minutes) |
| ALERT_THRESHOLD | No | 3 | Consecutive failures before Sentry alert |
| SENTRY_DSN | No | "" | Sentry error tracking DSN |
| LOG_LEVEL | No | INFO | Log level: DEBUG, INFO, WARNING, ERROR |

## Running Tests

```bash
# Start postgres + redis first
docker compose up postgres redis -d

cd worker
pip install -e ".[dev]"
pytest
```

## Adding a Subreddit

```sql
INSERT INTO data_sources (subreddit_name) VALUES ('options');
```

Takes effect on the next collection cycle — no restart needed.

## Architecture

See `kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/` for full spec, plan, and data model.

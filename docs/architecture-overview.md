# Architecture Overview

## System Diagram

```
                        Reddit API
                            |
                            v
                    +---------------+
                    |    Scraper    |  :8001
                    +---------------+
                            |
              writes to reddit_raw table
                            |
            sse:scraper:run_complete (Redis pub/sub)
                            |
                            v
                    +---------------+
                    |   Processor   |  :8002
                    +---------------+
                            |
              writes to comment_sentiment +
              ticker_sentiment_snapshot tables
                            |
            sse:sentiment:run_complete (Redis pub/sub)
                            |
                            v
                    +---------------+
                    | Pricing Engine|  :8003
                    +---------------+
                            |
              fetches real prices (yfinance/Finnhub)
              writes to real_prices + sentiment_prices
                            |
            sse:pricing:run_complete (Redis pub/sub)
                            |
                            v
                    +---------------+
                    |  Backend API  |  :8000
                    +---------------+
                            |
                      SSE streams
                            |
                            v
                    +---------------+
                    |   Frontend    |  :3000
                    +---------------+

    All services connect to:
    +------------+          +----------+
    | PostgreSQL | <------> |  Redis   |
    | TimescaleDB|          |  :6379   |
    |   :5432    |          +----------+
    +------------+
```

## Service Descriptions

**Scraper** -- Periodically fetches new posts from Reddit subreddits (wallstreetbets, stocks, investing, stockmarket, options) using the public JSON API (`/r/{subreddit}/new.json`). Matches posts to tracked tickers and stores them in the `reddit_raw` table. Runs on a configurable schedule and publishes `sse:scraper:run_complete` to Redis when finished.

**Processor** -- Listens for `sse:scraper:run_complete` events. Reads unprocessed posts from `reddit_raw`, runs sentiment analysis (VADER by default, FinBERT optional), and writes per-post scores to `comment_sentiment`. Aggregates results into `ticker_sentiment_snapshot` for each ticker window. Publishes `sse:sentiment:run_complete` when done.

**Pricing Engine** -- Listens for `sse:sentiment:run_complete` events and also polls on a configurable interval. Fetches real market prices from yfinance (dev) or Finnhub (prod), then calculates sentiment-adjusted prices using the pricing formula. Writes to `real_prices` and `sentiment_prices` tables. Publishes `sse:pricing:run_complete` when done.

**Backend API** -- A FastAPI application that serves REST endpoints and SSE (Server-Sent Events) streams. Subscribes to `sse:pricing:run_complete` and pushes real-time updates to connected clients. Provides market overview, ticker history with scenario comparison, and pricing configuration endpoints. Uses asyncpg for database access and Redis for caching and pub/sub.

**Frontend** -- A React 18 application built with Vite and TypeScript, using TanStack Query for data fetching. Displays ticker prices, sentiment charts, and scenario comparisons. Served via nginx in production. Connects to the backend via REST and SSE for live updates.

## Data Flow

1. **Reddit API** -- Scraper fetches recent posts from 5 subreddits
2. **Scraper** -- Matches ticker symbols in post titles/content, deduplicates, and bulk-inserts into `reddit_raw`
3. **Redis pub/sub** -- Scraper publishes `sse:scraper:run_complete`
4. **Processor** -- Reads new `reddit_raw` rows, runs sentiment analysis, writes scores to `comment_sentiment`
5. **Processor** -- Aggregates per-ticker sentiment into `ticker_sentiment_snapshot`
6. **Redis pub/sub** -- Processor publishes `sse:sentiment:run_complete`
7. **Pricing Engine** -- Reads latest snapshots and fetches real prices from market data provider
8. **Pricing Engine** -- Calculates sentiment-adjusted prices, writes to `sentiment_prices`
9. **Redis pub/sub** -- Pricing engine publishes `sse:pricing:run_complete`
10. **Backend API** -- Receives pub/sub event, pushes update via SSE to connected frontends
11. **Frontend** -- Renders updated prices and charts in real time

## Redis Pub/Sub Channels

| Channel | Publisher | Subscriber | Purpose |
|---------|-----------|------------|---------|
| `sse:scraper:run_complete` | Scraper | Processor | Triggers sentiment analysis |
| `sse:sentiment:run_complete` | Processor | Pricing Engine | Triggers price calculation |
| `sse:pricing:run_complete` | Pricing Engine | Backend API | Triggers SSE push to clients |

**Staleness keys** (written by services, read by health/market endpoints):
- `sse:staleness:last_scrape` -- Timestamp of last successful scrape run
- `sse:staleness:last_sentiment_calc` -- Timestamp of last sentiment calculation

## Database Tables

| Table | Description |
|-------|-------------|
| `tickers` | Tracked stock symbols (TSLA, NVDA, GME, PLTR, SOFI, RIVN) with active flag |
| `reddit_raw` | Raw Reddit posts with ticker mention, score, upvote ratio, content. UNIQUE on (reddit_id, ticker_mentioned) |
| `comment_sentiment` | Per-post sentiment scores (compound, positive, negative, neutral) by analysis backend. UNIQUE on (reddit_comment_id, backend) |
| `ticker_sentiment_snapshot` | Aggregated sentiment per ticker per time window: avg compound score, weighted mention count, avg upvote score |
| `real_prices` | Market prices from yfinance/Finnhub. TimescaleDB hypertable partitioned by day |
| `sentiment_prices` | Calculated sentiment-adjusted prices with delta from real price. TimescaleDB hypertable partitioned by day |
| `pricing_parameters` | Global default pricing formula parameters (sensitivity, max_delta_pct, weights) |
| `pricing_configurations` | Named formula presets (balanced, upvote-heavy, volume-heavy) with slug and JSONB params for scenario comparison |

A continuous aggregate `sentiment_prices_1h` provides hourly bucketed sentiment prices for efficient historical queries.

## Key Formula

The sentiment-adjusted price is calculated as:

```
sentiment_price = real_price + GREATEST(LEAST(raw_delta, max_delta), -max_delta)
```

Where:
```
raw_delta = avg_sentiment * ln(1 + mention_count) * volume_weight_multiplier * upvote_weight_multiplier * sensitivity
max_delta = real_price * max_delta_pct
```

- `avg_sentiment` -- Average compound sentiment score for the ticker (-1 to +1)
- `mention_count` -- Weighted mention count from the snapshot
- `volume_weight_multiplier` -- Amplifies the effect of mention volume (default 1.0)
- `upvote_weight_multiplier` -- Amplifies the effect of Reddit karma (default 1.0)
- `sensitivity` -- Overall scaling factor (default 1.0)
- `max_delta_pct` -- Maximum price deviation as a fraction of real price (default 0.10 = 10%)

The `GREATEST/LEAST` clamp ensures the sentiment delta never exceeds the configured maximum percentage of the real price in either direction.

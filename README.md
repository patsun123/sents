# Sentiment Stock Exchange (SSE)

A real-time dashboard that converts Reddit sentiment into synthetic stock prices — watch meme stock communities move a synthetic market live.

## How it works

```
Reddit (WSB, stocks, investing)
        │
        ▼
   [scraper]  ─── httpx ──► reddit_raw (PostgreSQL)
        │
        ▼  Redis pub/sub: sse:scraper:run_complete
   [processor] ─── VADER / TextBlob / FinBERT ──► comment_sentiment + ticker_sentiment_snapshot
        │
        ▼  Redis pub/sub: sse:sentiment:run_complete
[pricing_engine] ─── formula ──► sentiment_prices (TimescaleDB hypertable)
        │                          └── also writes real prices from yfinance
        ▼  Redis pub/sub: sse:pricing:run_complete
   [backend] ─── SSE ──► [frontend]  ─── TradingView charts
```

## Quick start (development)

### Prerequisites
- Docker Desktop
- `make` (GNU make)
- `cp .env.example .env` and fill in real values

### Start everything
```bash
make up         # docker compose up (builds and starts all services)
make migrate    # runs alembic upgrade head
make db-users   # creates PostgreSQL service users
```

Access:
- Frontend: http://localhost:5173
- API docs: http://localhost:8000/api/docs
- Health: http://localhost:8000/api/v1/health

### Development shortcuts
```bash
make logs-scraper       # tail scraper logs
make logs-processor     # tail processor logs
make shell-backend      # bash into the API container
make migrate-down       # roll back last migration
make test               # run pytest (unit tests only)
make format             # ruff format + ruff check --fix
```

## Services

| Service | Port (dev) | Description |
|---|---|---|
| `scraper` | — | Polls Reddit every 5 min, stores raw posts |
| `processor` | — | Runs VADER/TextBlob/FinBERT, aggregates snapshots |
| `pricing_engine` | 8082 | Computes sentiment prices, fetches real prices |
| `backend` (API) | 8000 | FastAPI — REST + SSE endpoints |
| `frontend` | 5173 | React/Vite/TypeScript dashboard |
| `postgres` | 5432 | TimescaleDB (PostgreSQL 15) |
| `redis` | 6379 | Pub/sub + cache |
| `nginx` | 80/443 | Reverse proxy (prod only) |
| `uptime-kuma` | 3001 | Service health monitoring |

## Architecture decisions

See [plans/decisions.md](plans/decisions.md) for rationale behind key choices.

Notable:
- **asyncpg** over SQLAlchemy — direct async queries for TimescaleDB-specific SQL
- **Pub/sub decoupling** — services communicate only via Redis channels, never direct calls
- **SSE not WebSockets** — simpler, HTTP-native, works through nginx without config
- **Non-root containers** — all services run as UID 1001
- **TimescaleDB** — hypertables + continuous aggregates for time-series price data
- **Scenario comparison** — named pricing configs (balanced/upvote-heavy/volume-heavy) let you overlay what-if prices without re-running NLP

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Pipeline behaviour (weights, decay, etc.) is in `config.yaml`:
```bash
cp config.example.yaml config.yaml
```

## Database

Migrations live in `database/migrations/versions/`. To create a new migration:
```bash
cd database
alembic revision -m "your description"
alembic upgrade head
```

To see current state:
```bash
alembic current
alembic history
```

## Pricing formula

```
sentiment_price(t) = real_price(t) + delta(t)

delta(t) = clamp(
    (score_t - score_t-1) * volume_weight * upvote_mult * sensitivity,
    -max_delta_pct * real_price,
    +max_delta_pct * real_price
)

volume_weight = log(1 + mention_count) * volume_weight_multiplier  # default: log
```

**Scenario comparison** re-applies this formula with different parameter sets against stored `ticker_sentiment_snapshot` data — no re-scraping needed.

## Testing

```bash
# Unit tests (no external deps)
make test

# With integration tests (requires running DB + Redis)
RUN_INTEGRATION_TESTS=true pytest backend/tests/ pricing_engine/tests/

# Load test (50 users, 60s)
make load-test
```

## Production deployment

1. Point a domain at your server, fill in `DOMAIN=` in `.env`
2. `make up-prod` — starts nginx + certbot for TLS
3. Certbot auto-renews via the `certbot` service
4. Monitor via Uptime Kuma at `:3001`

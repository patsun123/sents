# Local Development Setup

## Prerequisites

- **Docker** and **Docker Compose** (v2+ recommended)
- **Node.js 20+** (only needed if running the frontend outside Docker)
- **Python 3.11+** (only needed if running services outside Docker)
- **uv** (optional but recommended for faster Python dependency management)
- **Git**

## Quick Start

1. Clone the repository and navigate to the project root:

```bash
git clone <repo-url> sse_io
cd sse_io
```

2. Create your environment file:

```bash
cp .env.example .env
```

3. Start all services:

```bash
docker compose up --build
```

The first run will take several minutes to build all images. Subsequent starts are much faster.

4. Access the services:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| Uptime Kuma | http://localhost:3001 |

Note: In local dev, the nginx reverse proxy and certbot are disabled (docker-compose.override.yml sets their replicas to 0). Services are accessed directly on their dev ports.

## Environment Variables

Key variables in `.env` (see `.env.example` for the full reference):

| Variable | Description |
|----------|-------------|
| `POSTGRES_DB` | Database name (default: `sse`) |
| `POSTGRES_USER` | Admin DB user (default: `sse_admin`) |
| `POSTGRES_PASSWORD` | Admin DB password -- change from default |
| `POSTGRES_URL_API` | Connection string for the backend API (uses `sse_api` role) |
| `POSTGRES_URL_SCRAPER` | Connection string for the scraper (uses `sse_scraper` role) |
| `POSTGRES_URL_PROCESSOR` | Connection string for the processor (uses `sse_processor` role) |
| `POSTGRES_URL_PRICING` | Connection string for the pricing engine (uses `sse_pricing` role) |
| `REDIS_PASSWORD` | Redis password -- used by all services |
| `REDIS_URL` | Full Redis connection URL including password |
| `MARKET_DATA_PROVIDER` | `yfinance` (free, for dev) or `finnhub` (requires API key) |
| `FINNHUB_API_KEY` | Required only when `MARKET_DATA_PROVIDER=finnhub` |
| `POSTS_PER_TICKER` | Number of Reddit posts to fetch per subreddit per run (default: 25) |
| `API_CORS_ORIGINS` | Comma-separated allowed CORS origins |
| `VITE_API_BASE_URL` | API base URL injected into the React bundle at build time |
| `LOG_LEVEL` | Logging level for all Python services (default: `INFO`) |

All `POSTGRES_URL_*` variables must use the `postgresql://` scheme. Do not use `postgresql+asyncpg://` -- that format is for SQLAlchemy only and will cause asyncpg to fail.

## Common Commands

**Rebuild all images:**
```bash
docker compose up --build
```

**Full reset (wipes database and all volumes):**
```bash
docker compose down -v && docker compose up --build
```
This removes all Docker volumes, so `init.sql` re-runs on the fresh PostgreSQL data directory, recreating all tables and roles.

**Rebuild a single service:**
```bash
docker compose up --build scraper
```

**View logs for a specific service:**
```bash
docker compose logs -f scraper
docker compose logs --tail=100 processor
```

**Run the frontend dev server standalone (with hot reload):**
```bash
cd frontend
npm install
npm run dev
```
This starts Vite on port 5173. Make sure `http://localhost:5173` is in `API_CORS_ORIGINS` in your `.env`.

**Check service status:**
```bash
docker compose ps
```

## Troubleshooting

**asyncpg connection errors:**
Ensure all `POSTGRES_URL_*` values in `.env` use the `postgresql://` scheme, not `postgresql+asyncpg://`. The latter is a SQLAlchemy convention and will cause asyncpg to reject the DSN.

**`npm run` fails in PowerShell:**
PowerShell's execution policy can block npm scripts. Use bash, cmd, or Git Bash instead. Alternatively, run the frontend inside Docker where this is not an issue.

**First run is very slow:**
Docker needs to build all images from scratch, download base images, and install dependencies. The processor service also downloads the FinBERT model (~1.4 GB) on its first startup. The `huggingface_cache` volume persists the model across restarts.

**Database not initializing:**
The `database/init.sql` script only runs when PostgreSQL starts with an empty data directory. If the database volume already exists from a previous run, the script is skipped. Use `docker compose down -v` to wipe volumes before rebuilding.

**Services fail to connect to postgres or redis:**
Check that both postgres and redis containers are healthy with `docker compose ps`. Both have health checks that must pass before dependent services start. If they are restarting, check their logs for errors.

**sse_common import errors:**
The `sse_common` package is a local shared library installed inside each container during the Docker build. If you see import errors, rebuild the affected service image with `docker compose up --build <service>`.

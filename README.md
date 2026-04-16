# SentiX

SentiX is a Dockerized Reddit sentiment tracker currently focused on the
Epic Games Store. It scrapes selected gaming subreddits on a schedule,
classifies Epic-related posts and comments as positive or negative, stores raw
signals in PostgreSQL, and serves a live dashboard at `http://localhost:8000`.

## What You Get

- FastAPI dashboard and JSON API
- Reddit worker with public `.json` scraping and thread expansion
- PostgreSQL for raw signal storage
- Redis for API caching
- Docker Compose setup that boots the full stack locally

## Repo Layout

```text
api/          FastAPI dashboard + JSON API
worker/       Reddit ingestion worker, migrations, tests
kitty-specs/  Feature spec, plan, contracts, and task breakdown
```

## Prerequisites

- Git
- Docker Desktop or Docker Engine with Compose support

## Pull And Run

### 1. Clone the repo

```bash
git clone <YOUR-REPO-URL>
cd sse_io
```

### 2. Create a local env file

This is optional for a basic local run, but recommended so your settings are
explicit.

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

### 3. Start the stack

```bash
docker compose up --build
```

Or detached:

```bash
docker compose up -d --build
```

### 4. Open the app

- Dashboard: `http://localhost:8000`
- API overview: `http://localhost:8000/api/epic/overview`

The first startup will:

1. Build the API and worker images
2. Start PostgreSQL and Redis
3. Run database migrations
4. Seed default subreddits
5. Start the worker scheduler

## Default Local Behavior

Out of the box, the stack is ready to run locally with no extra credentials.

- API port: `8000`
- Worker schedule: every `15` minutes
- Default classifier: `epic_rules`
- Reddit public `.json` scraping: enabled
- Reddit OAuth fallback: optional

### Default Communities

The worker seeds and scans these communities by default:

- `EpicGamesPC`
- `pcgaming`
- `pcmasterrace`
- `Steam`
- `GamingLeaksAndRumours`
- `truegaming`
- `patientgamers`
- `GameDeals`
- `FreeGameFindings`
- `ShouldIbuythisgame`
- `fuckepic`

## Environment Variables

The compose file already provides sane local defaults. Most people only need a
`.env` file if they want to override them.

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | `sentix` | PostgreSQL password. `DATABASE_URL` for api + worker is derived from this. Change for any deploy beyond local. |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `CLASSIFIER_BACKEND` | `epic_rules` | Sentiment backend |
| `CYCLE_INTERVAL_MINUTES` | `15` | Worker scan interval |
| `ALERT_THRESHOLD` | `3` | Consecutive failures before alerting |
| `SENTRY_DSN` | `""` | Optional Sentry DSN |
| `LOG_LEVEL` | `INFO` | Worker log level |
| `VADER_NEUTRAL_THRESHOLD` | `0.05` | Neutral-zone boundary for VADER only |
| `DOMAIN` | `—` | Public hostname for prod Caddy TLS (required only by `docker-compose.prod.yml`) |

## Optional Reddit OAuth Fallback

The primary scraper uses Reddit's public `.json` endpoints and works without
credentials. If you want the OAuth fallback lane available, set these in
`.env` before starting the stack:

```bash
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=...
REDDIT_PASSWORD=...
```

## Common Commands

### Start in background

```bash
docker compose up -d --build
```

### View logs

```bash
docker compose logs -f
```

Worker only:

```bash
docker compose logs -f worker
```

API only:

```bash
docker compose logs -f api
```

### Stop the stack

```bash
docker compose down
```

### Stop and remove volumes

This wipes local Postgres and Redis data.

```bash
docker compose down -v
```

## How The Pipeline Works

### Worker

On startup the worker:

1. Loads settings from environment variables
2. Configures structured logging and optional Sentry
3. Runs Alembic migrations
4. Seeds default data sources
5. Initializes the configured classifier
6. Starts the scheduler

On each cycle it:

1. Loads enabled communities from PostgreSQL
2. Scrapes subreddit listings from Reddit
3. Expands selected threads via thread `.json`
4. Detects Epic Games Store discussion
5. Classifies polarity
6. Stores privacy-safe raw signals
7. Records run health and scrape metadata

### API

The API serves the dashboard plus Epic-specific endpoints:

- `/api/epic/overview`
- `/api/epic/sentiment-history`
- `/api/epic/communities`
- `/api/epic/recent-signals`

## Data And Privacy Model

The worker stores raw signals shaped like:

```text
(ticker_symbol, sentiment_polarity, upvote_weight, reply_count, collected_at, source_subreddit)
```

It also stores run metadata such as cycle status, comments processed, sources
attempted, sources succeeded, and error summaries.

The current Epic-specific slice uses `EGS_STORE` as a synthetic entity key.

The project intentionally does not persist:

- Reddit usernames
- Reddit comment IDs
- Reddit post IDs
- raw post/comment text

## Local Development

### Worker

```bash
cd worker
pip install -e ".[dev]"
pytest
```

### API

In Docker, the API runs with:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Deployment

Single-host production deploy (Digital Ocean Droplet or any Ubuntu box with
Docker). TLS is terminated by Caddy using auto-provisioned Let's Encrypt
certificates.

### One-time server setup

```bash
# SSH to droplet as a non-root user (e.g. deploy)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out/in after this
git clone https://github.com/patsun123/sents.git && cd sents
cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD and DOMAIN
```

Point a DNS A record for `$DOMAIN` at the droplet's IPv4 before the first
`up` so Caddy can complete the ACME challenge on ports 80/443.

### Start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

Visit `https://$DOMAIN`. Caddy issues a certificate on first request.

### Automated deploys (GitHub Actions)

[.github/workflows/deploy.yml](.github/workflows/deploy.yml) runs
`git reset --hard origin/main && docker compose up -d --build` over SSH on
every push to `main`. Required repo secrets:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | Droplet IPv4 or hostname |
| `DEPLOY_USER` | Unprivileged user with docker group + repo clone |
| `DEPLOY_SSH_KEY` | Private key whose public key is in `~/.ssh/authorized_keys` on the droplet |
| `DEPLOY_SSH_PORT` | Optional, defaults to 22 |

The workflow is also `workflow_dispatch`-triggerable for manual redeploys.

### Backups

Nothing automated yet. Minimum recommended first step:

```bash
docker compose exec -T postgres pg_dump -U sentix sentix | gzip > backup-$(date +%F).sql.gz
```

Ship to DO Spaces, Backblaze, or `scp` off-box on a cron.

## Where To Read Next

- [worker/README.md](worker/README.md)
- [api/src/main.py](api/src/main.py)
- [worker/src/main.py](worker/src/main.py)
- [worker/src/pipeline/runner.py](worker/src/pipeline/runner.py)
- [worker/src/topics/epic_games_store.py](worker/src/topics/epic_games_store.py)

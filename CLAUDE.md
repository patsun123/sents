# SSE Project — Claude Code Context

## Running the Stack
- `docker compose up --build` — first run rebuilds all images
- `docker compose down -v && docker compose up --build` — full reset (wipes DB volumes, reruns init.sql)
- DB schema + users init automatically via `database/init.sql` mounted at `/docker-entrypoint-initdb.d/`
- Dev ports: frontend :3000, api :8000, postgres :5432, redis :6379
- nginx reverse proxy and certbot are disabled in dev (docker-compose.override.yml sets replicas: 0)

## Known Gotchas
- asyncpg requires `postgresql://` DSN — NOT `postgresql+asyncpg://` (that's SQLAlchemy-only)
- All Dockerfiles use repo root as build context; service paths are prefixed (e.g. `COPY backend/app/ app/`)
- `sse-common` is a local package — installed via `COPY sse_common/ /sse_common/` + `uv pip install /sse_common` before the service package
- pyproject.toml `[prod]` extras don't exist — use `uv pip install -e "."` not `.[prod]`
- torch/transformers (FinBERT) are in `[finbert]` optional extra — not installed by default (too large for dev)
- Frontend nginx runs as non-root; `/var/cache/nginx/*` dirs must be pre-created and chowned in Dockerfile
- `npm run` fails in PowerShell (execution policy) — use bash/cmd or the Bash tool directly

## Testing Reddit Scraping
- `cd scraper && python -c "import asyncio, sys; sys.path.insert(0, 'src'); from scraper.reddit.client import RedditClient; ..."` — no DB/Redis needed
- Scraper uses `/r/{subreddit}/new.json` (not search API) — 5 requests total regardless of ticker count
- `t=week` returns more posts than `t=day` for the search endpoint (kept as week)

## Service Architecture Reminders
- `pricing_engine/main.py` was a stub — now implemented; listens on `sse:sentiment:run_complete` + polls on interval
- `RedditClient.fetch_new_posts()` signature: `(tickers: list[str], posts_per_subreddit: int = 25)`
- Scheduler calls it with `posts_per_subreddit=settings.posts_per_ticker`

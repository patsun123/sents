# Security Overview

## Database Roles

Each service connects to PostgreSQL with a dedicated least-privilege role. No service has more access than it needs.

| Role | Access |
|------|--------|
| `sse_admin` | Superuser. Used for migrations and schema changes. Not used by any application service at runtime. |
| `sse_api` | SELECT only on all tables. Cannot modify data. Used by the backend API service. |
| `sse_scraper` | SELECT, INSERT, UPDATE on `reddit_raw`. SELECT on `tickers`. Used by the scraper service. |
| `sse_processor` | SELECT, INSERT on `comment_sentiment` and `ticker_sentiment_snapshot`. SELECT on `reddit_raw` and `tickers`. Used by the processor service. |
| `sse_pricing` | SELECT, INSERT on `real_prices` and `sentiment_prices`. SELECT on `tickers`, `pricing_parameters`, `pricing_configurations`, `ticker_sentiment_snapshot`. Used by the pricing engine. |

Roles are created by `database/init.sql` on first database initialization. Default passwords are placeholder values (`changeme_*`) that must be changed for any non-local deployment.

## Redis Authentication

Redis is configured with `--requirepass` in the docker-compose.yml command block. All services connect using authenticated Redis URLs in the format:

```
redis://:${REDIS_PASSWORD}@redis:6379/0
```

The password is set via the `REDIS_PASSWORD` environment variable in `.env`. Change it from the default before any non-local deployment.

## Container Hardening

All application containers (scraper, processor, pricing_engine, api, frontend) are configured with:

- **`read_only: true`** -- Container filesystems are mounted read-only. Services cannot write to their own image layers.
- **`tmpfs: /tmp`** -- A tmpfs mount provides a writable `/tmp` for temporary files without persisting to disk.
- **Non-root processes** -- Services run as UID 1001 inside the container. No service runs as root.
- **Memory limits** -- Each service has a Docker memory limit to prevent runaway consumption:
  - Scraper: 512 MB
  - Processor: 4 GB (FinBERT model requires ~1.4 GB)
  - Pricing Engine: 256 MB
  - Backend API: 512 MB

## Network Model

All services communicate over a single Docker bridge network (`sse_net`). No service port is exposed to the host except through explicitly mapped ports.

In production:
- Only **nginx** exposes ports 80 and 443 to the host
- Nginx handles TLS termination via Let's Encrypt certificates (managed by certbot)
- All inter-service traffic stays on the internal `sse_net` bridge

In local development:
- Nginx and certbot are disabled (replicas set to 0 via docker-compose.override.yml)
- Service ports (3000, 8000, 5432, 6379, 3001) are mapped directly to the host for convenience
- Uptime Kuma exposes port 3001 for its monitoring dashboard

## API Rate Limiting

The backend API uses slowapi for rate limiting:

| Endpoint Type | Limit |
|---------------|-------|
| General API endpoints | 60 requests/minute |
| SSE streaming endpoints | 10 requests/minute |

Rate limiting uses an in-memory backend, meaning limits reset when the API service restarts.

## Environment Variable Security

Sensitive values are stored in `.env` (gitignored, never committed):

- Database passwords for all roles
- Redis password
- Finnhub API key
- Reddit API credentials (optional)

The `.env.example` file contains only placeholder values and is safe to commit. All Docker services load variables via the `env_file: .env` directive.

## Known Limitations (V1)

These are accepted trade-offs for the current prototype stage:

- **No TLS between internal services** -- Inter-service communication on the Docker bridge network is unencrypted. Acceptable for a single-host deployment where the network is not shared with untrusted containers.
- **Rate limiting resets on restart** -- The slowapi in-memory backend loses all state when the API container restarts. A Redis-backed rate limiter would provide persistence.
- **No API authentication** -- All API endpoints are publicly accessible. This is intentional for the V1 public prototype. Adding JWT or API key authentication is planned for V2.
- **Default database passwords** -- The `init.sql` script uses `changeme_*` passwords. These must be replaced before any internet-facing deployment.
- **No secrets management** -- Secrets are passed as plain environment variables. A production deployment should use Docker secrets, Vault, or a similar system.
- **No audit logging** -- Database and API access is not logged for audit purposes beyond standard container logs.

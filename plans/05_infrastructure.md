# Infrastructure / DevOps — Atomic Implementation Plan

## Domain: Docker Compose, DigitalOcean, TLS, Monitoring, Backups, Security

---

### TASK-OPS01: Provision DigitalOcean Droplet
**Domain:** Infrastructure / DevOps
**Depends on:** none
**Description:** Provision a single DigitalOcean droplet (**minimum 4GB RAM**, 50GB storage) to run all services. The 4GB minimum is required because the FinBERT model (TASK-OPS32) loads ~1.4GB of model weights into RAM at startup; 2GB is insufficient. Configure SSH key access, basic firewall rules, and initial system updates.
**Acceptance criteria:**
- Droplet is **4GB RAM / 2 vCPU** or larger (e.g., DigitalOcean `s-2vcpu-4gb`)
- Droplet accessible via SSH with key-based authentication only (password auth disabled)
- System packages up to date
- Basic firewall: allow SSH (22), HTTP (80), HTTPS (443); deny all other inbound
- Hostname and timezone configured
- Droplet can be accessed and basic system info retrieved

---

### TASK-OPS02: Install Docker and Docker Compose
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS01
**Description:** Install Docker Engine and Docker Compose on the droplet, verify installations, and configure Docker daemon to start on boot.
**Acceptance criteria:**
- Docker 20.10+ installed and running
- Docker Compose 2.0+ installed
- Docker daemon starts automatically on reboot
- `docker --version` and `docker compose --version` succeed
- Current user can run docker commands without sudo (via docker group)

---

### TASK-OPS03: Document non-root Docker user strategy
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS02
**Description:** Define application-specific non-root users for each service (scraper, processor, pricing_engine, api, frontend) to be used consistently in all Dockerfiles.
**Acceptance criteria:**
- User list documented with UIDs/GIDs
- Each service has a dedicated low-privilege user
- Naming convention defined (e.g., `app_scraper`, `app_processor`)
- Users have no interactive shell access
- Referenced in all subsequent Dockerfiles

---

### TASK-OPS04: Design Docker Compose network topology
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS02
**Description:** Design the Docker Compose network topology with explicit service networks for isolation. Document which services communicate with which, DNS resolution strategy, and the external network for the Nginx reverse proxy.
**Acceptance criteria:**
- Network diagram (or ascii diagram) showing service isolation
- Internal DNS names defined (postgres, redis, api, scraper, processor, pricing_engine)
- External network for Nginx proxy defined separately
- Rationale for isolation decisions documented
- Which services share networks is explicitly decided

---

### TASK-OPS05: Create Dockerfile for Scraper service
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Production-grade Dockerfile for the Python Scraper service: non-root user, minimal base image, Playwright browser binaries installed, health check configured.
**Acceptance criteria:**
- Python 3.11+ slim base image
- Runs as non-root user (`app_scraper`)
- Playwright browsers installed
- Dependencies installed from requirements.txt
- Health check command defined
- Read-only root filesystem where feasible
- Dockerfile comments explain non-obvious steps

---

### TASK-OPS06: Create Dockerfile for Sentiment Processor service
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Production-grade Dockerfile for the Python Sentiment Processor service with CPU-bound NLP workload considerations.
**Acceptance criteria:**
- Python 3.11+ slim base image
- Runs as non-root user (`app_processor`)
- Dependencies installed from requirements.txt (includes VADER, TextBlob, transformers)
- Health check command defined
- Logging configuration for monitoring included

---

### TASK-OPS07: Create Dockerfile for Pricing Engine service
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Production-grade Dockerfile for the Python Pricing Engine service with high-precision numeric handling.
**Acceptance criteria:**
- Python 3.11+ slim base image
- Runs as non-root user (`app_pricing_engine`)
- Dependencies from requirements.txt
- Health check defined
- Logging configured for audit trails

---

### TASK-OPS08: Create Dockerfile for FastAPI API server
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Production-grade Dockerfile for the FastAPI API server with uvicorn, health endpoint, and configurable worker count.
**Acceptance criteria:**
- Python 3.11+ slim base image
- Runs as non-root user (`app_api`)
- FastAPI and uvicorn installed from requirements.txt
- Health check endpoint defined
- Worker count configurable via env var
- Structured logging configured

---

### TASK-OPS09: Create Dockerfile for Frontend (multi-stage React build)
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Multi-stage Dockerfile: Node.js build stage compiles React app, nginx:alpine runtime stage serves static files.
**Acceptance criteria:**
- Build stage uses Node.js, compiles React app with optimizations
- Runtime stage uses nginx:alpine
- Runs as nginx user (non-root)
- Static files served with cache headers
- Listens on 443, redirects 80 to 443 internally

---

### TASK-OPS10: Create Dockerfile for PostgreSQL + TimescaleDB
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Dockerfile extending official PostgreSQL 15+ with TimescaleDB extension and initialization scripts for schema and per-service DB user creation.
**Acceptance criteria:**
- Based on postgres:15-alpine with TimescaleDB installed
- Init script creates databases and DB schema
- Init script creates separate non-root DB users per service with minimal privileges
- Health check uses `pg_isready`
- Data persisted via named volume
- Documented permission matrix (which user can do what)

---

### TASK-OPS11: Create Dockerfile for Redis
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Dockerfile for Redis with non-root user, persistence enabled, and password authentication via environment variable.
**Acceptance criteria:**
- Based on redis:7-alpine
- Runs as non-root user
- Persistence enabled (AOF or RDB)
- Health check configured
- Requires auth password from env var
- Data persisted via named volume
- Pub/sub operations supported

---

### TASK-OPS12: Create Certbot container for Let's Encrypt TLS
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03
**Description:** Certbot container configuration for automatic Let's Encrypt certificate provisioning and renewal, with a reload hook to signal Nginx when certificates renew.
**Acceptance criteria:**
- Based on certbot official image
- Volume mounts for certificates and renewal hooks
- Automated renewal check runs daily
- Reload hook signals Nginx on renewal
- Certificate storage at /etc/letsencrypt (shared volume with Nginx)

---

### TASK-OPS13: Create base docker-compose.yml with all services
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS04, TASK-OPS05, TASK-OPS06, TASK-OPS07, TASK-OPS08, TASK-OPS09, TASK-OPS10, TASK-OPS11, TASK-OPS12
**Description:** The main `docker-compose.yml` declaring all **9 services** with their images, environment bindings, network memberships, named volumes, and `depends_on` conditions. Scope is limited to service declaration and wiring — read-only filesystems (TASK-OPS23), health check probes (TASK-OPS24), and restart policies (TASK-OPS25) are handled in their own tasks and referenced here only by the fields they own.

**Services (9):** Scraper, Sentiment Processor, Pricing Engine, API, Frontend/Nginx, PostgreSQL+TimescaleDB, Redis, Certbot, Uptime Kuma
**Acceptance criteria:**
- All 9 services declared with correct `image:` or `build:` references
- Resource limits defined (memory/CPU) — suggested: Processor 2GB, API 512MB, Scraper 512MB, Pricing Engine 256MB
- Named volumes declared: `postgres_data`, `redis_data`, `letsencrypt_certs`, `uptime_kuma_data`
- Networks configured per TASK-OPS04 design
- `depends_on` with `condition: service_healthy` set for critical paths (e.g., API waits on postgres and redis healthy)
- All env vars sourced from `.env` file (no hardcoded values)

---

### TASK-OPS14: Create .env.example template
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS13
**Description:** `.env.example` documenting all required environment variables across all services, with descriptions, example values, and clear distinction between required and optional vars.
**Acceptance criteria:**
- All variables documented with inline comments
- Sections: Database, Cache, API Keys, Security, Monitoring, Scraping, Sentiment
- Sensitive variables clearly marked
- Example values provided (non-functional — no real credentials)
- Notes on how to generate secrets (e.g., `openssl rand -hex 32`)
- `.env` listed in `.gitignore`

---

### TASK-OPS15: Configure PostgreSQL database users and permissions
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS10
**Description:** SQL initialization script creating all service-specific DB users with minimal privileges. Separate users for: scraper, processor, pricing_engine, api, and monitoring (read-only).
**Acceptance criteria:**
- Script creates users: `sse_scraper`, `sse_processor`, `sse_pricing`, `sse_api`, `sse_monitor`
- Each user granted only the privileges their service needs (CRUD on specific tables only)
- `sse_monitor` is read-only
- Script is idempotent (safe to re-run)
- Permission matrix documented in a comment block at top of script

---

### TASK-OPS16: Configure Nginx reverse proxy
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS09, TASK-OPS13
**Description:** Nginx configuration for TLS termination, HTTP→HTTPS redirect, API proxying to FastAPI, and static frontend file serving with cache headers and gzip.
**Acceptance criteria:**
- HTTPS on port 443 with TLS from Let's Encrypt
- HTTP port 80 redirects to HTTPS
- `/api/v1/` proxied to FastAPI backend
- Frontend static files served with appropriate cache headers
- Gzip compression enabled
- Security headers: X-Frame-Options, X-Content-Type-Options, Strict-Transport-Security
- Structured access/error logging

---

### TASK-OPS17: Configure Let's Encrypt TLS certificate provisioning
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS12, TASK-OPS16
**Description:** Set up initial Let's Encrypt certificate issuance via Certbot using HTTP-01 ACME challenge through Nginx, with auto-renewal.
**Acceptance criteria:**
- Certbot configured for the target domain
- HTTP-01 challenge method used via Nginx
- Certificate files mounted to Nginx container
- Initial certificate generation procedure documented step-by-step
- Renewal hook script reloads Nginx on certificate update
- Renewal check scheduled daily
- SSL configuration in Nginx references certificates correctly

---

### TASK-OPS18: Configure structured logging for all services
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS13
**Description:** JSON-format structured logging for all services with log rotation, timestamps, service name, and severity level on every log entry.
**Acceptance criteria:**
- All services use json-file log driver
- Log rotation: max-size 10MB, max-file 5
- Log entries include: timestamp, service_name, severity, message
- Python services use `python-json-logger` or `structlog`
- FastAPI logs include request/response details
- Log aggregation strategy documented

---

### TASK-OPS19: ~~Implement API rate limiting~~ [SUPERSEDED → TASK-BE12]
**Domain:** Infrastructure / DevOps
**Status:** SUPERSEDED — rate limiting is implemented as FastAPI middleware in TASK-BE12 (`slowapi` or `fastapi-limiter`), not as an infrastructure-layer concern. This task is retained for traceability only.
**See:** TASK-BE12 in `03_backend_api.md`

---

### TASK-OPS20: Set up Uptime Kuma monitoring
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS13
**Description:** Uptime Kuma service in Docker Compose monitoring all services, with health monitors for API, frontend, PostgreSQL, Redis, and scraper status endpoint.
**Acceptance criteria:**
- Uptime Kuma service defined in docker-compose.yml
- Web UI accessible (HTTPS)
- Monitors created for: API /health, Frontend, PostgreSQL, Redis, Scraper /health
- Check intervals configured (5 min for critical services)
- Dashboard shows: service status, last successful scrape, data freshness
- Monitor for data staleness (last scrape > 45 min ago triggers alert)

---

### TASK-OPS21: Configure Uptime Kuma notifications
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS20
**Description:** Notification channels in Uptime Kuma for service alerts via email and at least one of Discord/Slack.
**Acceptance criteria:**
- Email notification configured and tested
- Discord or Slack webhook integration configured
- Alert rules for: service down, response time high, database unreachable
- Escalation policy documented
- Test alerts successfully delivered
- On-call procedure documented

---

### TASK-OPS22: Create automated PostgreSQL backup job
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS10, TASK-OPS13
**Description:** Daily automated PostgreSQL backup using `pg_dump`, compressed, with a retention policy and external storage destination.
**Acceptance criteria:**
- Backup runs daily at configurable time (default: 02:00 UTC)
- Dumps compressed to external storage (DigitalOcean Spaces, S3, or mounted volume)
- Backup files named with timestamp (e.g., `sse-backup-2026-02-28.sql.gz`)
- Retention policy: keep last 30 backups
- Backup job logs success/failure
- Restoration procedure documented and tested
- External storage location documented

---

### TASK-OPS23: Configure read-only filesystems for services
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS05, TASK-OPS06, TASK-OPS07, TASK-OPS08, TASK-OPS09, TASK-OPS11
**Description:** Set `read_only: true` on root filesystems in docker-compose.yml for all applicable services, with explicit writable tmpfs mounts for logs, /tmp, and cache.
**Acceptance criteria:**
- `read_only: true` set on root filesystem for all Python services and Nginx
- Writable volumes/tmpfs explicitly mounted for: logs, /tmp, cache directories
- All services tested to confirm correct operation with read-only root
- Services requiring writable root documented with rationale

---

### TASK-OPS24: Implement health checks for all services
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS05–TASK-OPS11
**Description:** Health check endpoints and Docker health check probes for every service in docker-compose.yml.
**Acceptance criteria:**
- FastAPI `/health` returns 200 with service status JSON
- PostgreSQL health check uses `pg_isready`
- Redis health check uses `redis-cli ping`
- Frontend health check returns 200 from Nginx
- Scraper `/health` returns last execution timestamp and staleness status
- Processor and pricing engine health checks confirm connectivity
- Health check intervals, timeouts, and retries configured in docker-compose.yml
- Failed health checks trigger container restart (via `depends_on` conditions)

---

### TASK-OPS25: Configure restart policies for all services
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS13
**Description:** All services configured with `restart: unless-stopped` in docker-compose.yml, with documented manual override procedure for maintenance windows.
**Acceptance criteria:**
- All services set to `restart: unless-stopped`
- Rationale documented (auto-recovery from transient failures and droplet reboots)
- Manual service stop procedure documented (does not trigger restart)
- Maintenance window procedure documented
- Service inter-dependency restart order documented

---

### TASK-OPS26: Secrets management and credential rotation procedure
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS02, TASK-OPS14
**Description:** Establish .env-based secrets management with documented rotation procedures and a `.gitignore` that prevents accidental secret commits.
**Acceptance criteria:**
- `.env` and all variants listed in `.gitignore`
- Procedure for generating initial secrets documented (openssl, python secrets module)
- Secrets rotation procedure documented per credential type
- Secrets stored with restricted file permissions (0600)
- No secrets hardcoded in Dockerfiles or docker-compose.yml
- Pre-commit hook (optional) that checks for accidental secret inclusion

---

### TASK-OPS27: ~~Implement structured application logging framework~~ [SUPERSEDED → TASK-OPS34]
**Domain:** Infrastructure / DevOps
**Status:** SUPERSEDED — structured logging is implemented as part of the `sse-common` shared package in TASK-OPS34 (`sse_common.logging_config.configure_logging()`). This task is retained for traceability only.
**See:** TASK-OPS34 in this file

---

### TASK-OPS28: Create deployment runbook
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS01, TASK-OPS02, TASK-OPS13, TASK-OPS14, TASK-OPS16, TASK-OPS17, TASK-OPS20, TASK-OPS25
**Description:** Step-by-step deployment guide from a fresh DigitalOcean droplet to a fully operational system with all services running and verified.
**Acceptance criteria:**
- Pre-deployment checklist (accounts, domain, SSH key, env vars)
- Step-by-step commands with expected output for each step
- Verification procedure for each component after deployment
- Post-deployment validation tests (API calls, DB connectivity, TLS check)
- Troubleshooting section for top 5 most likely failure modes
- Rollback procedure documented
- Maintenance procedures: service restart, log cleanup, backup verification

---

### TASK-OPS29: Create monitoring and incident response runbook
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS20, TASK-OPS21, TASK-OPS18
**Description:** Document monitoring procedures, alert response steps, and troubleshooting guides for responding to common alerts.
**Acceptance criteria:**
- Alert types catalogued with severity levels
- Response procedure for each alert type
- Service restart procedures documented
- Log analysis procedure documented
- Database performance troubleshooting guide
- Disk space monitoring and cleanup procedure
- API rate limit debugging procedure
- Common issues and resolutions documented

---

### TASK-OPS30: Produce pre-launch security hardening document
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS03, TASK-OPS10, TASK-OPS15, TASK-OPS16, TASK-OPS17, TASK-OPS23, TASK-OPS26
**Description:** Create `docs/security-hardening.md` — a written sign-off document, not an implementation task. The document records the result of manually verifying each hardening measure against the deployed system before going live. Each item is either ✓ (verified) or ✗ (with a documented exception and justification).

**Document must cover:**
- Non-root users across all 9 containers
- Read-only root filesystems (TASK-OPS23)
- Network isolation — which containers cannot reach which
- TLS/HTTPS end-to-end (no cleartext in transit)
- DB least-privilege per service (TASK-OPS15)
- Rate limiting active (TASK-BE12)
- No secrets in `.env`, logs, or container image layers
- Container image vulnerability scan completed (`docker scout` or `trivy`)

**Acceptance criteria:**
- `docs/security-hardening.md` exists and is committed
- All 8 items marked ✓ or have a written exception with justification
- Document reviewed and signed off before the first production deployment

---

### TASK-OPS31: Create disaster recovery plan
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS22, TASK-OPS28
**Description:** Document disaster recovery procedures for complete droplet failure, including backup restoration and failover to a new droplet.
**Acceptance criteria:**
- RTO (Recovery Time Objective) and RPO (Recovery Point Objective) defined
- Step-by-step procedure to spin up new droplet from backup
- Backup restoration tested and documented
- DNS reconfiguration procedure documented
- Data consistency validation after restoration
- Service verification procedures post-restoration
- DR test frequency defined (quarterly recommended)

---

### TASK-OPS32: Add FinBERT memory guard to Sentiment Processor Dockerfile
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS06
**Description:** The FinBERT transformer model loads ~1.4GB of weights at startup. Without an explicit memory limit, the Processor container can silently OOM-kill the entire host. Set a hard memory limit and add a pre-start check that logs a fatal error if available RAM is below threshold.

**Changes to `docker-compose.yml` Processor service:**
```yaml
deploy:
  resources:
    limits:
      memory: 2G      # hard limit; OOM-kill before host is affected
    reservations:
      memory: 1500M   # scheduler hint
```

**Changes to `processor/entrypoint.sh` (or `__main__.py` startup):**
```python
import psutil, sys, logging
MIN_FREE_MB = 1200
free_mb = psutil.virtual_memory().available / 1024 / 1024
if free_mb < MIN_FREE_MB:
    logging.fatal("Insufficient RAM to load FinBERT (%.0f MB free, need %d MB). Aborting.", free_mb, MIN_FREE_MB)
    sys.exit(1)
```

**Acceptance criteria:**
- `deploy.resources.limits.memory: 2G` set in `docker-compose.yml` for the Processor service
- Startup check aborts with exit code 1 and a clear log message if free RAM < 1200 MB
- Unit test asserts startup check raises `SystemExit` when mocked `available` memory is below threshold
- TASK-OPS01 droplet size (4GB) verified sufficient for all 9 services concurrently

---

### TASK-OPS33: Establish shared database migration ownership
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS10, TASK-OPS15
**Description:** All DDL (schema creation, alterations, indexes) lives in `database/migrations/` and is applied by a single migration runner. No service Dockerfile or application code runs `CREATE TABLE` directly — services depend on the migration having already run.

**Directory layout:**
```
database/
  migrations/
    001_initial_schema.sql      # reddit_raw, sentiment_scores, pricing_history tables
    002_timescaledb_hypertable.sql
    003_add_content_fingerprint.sql
    ...
  scripts/
    seed_tickers.sql            # initial ticker list (TASK-BE31)
    create_users.sql            # per-service DB users (TASK-OPS15)
  docker-entrypoint-initdb.d/  # symlinks or copies for PostgreSQL auto-init
```

**Migration runner:** Flyway (Java-free via `flyway/flyway` Docker image) or plain sequential SQL via `psql` in a one-shot init container.

**Acceptance criteria:**
- `database/migrations/` directory exists with numbered SQL files
- Migration runner is declared as a `depends_on` prerequisite for all services that use the DB
- No `CREATE TABLE` statements exist outside `database/migrations/`
- `README.md` in `database/` explains how to add a new migration
- Migrations are idempotent (use `IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, etc.)

---

### TASK-OPS34: Create `sse-common` shared Python package
**Domain:** Infrastructure / DevOps
**Depends on:** none
**Description:** Create an internal Python package `sse_common` installed into all Python service images via `pip install -e packages/sse-common`. Provides shared constants, logging configuration, and Redis channel names so values are never duplicated across services.

**Package layout:**
```
packages/sse-common/
  pyproject.toml
  sse_common/
    __init__.py
    constants.py       # staleness thresholds, channel names, config defaults
    logging_config.py  # configure_logging(service_name, log_level) → structlog/json
    channels.py        # REDIS_CHANNEL_SCRAPER, PROCESSOR, PRICING constants
```

**`constants.py` (authoritative values):**
```python
STALENESS_WARNING_MINUTES = 30
STALENESS_CRITICAL_MINUTES = 60
STALENESS_UNAVAILABLE_HOURS = 4

REDIS_CHANNEL_SCRAPER_COMPLETE   = "sse:scraper:run_complete"
REDIS_CHANNEL_SENTIMENT_COMPLETE = "sse:sentiment:run_complete"
REDIS_CHANNEL_PRICING_COMPLETE   = "sse:pricing:run_complete"
```

**`logging_config.py`:**
```python
def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """Configure structlog JSON logging for the given service."""
    ...
```

**Acceptance criteria:**
- `packages/sse-common/pyproject.toml` declares package `sse-common` with no external dependencies beyond `structlog`
- All Python Dockerfiles install it with `pip install -e /app/packages/sse-common`
- `sse_common.constants.STALENESS_WARNING_MINUTES` importable from Scraper, Processor, Pricing Engine, and API
- `sse_common.logging_config.configure_logging("scraper", "INFO")` produces JSON logs
- Unit tests for `constants.py` and `configure_logging()` in the `sse-common` package itself

---

### TASK-OPS35: Create Locust load test suite
**Domain:** Infrastructure / DevOps
**Depends on:** TASK-OPS13, TASK-BE24, TASK-BE25, TASK-BE26
**Description:** Write a Locust load test suite that simulates realistic production traffic patterns against the API. Run in CI on PRs to `main` (TASK-CI04) using `docker-compose.test.yml`.

**File:** `tests/load/locustfile.py`

**Scenarios to simulate:**
| Task | Locust task | Weight |
|------|-------------|--------|
| List tickers `GET /api/v1/tickers` | `get_tickers` | 5 |
| Ticker detail `GET /api/v1/tickers/{symbol}` | `get_ticker_detail` | 3 |
| Price history `GET /api/v1/tickers/{symbol}/history?timeframe=1D` | `get_history` | 2 |
| SSE connection (hold 30s) `GET /api/v1/tickers/stream` | `stream_prices` | 1 |

**Thresholds (CI failure gates):**
- p95 response time < 500ms for REST endpoints
- p99 response time < 2000ms for SSE connection establishment
- Error rate < 1% at 50 concurrent users

**Acceptance criteria:**
- `tests/load/locustfile.py` exists with all 4 task classes above
- `Makefile` target `make load-test` runs Locust headlessly for 60s at 50 users
- CI integration test (TASK-CI04) runs `make load-test` against test compose stack
- Results written to `tests/load/results/` (gitignored)
- Thresholds enforced: Locust exits with non-zero code if p95 > 500ms or error rate > 1%

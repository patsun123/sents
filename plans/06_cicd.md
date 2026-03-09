# CI/CD Pipeline — Atomic Implementation Plan

## Domain: GitHub Actions, Pre-Commit, Docker Compose Test Stack, Deploy Automation

> This plan resolves RISK-4 from the gap analysis: the 133-task implementation plan
> had zero CI/CD coverage. All tasks are organized in dependency order.

---

### TASK-CI01: GitHub branch protection and repository settings
**Domain:** CI/CD
**Depends on:** none
**Description:** Configure GitHub repository settings:
- Protect `main` branch: require PR reviews (1 reviewer), require status checks to pass before merge, require branch to be up to date
- Required status checks: `backend-ci`, `frontend-ci`
- Disallow force push to `main`
- Delete head branches automatically on PR merge
- Enable "Squash and merge" as the preferred merge strategy
- Tag naming convention: `v{major}.{minor}.{patch}` (e.g., `v1.0.0`) triggers production deploy
**Acceptance criteria:**
- Direct push to `main` is rejected
- PR with failing `backend-ci` or `frontend-ci` cannot be merged
- Tag `v*` triggers the deploy workflow (TASK-CI08)
- Repository settings documented in `docs/contributing.md`

---

### TASK-CI02: Pre-commit hooks configuration
**Domain:** CI/CD
**Depends on:** TASK-CI01
**Description:** Create `.pre-commit-config.yaml` at repo root. Hooks run on every `git commit`:
1. **ruff** — lint and auto-fix (Python, all services: `scraper/`, `backend/`, `processor/`, `pricing/`)
2. **ruff-format** — code formatting (replaces black)
3. **mypy** — type checking (each service has its own `mypy.ini`)
4. **pytest (fast subset)** — unit tests only, tagged `@pytest.mark.fast`, timeout 30s
5. **trailing-whitespace, end-of-file-fixer, check-yaml, check-json** — general hygiene
6. **eslint** — frontend JS/TS linting (runs only on changed `frontend/` files)
7. **tsc** — TypeScript type check (only on changed `frontend/` files)
Install instructions: `pip install pre-commit && pre-commit install`
**Acceptance criteria:**
- `pre-commit run --all-files` passes on a clean repo state
- `pre-commit install` documented in `docs/development.md` (TASK-CI10)
- Hook config file committed to repo at `.pre-commit-config.yaml`
- Ruff config in `pyproject.toml` (shared) or each service's own `pyproject.toml`
- Mypy config in each service's `mypy.ini` with `strict = true`
- Pre-commit hooks complete in under 60 seconds on a typical commit

---

### TASK-CI03: Backend CI workflow — lint, type check, unit tests
**Domain:** CI/CD
**Depends on:** TASK-CI02
**Description:** Create `.github/workflows/backend-ci.yml`. Triggers on: push to any branch, PR to `main`. Matrix strategy runs each service independently:
```yaml
strategy:
  matrix:
    service: [scraper, backend, processor, pricing]
```
Steps per service:
1. `actions/checkout@v4`
2. `actions/setup-python@v5` (Python 3.11)
3. `pip install -e ".[dev]"` (install service with dev deps)
4. `ruff check .` — lint
5. `ruff format --check .` — format check
6. `mypy .` — type check
7. `pytest -m "not integration" --timeout=30 -x` — unit tests only
Cache: `pip` cache keyed on `pyproject.toml` hash per service.
**Acceptance criteria:**
- Workflow file committed at `.github/workflows/backend-ci.yml`
- All 4 services pass on a clean repo
- Workflow name `backend-ci` matches the protected branch required status check (TASK-CI01)
- Lint and test failures clearly annotate the PR with inline comments
- Workflow completes in under 5 minutes per service (parallelized via matrix)
- No secrets required — pure lint/test workflow

---

### TASK-CI04: Integration tests workflow — PR to main
**Domain:** CI/CD
**Depends on:** TASK-CI03, TASK-CI05
**Description:** Create `.github/workflows/integration-tests.yml`. Triggers on: PR to `main` only (not every push — integration tests are slower). Steps:
1. `actions/checkout@v4`
2. `docker/setup-buildx-action@v3`
3. Build test images: `docker compose -f docker-compose.yml -f docker-compose.test.yml build`
4. Start test stack: `docker compose -f docker-compose.yml -f docker-compose.test.yml up -d`
5. Wait for health checks: poll until all services report healthy (timeout 120s)
6. Run backend integration tests: `docker compose exec backend pytest -m integration --timeout=120`
7. Run processor integration tests: `docker compose exec processor pytest -m integration --timeout=120`
8. Run pricing integration tests: `docker compose exec pricing pytest -m integration --timeout=120`
9. Collect and upload test artifacts (logs, coverage report)
10. Tear down: `docker compose down -v` (remove volumes to prevent state leakage)
**Acceptance criteria:**
- Workflow skipped on pushes that don't target `main` branch
- Uses `docker-compose.test.yml` override (TASK-CI05) to inject test DB/Redis
- Test containers use `testcontainers` fixtures where possible, otherwise rely on Compose
- Marked `@pytest.mark.integration` tests in all three services run and results reported
- Workflow uploads test logs as GitHub Actions artifacts on failure
- `docker compose down -v` always runs (via `if: always()`) to prevent orphaned containers
- Workflow completes in under 15 minutes

---

### TASK-CI05: docker-compose.test.yml override file
**Domain:** CI/CD
**Depends on:** TASK-OPS08 (main docker-compose.yml)
**Description:** Create `docker-compose.test.yml` for CI-specific overrides. This file extends the main `docker-compose.yml`:
- Overrides `DATABASE_URL` to point at a separate test PostgreSQL DB (`sse_test`)
- Overrides `REDIS_URL` to point at a Redis instance with DB index 1 (separate from prod DB 0)
- Sets `RUN_INTEGRATION_TESTS=true` env var on all service containers
- Sets `LOG_LEVEL=DEBUG` to get verbose output in CI
- Disables certbot (not needed in test)
- Disables uptime-kuma (not needed in test)
- PostgreSQL: adds a healthcheck command that also creates the `sse_test` database if missing
- All services set `restart: "no"` (override default `unless-stopped`)
```yaml
# docker-compose.test.yml
version: "3.9"
services:
  postgres:
    environment:
      POSTGRES_DB: sse_test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sse && psql -U sse -c 'SELECT 1' sse_test || exit 1"]
  backend:
    environment:
      DATABASE_URL: postgresql+asyncpg://sse:sse@postgres:5432/sse_test
      RUN_INTEGRATION_TESTS: "true"
      LOG_LEVEL: DEBUG
    restart: "no"
  # ... (same pattern for scraper, processor, pricing)
  certbot:
    profiles: ["production"]  # skip certbot in test
  uptime-kuma:
    profiles: ["production"]  # skip uptime-kuma in test
```
**Acceptance criteria:**
- `docker compose -f docker-compose.yml -f docker-compose.test.yml up` starts cleanly
- Test PostgreSQL DB `sse_test` is fully separate from `sse` (no cross-contamination)
- `docker compose -f docker-compose.yml -f docker-compose.test.yml down -v` cleanly removes test data
- File documented in `docs/development.md`

---

### TASK-CI06: Frontend CI workflow — lint, type check, test, build
**Domain:** CI/CD
**Depends on:** TASK-CI01, TASK-FE01, TASK-FE25, TASK-FE26
**Description:** Create `.github/workflows/frontend-ci.yml`. Triggers on: push to any branch (path filter: `frontend/**`), PR to `main`. Steps:
1. `actions/checkout@v4`
2. `actions/setup-node@v4` (Node 20 LTS)
3. `npm ci` (uses `package-lock.json` for reproducible installs)
4. `npm run lint` — ESLint
5. `npm run typecheck` — `tsc --noEmit`
6. `npm test -- --run` — Vitest unit + RTL component tests (TASK-FE25, TASK-FE26); `--run` disables watch mode for CI
7. `npm run build` — Vite production build (verifies bundle compiles cleanly)
8. Upload build artifact (`dist/` folder) — useful for size tracking and deploy (TASK-CI08)

Cache: `~/.npm` cache keyed on `package-lock.json` hash.
**Acceptance criteria:**
- Workflow triggers only when `frontend/` files change (path filter)
- All four checks (lint, typecheck, test, build) run as separate steps and report independently
- `npm test -- --run` step fails the workflow if any Vitest test fails
- Build artifact uploaded as GitHub Actions artifact (retention: 7 days)
- Bundle size reported in workflow summary (use `du -sh dist/`)
- Workflow completes in under 5 minutes
- Workflow is a required status check for `main` branch protection (TASK-CI01)

---

### TASK-CI07: GitHub Actions secrets and environment configuration
**Domain:** CI/CD
**Depends on:** TASK-CI01
**Description:** Document and configure all required GitHub Actions secrets and variables. Create `docs/ci-secrets.md` listing every secret, its purpose, and how to rotate it. Required secrets:
- `DROPLET_SSH_KEY` — private SSH key for deploying to DigitalOcean droplet (deploy user)
- `DROPLET_IP` — IP address of production droplet
- `DROPLET_USER` — SSH username (e.g., `deploy`)
- `SLACK_WEBHOOK_URL` (optional) — Slack notifications on deploy success/failure
- `FINNHUB_API_KEY` (optional) — used in production `.env` on droplet, not stored in GH secrets directly
**Acceptance criteria:**
- All required secrets listed in `docs/ci-secrets.md` with rotation procedures
- No secrets committed to the repository (`.env` files in `.gitignore`)
- Deploy workflow (TASK-CI08) fails with a clear error if `DROPLET_SSH_KEY` is not set
- SSH key uses ED25519 algorithm (not RSA)
- Deploy user on droplet has minimal permissions: `docker`, `docker compose`, read `/opt/sse/`

---

### TASK-CI08: Deploy workflow — tagged release to production
**Domain:** CI/CD
**Depends on:** TASK-CI03, TASK-CI06, TASK-CI07
**Description:** Create `.github/workflows/deploy.yml`. Triggers on: push of tag matching `v*.*.*`. Steps:
1. `actions/checkout@v4`
2. Verify all CI checks passed on the tagged commit (use `gh` CLI to check run status)
3. SSH to droplet via `appleboy/ssh-action@v1`:
   ```bash
   cd /opt/sse
   git fetch --tags
   git checkout ${{ github.ref_name }}
   docker compose pull
   docker compose up -d --remove-orphans
   ```
4. Health check loop: poll each service's `/health` endpoint until all return 200 (timeout 120s, retry every 5s)
5. If health checks fail: trigger rollback (reuse TASK-CI09 logic, run as inline step)
6. Post deploy summary to GitHub Release notes (image tags, service versions)
7. (Optional) Notify Slack via webhook on success or failure
**Acceptance criteria:**
- Only triggers on `v*.*.*` tag push (not on branch push)
- Deploy is blocked if any required CI check failed on the tagged commit
- Health check polling correctly identifies degraded services
- On health check failure, rollback runs automatically and the workflow fails
- Droplet SSH credentials pulled from GitHub secrets (TASK-CI07)
- Workflow logs show each `docker compose` command output in full
- Total deploy time (excluding health check wait) < 5 minutes

---

### TASK-CI09: Rollback workflow — manual dispatch
**Domain:** CI/CD
**Depends on:** TASK-CI08
**Description:** Create `.github/workflows/rollback.yml`. Triggers on: `workflow_dispatch` with input `target_tag` (the version to roll back to, e.g., `v1.0.0`). Steps:
1. Validate `target_tag` exists in the repository
2. SSH to droplet:
   ```bash
   cd /opt/sse
   git checkout ${{ inputs.target_tag }}
   docker compose pull
   docker compose up -d --remove-orphans
   ```
3. Health check loop (same as TASK-CI08)
4. Report rollback result in workflow summary
**Acceptance criteria:**
- Requires manual dispatch with explicit `target_tag` input (no accidental triggers)
- Tag existence validated before SSH to droplet
- Rollback completes in under 5 minutes
- Health check confirms services healthy after rollback
- Workflow output clearly states what version was rolled back to
- Recommended usage documented in `docs/runbooks/rollback.md`

---

### TASK-CI10: docker-compose.override.yml for local development
**Domain:** CI/CD
**Depends on:** TASK-OPS08
**Description:** Create `docker-compose.override.yml` for local development convenience. Docker Compose automatically merges this with `docker-compose.yml`. Overrides:
- **Volume mounts:** mount local source directories into containers for hot-reload
  ```yaml
  scraper:
    volumes:
      - ./scraper:/app
    command: ["python", "-m", "scraper.main", "--dev"]
  backend:
    volumes:
      - ./backend:/app
    command: ["uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]
  processor:
    volumes:
      - ./processor:/app
  pricing:
    volumes:
      - ./pricing:/app
  frontend:
    volumes:
      - ./frontend:/app
    command: ["npm", "run", "dev", "--", "--host"]
    ports:
      - "5173:5173"  # Vite dev server
  ```
- Disable certbot (no TLS locally)
- Set `LOG_LEVEL=DEBUG` for all services
- Forward all service ports to localhost for direct inspection
- Keep `restart: "no"` so crashes don't auto-restart (easier debugging)
**Acceptance criteria:**
- `docker compose up` (no `-f` flag) picks up the override automatically
- Hot-reload works for backend (uvicorn --reload) and frontend (Vite HMR)
- File committed to repo at `docker-compose.override.yml`
- File is NOT in `.gitignore` (it's shared dev config, not personal config)
- Any developer-specific overrides documented as: create a `docker-compose.local.yml` and run `docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.local.yml up`

---

### TASK-CI11: Makefile for common development commands
**Domain:** CI/CD
**Depends on:** TASK-CI02, TASK-CI05, TASK-CI10
**Description:** Create `Makefile` at repo root with targets for common dev and CI operations. Targets:
```makefile
# Development
make dev           # docker compose up with override (hot-reload mode)
make down          # docker compose down
make logs          # docker compose logs -f
make shell-api     # docker compose exec api bash
make shell-db      # docker compose exec postgres psql -U sse sse

# Testing
make test          # run all unit tests across all services
make test-fast     # run only @pytest.mark.fast tagged tests
make test-int      # run integration tests (requires docker compose up)
make test-fe       # run frontend lint + typecheck + build

# Code quality
make lint          # ruff check across all Python services
make format        # ruff format across all Python services
make typecheck     # mypy across all Python services

# Database
make migrate       # run alembic upgrade head
make migration     # create new migration (prompts for name)
make db-reset      # drop and recreate local DB (dev only)

# CI simulation
make ci            # run the same checks as backend-ci workflow locally
make ci-int        # run integration tests using docker-compose.test.yml

# Deploy (requires SSH access)
make deploy TAG=v1.0.0  # tag and push to trigger deploy workflow
make rollback TAG=v0.9.0  # manually trigger rollback workflow
```
**Acceptance criteria:**
- All targets documented with `make help` (using `##` comment convention)
- `make test` and `make ci` pass on a clean repo
- `make dev` brings up a fully functional local stack
- `make deploy` does NOT SSH directly — it creates a git tag and pushes to trigger the GH Actions workflow
- Makefile uses `.PHONY` for all non-file targets
- No hardcoded paths — relative to repo root

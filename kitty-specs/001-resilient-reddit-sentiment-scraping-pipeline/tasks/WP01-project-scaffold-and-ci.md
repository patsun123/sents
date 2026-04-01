---
work_package_id: WP01
title: Project Scaffold & CI
lane: "done"
dependencies: []
base_branch: master
base_commit: addfacf7f1924059eb3d6e5d084d96f4922bd46b
created_at: '2026-03-10T16:07:47.490465+00:00'
subtasks:
- T001
- T002
- T003
- T004
- T005
phase: Phase 0 - Foundation
assignee: ''
agent: "claude-sonnet-4-6"
shell_pid: "2472"
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-03-09T19:41:43Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
requirement_refs:
- FR-001
- FR-009
- FR-013
---

# Work Package Prompt: WP01 - Project Scaffold & CI

## Objectives & Success Criteria

- `worker/` directory exists with correct structure (src/, tests/, Dockerfile, pyproject.toml)
- `docker-compose.yml` at repo root brings up worker + postgres + redis with health checks
- `docker compose build` succeeds with no errors
- `pytest` collects zero tests but exits 0 (infrastructure ready)
- `ruff check worker/` exits 0 on empty source
- `mypy worker/src/` exits 0 on empty source
- `bandit -r worker/src/` exits 0 on empty source
- GitHub Actions CI runs all gates on push; fails if any gate fails

## Context & Constraints

- **Constitution**: `.kittify/memory/constitution.md` — Python 3.12+, Docker Compose, pytest 90%+, ruff + mypy + bandit
- **Plan**: `kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/plan.md`
- **Architecture**: `worker/` is a standalone Python service — no HTTP server, runs as a background worker process
- **Docker Compose** lives at repo root (shared across future services — API, frontend)
- **No worktree for WP01**: implement directly on feature branch

**Implementation command**: `spec-kitty implement WP01`

---

## Subtasks & Detailed Guidance

### Subtask T001 - Create worker/ directory structure

**Purpose**: Establish the skeleton that all downstream WPs will build into. Must match the project structure defined in `plan.md`.

**Steps**:
1. Create the following directory tree:
   ```
   worker/
   +-- src/
   |   +-- pipeline/
   |   |   +-- __init__.py
   |   +-- scrapers/
   |   |   +-- __init__.py
   |   +-- classifiers/
   |   |   +-- __init__.py
   |   +-- tickers/
   |   |   +-- __init__.py
   |   |   +-- data/          (for blocklist and ticker universe files)
   |   +-- storage/
   |   |   +-- __init__.py
   |   +-- alerting/
   |   |   +-- __init__.py
   |   +-- __init__.py
   |   +-- config.py          (empty stub — implemented in WP06)
   +-- tests/
   |   +-- unit/
   |   |   +-- test_classifiers/
   |   |   |   +-- __init__.py
   |   |   +-- test_scrapers/
   |   |   |   +-- __init__.py
   |   |   +-- test_tickers/
   |   |   |   +-- __init__.py
   |   |   +-- test_pipeline/
   |   |       +-- __init__.py
   |   +-- integration/
   |   |   +-- __init__.py
   |   +-- conftest.py        (empty stub)
   +-- pyproject.toml
   +-- Dockerfile
   +-- README.md              (minimal placeholder)
   ```

2. `worker/src/__init__.py` — empty, marks as package
3. `worker/pyproject.toml` — see T002 steps for full content

**Files**: All under `worker/`

**Notes**: Every `__init__.py` should be empty at this stage. Source code comes in later WPs.

---

### Subtask T002 - Configure docker-compose.yml and pyproject.toml

**Purpose**: Define the service topology and Python project configuration that all other WPs depend on.

**Steps**:

1. Create `docker-compose.yml` at **repo root** (not inside `worker/`):
   ```yaml
   services:
     worker:
       build: ./worker
       restart: unless-stopped
       environment:
         DATABASE_URL: postgresql+asyncpg://sentix:sentix@postgres:5432/sentix
         REDIS_URL: redis://redis:6379/0
         REDDIT_CLIENT_ID: ${REDDIT_CLIENT_ID:-}
         REDDIT_CLIENT_SECRET: ${REDDIT_CLIENT_SECRET:-}
         REDDIT_USERNAME: ${REDDIT_USERNAME:-}
         REDDIT_PASSWORD: ${REDDIT_PASSWORD:-}
         CLASSIFIER_BACKEND: ${CLASSIFIER_BACKEND:-vader}
         SENTRY_DSN: ${SENTRY_DSN:-}
         CYCLE_INTERVAL_MINUTES: ${CYCLE_INTERVAL_MINUTES:-15}
         ALERT_THRESHOLD: ${ALERT_THRESHOLD:-3}
       depends_on:
         postgres:
           condition: service_healthy
         redis:
           condition: service_healthy
       healthcheck:
         test: ["CMD", "python", "-c", "import os, time; f='.health'; assert os.path.exists(f) and time.time()-os.path.getmtime(f) < 1200"]
         interval: 20m
         timeout: 10s
         retries: 3
         start_period: 60s

     postgres:
       image: postgres:16-alpine
       restart: unless-stopped
       environment:
         POSTGRES_USER: sentix
         POSTGRES_PASSWORD: sentix
         POSTGRES_DB: sentix
       volumes:
         - postgres_data:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U sentix"]
         interval: 10s
         timeout: 5s
         retries: 5

     redis:
       image: redis:7-alpine
       restart: unless-stopped
       volumes:
         - redis_data:/data
       healthcheck:
         test: ["CMD", "redis-cli", "ping"]
         interval: 10s
         timeout: 5s
         retries: 5

   volumes:
     postgres_data:
     redis_data:
   ```

2. Create `worker/Dockerfile`:
   ```dockerfile
   FROM python:3.12-slim

   WORKDIR /app

   COPY pyproject.toml .
   RUN pip install --no-cache-dir -e ".[dev]"

   COPY src/ src/

   CMD ["python", "-m", "worker"]
   ```

3. Create `worker/pyproject.toml`:
   ```toml
   [build-system]
   requires = ["setuptools>=70"]
   build-backend = "setuptools.backends.legacy:build"

   [project]
   name = "sentix-worker"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = [
     "apscheduler>=3.10",
     "asyncpg>=0.29",
     "httpx>=0.27",
     "praw>=7.8",
     "pydantic-settings>=2.3",
     "python-json-logger>=2.0",
     "sentry-sdk>=2.0",
     "sqlalchemy[asyncio]>=2.0",
     "vaderSentiment>=3.3",
   ]

   [project.optional-dependencies]
   dev = [
     "alembic>=1.13",
     "bandit>=1.7",
     "mypy>=1.10",
     "pytest>=8.0",
     "pytest-asyncio>=0.23",
     "pytest-cov>=5.0",
     "pytest-httpx>=0.30",
     "ruff>=0.5",
   ]

   [tool.setuptools.packages.find]
   where = ["src"]

   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   testpaths = ["tests"]
   addopts = "--cov=src --cov-report=term-missing --cov-fail-under=90"

   [tool.ruff]
   line-length = 100
   target-version = "py312"

   [tool.ruff.lint]
   select = ["E", "F", "I", "N", "UP", "S", "B", "A", "C4", "PT"]
   ignore = ["S101"]  # allow assert in tests

   [tool.mypy]
   python_version = "3.12"
   strict = true
   ignore_missing_imports = false

   [tool.coverage.run]
   source = ["src"]
   omit = ["tests/*"]
   ```

**Files**: `docker-compose.yml` (repo root), `worker/Dockerfile`, `worker/pyproject.toml`

---

### Subtask T003 - Configure ruff, mypy, bandit

**Purpose**: Enforce code quality from day one. All gates must be green before any other WP begins.

**Steps**:
1. Ruff config is in `pyproject.toml` (see T002) — no separate file needed
2. Add `worker/mypy.ini` or extend `pyproject.toml` with `[tool.mypy]` section (already done in T002)
3. Create `worker/.bandit` (bandit config):
   ```ini
   [bandit]
   exclude_dirs = tests
   skips = B101
   ```
   `B101` (assert statements) is allowed in test files — exclude tests from bandit scan
4. Verify locally:
   ```bash
   cd worker
   pip install -e ".[dev]"
   ruff check src/
   mypy src/
   bandit -r src/ -c .bandit
   ```
   All should pass on the empty skeleton.

**Files**: `worker/.bandit`, config already in `pyproject.toml`

---

### Subtask T004 - Set up pytest with coverage and asyncio fixtures

**Purpose**: Test infrastructure must be ready before any implementation starts.

**Steps**:
1. `pytest` config is in `pyproject.toml` (see T002)
2. Create `worker/tests/conftest.py`:
   ```python
   """
   Shared pytest fixtures for the SentiX worker test suite.
   """
   import pytest
   import pytest_asyncio
   ```
   (Expand in WP05 with database fixtures)
3. Verify: `cd worker && pytest` — should collect 0 tests, exit 0
4. Verify coverage gate works: create a minimal test that exercises a real module, confirm `--cov-fail-under=90` triggers correctly when coverage is low

**Files**: `worker/tests/conftest.py`

---

### Subtask T005 - Configure GitHub Actions CI pipeline

**Purpose**: Automate quality gates so no merge succeeds without passing all checks.

**Steps**:
1. Create `.github/workflows/worker-ci.yml` at repo root:
   ```yaml
   name: Worker CI

   on:
     push:
       paths:
         - "worker/**"
         - "docker-compose.yml"
         - ".github/workflows/worker-ci.yml"
     pull_request:
       paths:
         - "worker/**"

   jobs:
     quality:
       runs-on: ubuntu-latest
       services:
         postgres:
           image: postgres:16-alpine
           env:
             POSTGRES_USER: sentix
             POSTGRES_PASSWORD: sentix
             POSTGRES_DB: sentix
           options: >-
             --health-cmd pg_isready
             --health-interval 10s
             --health-timeout 5s
             --health-retries 5
           ports:
             - 5432:5432
         redis:
           image: redis:7-alpine
           options: >-
             --health-cmd "redis-cli ping"
             --health-interval 10s
             --health-timeout 5s
             --health-retries 5
           ports:
             - 6379:6379

       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.12"
             cache: "pip"
             cache-dependency-path: "worker/pyproject.toml"

         - name: Install dependencies
           run: pip install -e ".[dev]"
           working-directory: worker

         - name: Lint (ruff)
           run: ruff check src/
           working-directory: worker

         - name: Type check (mypy)
           run: mypy src/
           working-directory: worker

         - name: Security scan (bandit)
           run: bandit -r src/ -c .bandit
           working-directory: worker

         - name: Test with coverage
           env:
             DATABASE_URL: postgresql+asyncpg://sentix:sentix@localhost:5432/sentix
             REDIS_URL: redis://localhost:6379/0
           run: pytest
           working-directory: worker
   ```

**Files**: `.github/workflows/worker-ci.yml`

**Notes**: All gates run in sequence; any failure blocks merge. PostgreSQL and Redis are available for integration tests.

---

## Test Strategy

No application logic exists in WP01 — tests will be added in subsequent WPs. The CI pipeline itself is the validation:
- `docker compose build` must succeed
- All quality tools must exit 0 on empty source
- `pytest` must exit 0 (0 tests collected is fine)

---

## Risks & Mitigations

- **Windows dev environment**: Docker Desktop on Windows requires WSL2 backend; document in README. Path handling in Dockerfile uses forward slashes (Linux container).
- **Dependency version drift**: All versions pinned in `pyproject.toml`; update via `pip-audit` when needed.
- **CI cost**: GitHub Actions free tier provides 2,000 min/month — more than sufficient for a solo project.

## Review Guidance

- Verify `docker compose up --build` runs without errors on a clean pull
- Verify all four CI gates (lint, typecheck, security, test) appear in GitHub Actions output
- Verify `restart: unless-stopped` is set on the worker service
- Verify no secrets are hardcoded anywhere (all via environment variables)
- Verify named volumes exist for postgres and redis data

## Activity Log

- 2026-03-09T19:41:43Z - system - lane=planned - Prompt created.
- 2026-03-10T16:07:47Z – claude-sonnet-4-6 – shell_pid=2472 – lane=doing – Assigned agent via workflow command
- 2026-03-11T04:35:19Z – claude-sonnet-4-6 – shell_pid=2472 – lane=for_review – Ready for review: scaffold complete, all 4 quality gates green (ruff, mypy, bandit, pytest 1 passed)
- 2026-03-11T04:40:58Z – claude-sonnet-4-6 – shell_pid=2472 – lane=done – Review passed: scaffold structure complete, all CI gates configured, docker-compose healthy, GitHub Actions workflow verified

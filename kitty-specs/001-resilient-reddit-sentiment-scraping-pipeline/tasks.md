# Work Packages: Resilient Reddit Sentiment Scraping Pipeline

**Inputs**: Design documents from `kitty-specs/001-resilient-reddit-sentiment-scraping-pipeline/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Full test coverage required (90%+ per constitution — no human QA).

**Organization**: 44 fine-grained subtasks (T001-T044) across 8 work packages. Each WP is independently implementable. Interfaces (Protocols) are defined before implementations to enable safe parallelism.

---

## Work Package WP01: Project Scaffold & CI (Priority: P0)

**Goal**: Create the `worker/` service skeleton, Docker Compose config, and CI pipeline so all downstream WPs have a consistent base to build on.
**Independent Test**: `docker compose up --build` succeeds; `pytest` collects zero tests but exits 0; `ruff`, `mypy`, and `bandit` all pass on empty source.
**Prompt**: `tasks/WP01-project-scaffold-and-ci.md`
**Estimated size**: ~280 lines

### Included Subtasks
- [x] T001 Create `worker/` directory structure with `src/`, `tests/`, `Dockerfile`, `pyproject.toml`
- [x] T002 Configure `docker-compose.yml` at repo root (worker, postgres, redis services with health checks and `restart: unless-stopped`)
- [x] T003 [P] Set up ruff, mypy, and bandit with project-appropriate configuration
- [x] T004 [P] Set up pytest with pytest-asyncio, coverage config (90% gate), and asyncpg test fixtures
- [x] T005 Configure GitHub Actions CI pipeline (test, lint, type-check, security scan — all gates required)

### Implementation Notes
- Worker container runs `python -m worker` (no HTTP server)
- Postgres and Redis services in Compose must have named volumes so data survives container restarts
- CI must fail on any single gate failure; no soft gates

### Parallel Opportunities
- T003 and T004 can be set up in parallel once pyproject.toml exists (T001)

### Dependencies
- None (first package)

### Risks & Mitigations
- Windows path issues in Docker on dev machine: use forward slashes in Dockerfile, test with `docker compose up` on target Linux-like environment
- Pin all dependency versions in pyproject.toml to prevent drift

**Requirements Refs**: FR-001 (scheduling foundation), FR-009 (logging foundation), FR-013 (error handling foundation)

---

## Work Package WP02: Scraper Layer (Priority: P1)

**Goal**: Implement the dual-lane Reddit scraping system — primary `.json` endpoint scraper and PRAW OAuth fallback — both conforming to the `RedditScraper` Protocol.
**Independent Test**: Unit tests pass with mocked HTTP responses; JsonEndpointScraper returns `RawComment` objects; PRAWOAuthScraper returns the same structure; lane failover triggers after 3 consecutive rate-limit errors.
**Prompt**: `tasks/WP02-scraper-layer.md`
**Estimated size**: ~420 lines

### Included Subtasks
- [x] T006 Define `RedditScraper` Protocol and `RawComment` dataclass and error hierarchy in `worker/src/scrapers/base.py`
- [x] T007 Implement `JsonEndpointScraper` in `worker/src/scrapers/json_endpoint.py` (`.json` endpoint, User-Agent rotation, pagination via `after` param, incremental fetch by `created_utc`)
- [x] T008 Implement `PRAWOAuthScraper` in `worker/src/scrapers/praw_oauth.py` (PRAW script OAuth flow, same `RedditScraper` interface)
- [x] T009 [P] Implement exponential backoff and rate-limit detection in `JsonEndpointScraper` (429 -> backoff; 403/private -> `ScraperUnavailableError`)
- [x] T010 [P] Implement lane-switch logic stub in `worker/src/scrapers/__init__.py` (`get_scraper()` factory, reads `SCRAPER_BACKEND` env var; also used by pipeline runner for failover)
- [x] T011 Write unit tests for both scrapers in `worker/tests/unit/test_scrapers/` with `pytest-httpx` mocked responses

### Implementation Notes
- `RawComment` must contain ONLY: `text`, `upvotes`, `created_utc` — no username, comment ID, post ID
- User-Agent rotation pool: minimum 5 strings, selected randomly per request
- Incremental fetch: `since` parameter filters `created_utc > last_successful_run.started_at`
- PRAW credentials: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` env vars

### Parallel Opportunities
- T009 and T010 can proceed in parallel after T007 and T008 base implementations exist

### Dependencies
- Depends on WP01

### Risks & Mitigations
- Reddit API ToS: PRAW OAuth requires a registered Reddit app — document setup in README
- Comment pagination: deep threads may exceed `limit=100`; implement recursive pagination guard

**Requirements Refs**: FR-001, FR-006, FR-007, FR-008, FR-012, FR-013

---

## Work Package WP03: Ticker Extraction & Disambiguation (Priority: P1)

**Goal**: Build the ticker detection system that reliably extracts real stock tickers from WSB-style Reddit text while suppressing false positives (common English words that are valid ticker symbols).
**Independent Test**: `extractor.extract("$GME is mooning and IT is crashing")` returns `["GME"]` only; `disambiguator.is_valid("IT")` returns `False`; `disambiguator.is_valid("TSLA")` returns `True`.
**Prompt**: `tasks/WP03-ticker-extraction-and-disambiguation.md`
**Estimated size**: ~320 lines

### Included Subtasks
- [x] T012 Implement `TickerExtractor` in `worker/src/tickers/extractor.py` (regex for `$TICKER` explicit mentions and bare `ALL-CAPS` 1-5 char patterns)
- [x] T013 Implement `TickerDisambiguator` in `worker/src/tickers/disambiguator.py` (false-positive blocklist lookup + NYSE/NASDAQ universe validation; `$TICKER` explicit mentions bypass blocklist)
- [x] T014 Create and version `worker/src/tickers/data/false_positive_blocklist.txt` and `worker/src/tickers/data/ticker_universe.txt` (sourced from SEC EDGAR or equivalent)
- [x] T015 [P] Write unit tests for `TickerExtractor` in `worker/tests/unit/test_tickers/test_extractor.py`
- [x] T016 [P] Write unit tests for `TickerDisambiguator` in `worker/tests/unit/test_tickers/test_disambiguator.py`

### Implementation Notes
- Regex patterns: `\$([A-Z]{1,5})\b` for explicit; `\b([A-Z]{2,5})\b` for bare (note: 2-char minimum for bare to reduce noise)
- `$TICKER` format always passes disambiguation — explicit intent overrides blocklist
- Ticker universe file should be loaded once at module import and cached in memory
- Blocklist file should support runtime reload (no restart required for additions)

### Parallel Opportunities
- T015 and T016 can proceed in parallel once T012-T014 are complete

### Dependencies
- Depends on WP01

### Risks & Mitigations
- False negatives: single-letter tickers (`A`, `B`) are too noisy — exclude from bare-caps pattern, require `$A` explicit form
- Ticker universe staleness: document quarterly refresh cadence in README

**Requirements Refs**: FR-002, FR-005

---

## Work Package WP04: Classifier Interface & VADER (Priority: P1)

**Goal**: Define the pluggable `SentimentClassifier` Protocol and implement VADER as the default classifier, with a factory that allows FinBERT or any future model to slot in via environment variable.
**Independent Test**: `classify("GME to the moon!")` returns `ClassificationResult(polarity=1, ...)`; `classify("This company is bankrupt")` returns `ClassificationResult(polarity=-1, ...)`; neutral text returns `discarded=True`; `CLASSIFIER_BACKEND=vader` and `CLASSIFIER_BACKEND=finbert` both load without error.
**Prompt**: `tasks/WP04-classifier-interface-and-vader.md`
**Estimated size**: ~300 lines

### Included Subtasks
- [x] T017 Define `SentimentClassifier` Protocol and `ClassificationResult` dataclass in `worker/src/classifiers/base.py` (per `contracts/classifier-interface.md`)
- [x] T018 Implement `VADERClassifier` in `worker/src/classifiers/vader.py` (VADER compound score -> polarity mapping; neutral [-0.05, 0.05] -> `discarded=True`)
- [x] T019 Implement classifier factory `get_classifier()` in `worker/src/classifiers/__init__.py` (`CLASSIFIER_BACKEND` env var; lazy FinBERT import)
- [x] T020 [P] Write unit tests for VADER in `worker/tests/unit/test_classifiers/test_vader.py` (positive, negative, neutral, edge cases)
- [x] T021 [P] Write integration test for classifier selection via `CLASSIFIER_BACKEND` env var

### Implementation Notes
- VADER `SentimentIntensityAnalyzer` must be instantiated once at `__init__` (not per call) — it's expensive
- FinBERT stub: `get_classifier("finbert")` imports `worker.src.classifiers.finbert.FinBERTClassifier` — this module doesn't need to exist yet; the import error is the expected signal that it's not configured
- `ClassificationResult.confidence` for VADER: use `abs(compound_score)` normalized to [0,1]
- Text passed to `classify()` must never be logged at any level

### Parallel Opportunities
- T020 and T021 can proceed in parallel after T017-T019 are complete

### Dependencies
- Depends on WP01

### Risks & Mitigations
- VADER accuracy on financial slang: acceptable for now (Priority 2 in roadmap is accuracy validation); document known limitations in docstrings
- Neutral threshold: [-0.05, 0.05] may need tuning — make it configurable via `VADER_NEUTRAL_THRESHOLD` env var

**Requirements Refs**: FR-003, FR-004a

---

## Work Package WP05: Storage Layer (Priority: P1)

**Goal**: Implement the PostgreSQL persistence layer — SQLAlchemy models, Alembic migrations, and CRUD modules for all four entities — matching the schema in `contracts/schema.sql`.
**Independent Test**: Against a test PostgreSQL instance: insert a `CollectionRun`, bulk-insert 50 `SentimentSignal` rows, query signals by ticker and time window — all pass; no PII columns exist in schema.
**Prompt**: `tasks/WP05-storage-layer.md`
**Estimated size**: ~400 lines

### Included Subtasks
- [x] T022 Create SQLAlchemy 2.x async models in `worker/src/storage/models.py` (`DataSource`, `CollectionRun`, `SentimentSignal`, `ScoredResult` — matching `contracts/schema.sql`)
- [x] T023 Set up Alembic migrations in `worker/` with initial migration matching `contracts/schema.sql`; include all indexes
- [x] T024 Implement `SignalStore` in `worker/src/storage/signals.py` (`bulk_insert_signals()`, `get_signals_for_window()`)
- [x] T025 Implement `RunStore` in `worker/src/storage/runs.py` (`create_run()`, `update_run_status()`, `get_last_successful_run()`, pessimistic default status)
- [x] T026 [P] Implement `SourceStore` in `worker/src/storage/sources.py` (`get_active_sources()`, `disable_source()`)
- [x] T027 Write integration tests for all storage operations in `worker/tests/integration/test_storage.py` (real PostgreSQL via Docker)

### Implementation Notes
- Use `asyncpg` engine with SQLAlchemy async session
- `bulk_insert_signals()`: use `INSERT ... ON CONFLICT DO NOTHING` to handle idempotent reprocessing
- `CollectionRun` pessimistic default: insert with `status='failed'`, update to `success`/`partial` on completion — ensures crash leaves accurate record
- `get_last_successful_run()`: returns `None` if no successful run exists; pipeline handles this as "fetch all available comments"
- Database URL from `DATABASE_URL` env var

### Parallel Opportunities
- T026 can proceed in parallel with T024 and T025 once T022 and T023 are complete
- WP05 can be implemented in parallel with WP02, WP03, WP04 (no shared code)

### Dependencies
- Depends on WP01

### Risks & Mitigations
- Migration drift: Alembic `--check` flag in CI verifies no unapplied migrations exist
- Connection pooling: configure `pool_size` and `max_overflow` for expected concurrency (single worker, low concurrency)

**Requirements Refs**: FR-004, FR-005, FR-006, FR-011

---

## Work Package WP06: Pipeline Orchestrator (Priority: P1)

**Goal**: Assemble the full pipeline — scheduler, cycle runner, sequential queue, and config — wiring together all the components from WP02-WP05 into a single working service entry point.
**Independent Test**: Start the worker locally; observe a cycle run in logs within 15 minutes; verify signals appear in PostgreSQL; kill and restart the container; verify automatic recovery and next cycle runs.
**Prompt**: `tasks/WP06-pipeline-orchestrator.md`
**Estimated size**: ~450 lines

### Included Subtasks
- [x] T028 Implement `CycleRunner` in `worker/src/pipeline/runner.py` (single cycle: load sources -> scrape each -> extract tickers -> classify -> bulk insert signals -> update run status)
- [ ] T029 Implement `CycleQueue` in `worker/src/pipeline/queue.py` (asyncio `Lock`-based sequential execution; queues next cycle if current is still running)
- [ ] T030 Implement `Scheduler` in `worker/src/pipeline/scheduler.py` (APScheduler `AsyncIOScheduler`, 15-min `IntervalTrigger`, `max_instances=1`, PostgreSQL job store for restart persistence)
- [ ] T031 Implement `Settings` in `worker/src/config.py` (Pydantic `BaseSettings`; all config via env vars: `DATABASE_URL`, `REDIS_URL`, `REDDIT_*`, `CLASSIFIER_BACKEND`, `SCRAPER_BACKEND`, `CYCLE_INTERVAL_MINUTES`)
- [ ] T032 [P] Write unit tests for `CycleRunner` in `worker/tests/unit/test_pipeline/` (mock all dependencies; verify signal count, run status transitions, PII-free output)
- [ ] T033 Implement `worker/src/main.py` entry point (startup validation, scheduler start, asyncio event loop, graceful shutdown on SIGTERM)

### Implementation Notes
- `CycleRunner` must catch all exceptions per subreddit — one failed source must NOT abort the cycle for other sources
- `CycleQueue`: use `asyncio.Lock`; if lock is held when timer fires, queue one pending run (not unlimited backlog)
- APScheduler PostgreSQL job store: uses `DATABASE_URL` — prevents duplicate job creation on container restart
- Graceful shutdown: `SIGTERM` -> drain current cycle -> exit 0

### Parallel Opportunities
- T032 can proceed alongside T029-T030 once T028 interface is stable

### Dependencies
- Depends on WP02, WP03, WP04, WP05

### Risks & Mitigations
- Cycle duration exceeding 15 minutes: `CycleQueue` handles this; add a warning log if cycle takes > 12 minutes
- APScheduler job store schema: Alembic does NOT manage APScheduler's internal tables — let APScheduler create them automatically

**Requirements Refs**: FR-001, FR-002, FR-003, FR-006, FR-007, FR-008, FR-011, FR-013

---

## Work Package WP07: Alerting & Observability (Priority: P2)

**Goal**: Add Sentry error capture, structured JSON logging throughout, error threshold alerting, and a Docker health check — giving the operator eyes on the pipeline without live monitoring.
**Independent Test**: Trigger a simulated cycle failure; verify Sentry captures the event; verify log output is valid JSON with no PII fields; verify Docker health check returns healthy within 30 seconds of startup.
**Prompt**: `tasks/WP07-alerting-and-observability.md`
**Estimated size**: ~320 lines

### Included Subtasks
- [ ] T034 Implement Sentry integration in `worker/src/alerting/__init__.py` (`init_sentry()`, `capture_cycle_failure()`, `capture_error()`)
- [ ] T035 [P] Implement structured JSON logging throughout all modules (`python-json-logger`; every log record includes `timestamp`, `level`, `module`, `cycle_id` — never username or comment text)
- [ ] T036 [P] Implement error threshold logic in `CycleRunner` (alert via Sentry when N consecutive cycles fail; `N` configurable via `ALERT_THRESHOLD` env var, default 3)
- [ ] T037 [P] Add Docker health check to `Dockerfile` (file-based: `worker/` writes `.health` timestamp after each successful cycle; `HEALTHCHECK` in Dockerfile reads it)
- [ ] T038 Write tests for alerting in `worker/tests/unit/test_alerting/` (mock Sentry SDK; assert alert fires at threshold; assert no PII in log output)

### Implementation Notes
- Sentry DSN from `SENTRY_DSN` env var; if not set, alerting silently no-ops (safe for local dev)
- Log sanitization: assert in tests that `RawComment.text` and any username-shaped strings never appear in log output
- Health check file: `worker/.health` — updated by runner after each successful cycle completion; Docker `HEALTHCHECK --interval=20m` reads mtime

### Parallel Opportunities
- T035, T036, T037 can all proceed in parallel once T034 base is initialized

### Dependencies
- Depends on WP06

### Risks & Mitigations
- PII leakage via logs: enforce in tests; use `structlog` or `python-json-logger` with a custom processor that strips sensitive keys
- Sentry not configured in dev: ensure `SENTRY_DSN` absence is a no-op, not a crash

**Requirements Refs**: FR-009, FR-010

---

## Work Package WP08: Integration Tests & Hardening (Priority: P2)

**Goal**: Full end-to-end integration tests, PII audit, cycle overlap verification, source isolation verification, coverage gate enforcement, and documentation completion.
**Independent Test**: `pytest tests/integration/` passes against a running Docker Compose stack; coverage report shows >= 90% across all modules; README accurately describes setup and operation.
**Prompt**: `tasks/WP08-integration-tests-and-hardening.md`
**Estimated size**: ~380 lines

### Included Subtasks
- [ ] T039 Write E2E integration test in `worker/tests/integration/test_pipeline_e2e.py` (full cycle with mocked Reddit `.json` responses and real PostgreSQL; assert signals stored, run status = success, no PII)
- [ ] T040 [P] Write PII audit test in `worker/tests/integration/test_pii_audit.py` (assert no username, comment body, comment ID in any DB table after a cycle; assertion covers all columns of all tables)
- [ ] T041 [P] Write cycle overlap test in `worker/tests/unit/test_pipeline/test_queue.py` (simulate two concurrent trigger fires; assert second queues, first completes, second runs after)
- [ ] T042 [P] Write source isolation test in `worker/tests/integration/test_source_isolation.py` (one subreddit returns 503; assert other subreddits complete successfully and run status = partial)
- [ ] T043 Run coverage gate: `pytest --cov=worker/src --cov-fail-under=90` — fix any gaps before marking done
- [ ] T044 Documentation pass: `worker/README.md` (setup, env vars, running locally, adding subreddits); docstring audit on all public functions; `kitty-specs/001-.../contracts/` verify all contracts still match implementation

### Implementation Notes
- Integration tests require Docker Compose to be running (postgres, redis) — add `pytest-docker` or document manual prerequisite
- PII audit: write a generic scanner that inspects all rows of all tables for patterns matching usernames (alphanumeric + underscore, 3-20 chars) — this is intentionally over-broad to catch accidental leakage
- Coverage gaps most likely in: error paths, backoff logic, lane failover — target these specifically

### Parallel Opportunities
- T040, T041, T042 can all proceed in parallel after T039 establishes the E2E test infrastructure

### Dependencies
- Depends on WP07

### Risks & Mitigations
- Flaky integration tests: use `pytest-retry` for network-dependent tests; always mock Reddit calls, never hit real Reddit in CI
- Coverage gate: do not lower the threshold — add tests instead

**Requirements Refs**: FR-001, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-012, FR-013

---

## Dependency & Execution Summary

**Sequence**:
```
WP01 (scaffold)
  -> WP02 (scrapers)    [parallel with WP03, WP04, WP05]
  -> WP03 (tickers)     [parallel with WP02, WP04, WP05]
  -> WP04 (classifiers) [parallel with WP02, WP03, WP05]
  -> WP05 (storage)     [parallel with WP02, WP03, WP04]
     -> WP06 (orchestrator, depends on WP02+WP03+WP04+WP05)
        -> WP07 (alerting)
           -> WP08 (integration tests & hardening)
```

**Parallelization**: After WP01, WP02-WP05 can all run in parallel (4 independent subsystems). WP06 is the integration point — it waits for all four.

**MVP Scope**: WP01 + WP02 + WP03 + WP04 + WP05 + WP06 — a functioning pipeline that collects, scores, and stores. WP07 and WP08 add operational safety and test hardening.

---

## Subtask Index

| ID | Summary | WP | Priority | Parallel? |
|----|---------|-----|----------|-----------|
| T001 | Create worker/ directory structure | WP01 | P0 | No |
| T002 | Configure docker-compose.yml | WP01 | P0 | No |
| T003 | Set up ruff, mypy, bandit | WP01 | P0 | Yes |
| T004 | Set up pytest + coverage | WP01 | P0 | Yes |
| T005 | Configure GitHub Actions CI | WP01 | P0 | No |
| T006 | Define RedditScraper Protocol | WP02 | P1 | No |
| T007 | Implement JsonEndpointScraper | WP02 | P1 | No |
| T008 | Implement PRAWOAuthScraper | WP02 | P1 | No |
| T009 | Exponential backoff in JsonEndpointScraper | WP02 | P1 | Yes |
| T010 | Scraper factory with lane-switch | WP02 | P1 | Yes |
| T011 | Unit tests for scrapers | WP02 | P1 | No |
| T012 | Implement TickerExtractor | WP03 | P1 | No |
| T013 | Implement TickerDisambiguator | WP03 | P1 | No |
| T014 | Create blocklist and universe data files | WP03 | P1 | No |
| T015 | Unit tests for TickerExtractor | WP03 | P1 | Yes |
| T016 | Unit tests for TickerDisambiguator | WP03 | P1 | Yes |
| T017 | Define SentimentClassifier Protocol | WP04 | P1 | No |
| T018 | Implement VADERClassifier | WP04 | P1 | No |
| T019 | Classifier factory (get_classifier) | WP04 | P1 | No |
| T020 | Unit tests for VADER | WP04 | P1 | Yes |
| T021 | Integration test for CLASSIFIER_BACKEND | WP04 | P1 | Yes |
| T022 | SQLAlchemy async models | WP05 | P1 | No |
| T023 | Alembic migrations setup | WP05 | P1 | No |
| T024 | SignalStore CRUD | WP05 | P1 | No |
| T025 | RunStore CRUD | WP05 | P1 | No |
| T026 | SourceStore CRUD | WP05 | P1 | Yes |
| T027 | Storage integration tests | WP05 | P1 | No |
| T028 | Implement CycleRunner | WP06 | P1 | No |
| T029 | Implement CycleQueue | WP06 | P1 | No |
| T030 | Implement Scheduler | WP06 | P1 | No |
| T031 | Implement Settings (config.py) | WP06 | P1 | No |
| T032 | Unit tests for CycleRunner | WP06 | P1 | Yes |
| T033 | Implement main.py entry point | WP06 | P1 | No |
| T034 | Sentry integration | WP07 | P2 | No |
| T035 | Structured JSON logging | WP07 | P2 | Yes |
| T036 | Error threshold alerting | WP07 | P2 | Yes |
| T037 | Docker health check | WP07 | P2 | Yes |
| T038 | Alerting unit tests | WP07 | P2 | No |
| T039 | E2E integration test | WP08 | P2 | No |
| T040 | PII audit test | WP08 | P2 | Yes |
| T041 | Cycle overlap test | WP08 | P2 | Yes |
| T042 | Source isolation test | WP08 | P2 | Yes |
| T043 | Coverage gate validation | WP08 | P2 | No |
| T044 | Documentation pass | WP08 | P2 | No |

---
work_package_id: WP06
title: Pipeline Orchestrator
lane: "done"
dependencies: [WP02, WP03, WP04, WP05]
base_branch: 001-resilient-reddit-sentiment-scraping-pipeline-WP06-merge-base
base_commit: 1b5885f73e4941e43582d41eca698703726a730a
created_at: '2026-03-13T15:08:36.475085+00:00'
subtasks:
- T028
- T029
- T030
- T031
- T032
- T033
phase: Phase 2 - Integration
assignee: ''
agent: "claude-sonnet-4-6"
shell_pid: "4480"
review_status: "approved"
reviewed_by: "Patrick Sun"
history:
- timestamp: '2026-03-09T19:41:43Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
requirement_refs:
- FR-001
- FR-002
- FR-003
- FR-006
- FR-007
- FR-008
- FR-011
- FR-013
---

# Work Package Prompt: WP06 - Pipeline Orchestrator

## Objectives & Success Criteria

- `CycleRunner` executes a full pipeline cycle: load sources, scrape, extract, classify, store
- One failed subreddit does NOT abort the cycle for other subreddits
- `CycleQueue` enforces sequential execution — no concurrent cycles ever run
- `Scheduler` fires every 15 minutes; `max_instances=1` means APScheduler handles queuing automatically
- Container starts, runs first cycle within 15 minutes, and logs structured output
- `docker compose down && docker compose up` restores scheduler state from PostgreSQL job store
- Graceful shutdown on `SIGTERM`: current cycle completes, then process exits 0
- All settings configurable via environment variables (no hardcoded values)

## Context & Constraints

- **Spec**: FR-001 (schedule + sequential), FR-002 (ticker extraction), FR-003 (classification), FR-006 (incremental), FR-007 (retry), FR-008 (source isolation), FR-011 (configurable sources), FR-013 (no crashes)
- **Research**: R-005 — APScheduler `AsyncIOScheduler` with `max_instances=1`
- **Dependencies**: All of WP02, WP03, WP04, WP05 must be complete before WP06 starts
- **CRITICAL**: `CycleRunner` must never store `RawComment.text` or any PII — it processes in-memory and discards

**Implementation command**: `spec-kitty implement WP06 --base WP05`

(WP05 is the last parallel dependency to land. Branch from WP05's branch.)

---

## Subtasks & Detailed Guidance

### Subtask T031 - Implement Settings (config.py) first

**Purpose**: All configuration must come from environment variables. Implement this first so other modules can import it. (Listed as T031 in tasks.md but implemented first in WP06 to unblock other subtasks.)

**Steps**:
1. Create `worker/src/config.py`:

```python
"""
SSE Worker configuration.

All settings come from environment variables.
No default should expose production credentials.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Worker configuration loaded from environment variables.

    All fields have safe defaults for local development.
    Production deployments must set DATABASE_URL, REDIS_URL, and
    REDDIT_* credentials explicitly.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://sse:sse@localhost:5432/sse"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Reddit credentials (PRAW fallback lane)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""

    # Classifier
    classifier_backend: str = "vader"
    vader_neutral_threshold: float = 0.05

    # Pipeline
    cycle_interval_minutes: int = 15
    alert_threshold: int = 3  # consecutive failures before alerting

    # Sentry
    sentry_dsn: str = ""

    # Logging
    log_level: str = "INFO"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

**Files**: `worker/src/config.py`

---

### Subtask T028 - Implement CycleRunner

**Purpose**: Executes a single complete pipeline cycle. The most complex module — coordinates all four subsystems (scraper, extractor, disambiguator, classifier, storage).

**Steps**:
1. Create `worker/src/pipeline/runner.py`:

```python
"""
CycleRunner: executes one complete collection cycle.

Cycle flow:
  1. Load active sources from database
  2. Get last successful run timestamp (for incremental fetch)
  3. For each source: scrape -> extract tickers -> classify -> accumulate signals
  4. Bulk insert all signals
  5. Update run status (success/partial/failed)

Source isolation: one failed source does NOT abort others.
PII guarantee: RawComment objects are created in-memory and never stored.
"""
```

2. Class `CycleRunner`:
   - Constructor: `def __init__(self, settings: Settings, db_session_factory, classifier, primary_scraper, fallback_scraper, extractor, disambiguator)`
   - Method `async def run_cycle(self) -> CollectionRun`

3. Full cycle logic:
   ```python
   async def run_cycle(self) -> CollectionRun:
       async with self._session_factory() as session:
           run_store = RunStore(session)
           signal_store = SignalStore(session)
           source_store = SourceStore(session)

           run = await run_store.create_run()
           await session.flush()  # get run.id

           last_run = await run_store.get_last_successful_run()
           since = last_run.started_at if last_run else (now - timedelta(hours=1))

           sources = await source_store.get_active_sources()
           signals_batch = []
           succeeded = 0
           failed_sources = []

           for source in sources:
               try:
                   async for comment in self._scraper.fetch_comments(source.subreddit_name, since):
                       candidates = self._extractor.extract(comment.text)
                       valid_tickers = self._disambiguator.filter(candidates)
                       for ticker in valid_tickers:
                           result = self._classifier.classify(comment.text)
                           if not result.discarded:
                               signals_batch.append({
                                   "collection_run_id": run.id,
                                   "ticker_symbol": ticker,
                                   "sentiment_polarity": result.polarity,
                                   "upvote_weight": comment.upvotes,
                                   "collected_at": comment.created_utc,
                                   "source_subreddit": source.subreddit_name,
                               })
                   succeeded += 1
               except ScraperUnavailableError:
                   failed_sources.append(source.subreddit_name)
                   logger.warning("source_unavailable", subreddit=source.subreddit_name)
               except Exception as exc:
                   failed_sources.append(source.subreddit_name)
                   logger.error("source_failed", subreddit=source.subreddit_name, error=str(exc))

           stored = await signal_store.bulk_insert_signals(signals_batch)

           status = "success" if not failed_sources else ("partial" if succeeded > 0 else "failed")
           await run_store.update_run_status(
               run, status=status,
               sources_attempted=len(sources), sources_succeeded=succeeded,
               signals_stored=stored,
               error_summary=f"Failed: {failed_sources}" if failed_sources else None,
           )
           await session.commit()
           return run
   ```

**Files**: `worker/src/pipeline/runner.py`

**Notes**: `comment.text` is passed to `classifier.classify()` in-memory only — it is never stored, never logged, never assigned to a variable that outlives the loop iteration.

---

### Subtask T029 - Implement CycleQueue

**Purpose**: Enforce sequential cycle execution. If a cycle is still running when the next interval fires, queue one pending run rather than skipping or parallelizing.

**Steps**:
1. Create `worker/src/pipeline/queue.py`:

```python
"""
CycleQueue: enforces sequential, non-concurrent cycle execution.

APScheduler max_instances=1 prevents concurrent job starts.
CycleQueue provides an additional asyncio.Lock for fine-grained
in-process sequencing and "queue one" overflow behavior.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class CycleQueue:
    """
    Ensures pipeline cycles run sequentially.

    At most ONE cycle runs at a time. If a new cycle is triggered
    while one is running, it queues and runs immediately after.
    Additional triggers while the queue is full are dropped.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._queued = False

    async def submit(self, coro) -> None:
        """
        Submit a cycle coroutine for sequential execution.

        If idle: run immediately.
        If running and queue empty: queue one.
        If running and queue full: drop (log warning).
        """
        if self._lock.locked():
            if not self._queued:
                self._queued = True
                logger.warning("cycle_queued", reason="previous_cycle_still_running")
                # Wait for lock, then run
                async with self._lock:
                    self._queued = False
                    await coro
            else:
                logger.warning("cycle_dropped", reason="queue_full")
            return

        async with self._lock:
            await coro
```

**Files**: `worker/src/pipeline/queue.py`

---

### Subtask T030 - Implement Scheduler

**Purpose**: APScheduler fires every 15 minutes, submits cycles to the queue, and persists job state to PostgreSQL so restarts don't create duplicate jobs.

**Steps**:
1. Create `worker/src/pipeline/scheduler.py`:

```python
"""
Scheduler: APScheduler-backed 15-minute cycle trigger.

Uses AsyncIOScheduler with PostgreSQL job store for restart persistence.
max_instances=1 prevents APScheduler from launching concurrent jobs.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_settings


def create_scheduler(run_cycle_fn) -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance.

    Args:
        run_cycle_fn: Async callable to invoke each interval.

    Returns:
        Configured AsyncIOScheduler (not yet started).
    """
    settings = get_settings()

    # Use sync SQLAlchemy URL for APScheduler (it manages its own connection)
    sync_db_url = settings.database_url.replace("+asyncpg", "")

    jobstores = {
        "default": SQLAlchemyJobStore(url=sync_db_url)
    }

    scheduler = AsyncIOScheduler(jobstores=jobstores)
    scheduler.add_job(
        run_cycle_fn,
        trigger=IntervalTrigger(minutes=settings.cycle_interval_minutes),
        id="pipeline_cycle",
        name="SSE Sentiment Collection Cycle",
        replace_existing=True,
        max_instances=1,  # APScheduler-level concurrency guard
    )

    return scheduler
```

**Files**: `worker/src/pipeline/scheduler.py`

---

### Subtask T032 - Unit tests for CycleRunner

**Purpose**: Verify cycle coordination logic — source isolation, signal accumulation, status transitions, and PII-free output.

**Steps**:
1. Create `worker/tests/unit/test_pipeline/test_runner.py`:
   - Mock all dependencies (scraper, classifier, extractor, disambiguator, stores)
   - Test: successful cycle -> `status='success'`, correct signal count
   - Test: one source fails -> `status='partial'`, other sources succeed
   - Test: all sources fail -> `status='failed'`
   - Test: neutral comments (discarded=True) produce no signals
   - Test: `RawComment.text` never appears in any stored signal dict
   - Test: `error_summary` does not contain subreddit usernames (only subreddit names)

**Files**: `worker/tests/unit/test_pipeline/test_runner.py`

---

### Subtask T033 - Implement main.py entry point

**Purpose**: Wire everything together. Entry point for `python -m worker`. Handles startup, scheduler start, and graceful shutdown.

**Steps**:
1. Create `worker/src/main.py`:

```python
"""
SSE Worker entry point.

Startup sequence:
  1. Load and validate settings
  2. Initialize Sentry (if DSN configured)
  3. Initialize classifier (validate it's ready)
  4. Run Alembic migrations (ensures schema is current)
  5. Seed default data sources (if table is empty)
  6. Start APScheduler
  7. Run asyncio event loop until SIGTERM

Shutdown sequence (SIGTERM):
  1. Stop accepting new cycles
  2. Wait for current cycle to complete
  3. Shut down scheduler
  4. Exit 0
"""
import asyncio
import signal
import logging

from .config import get_settings
from .classifiers import get_classifier
from .pipeline.runner import CycleRunner
from .pipeline.queue import CycleQueue
from .pipeline.scheduler import create_scheduler
from .alerting import init_sentry


async def main() -> None:
    settings = get_settings()
    init_sentry(settings.sentry_dsn)

    classifier = get_classifier()
    assert classifier.is_ready(), "Classifier failed to initialize"

    # ... (dependency wiring, scheduler start, event loop)


if __name__ == "__main__":
    asyncio.run(main())
```

2. Create `worker/src/__main__.py`:
```python
from .main import main
import asyncio
asyncio.run(main())
```

3. Add default data source seeding: if `data_sources` table is empty, insert the three default subreddits (`wallstreetbets`, `stocks`, `investing`)

4. Implement graceful SIGTERM handling:
   ```python
   loop = asyncio.get_event_loop()
   stop_event = asyncio.Event()
   loop.add_signal_handler(signal.SIGTERM, stop_event.set)
   await stop_event.wait()
   scheduler.shutdown(wait=True)  # wait=True lets current job finish
   ```

**Files**: `worker/src/main.py`, `worker/src/__main__.py`

---

## Test Strategy

- Unit tests for `CycleRunner` use full mock injection — no database, no HTTP
- Integration tests (WP08) cover the full wired-together cycle
- Manual smoke test: `docker compose up`, observe first cycle in logs within 15 minutes

## Risks & Mitigations

- **APScheduler PostgreSQL job store**: Uses sync SQLAlchemy URL (not asyncpg). Derive from `DATABASE_URL` by stripping `+asyncpg`.
- **Cycle duration warning**: Log at WARNING level if cycle exceeds `cycle_interval_minutes * 0.8` minutes (e.g., 12 minutes for a 15-minute cycle).
- **Default source seeding**: Only seed if table is empty — idempotent.

## Review Guidance

- Verify one source failure does not abort the cycle (check test coverage of this path)
- Verify `comment.text` never appears in any signal dict or log call
- Verify `SIGTERM` causes graceful shutdown (current cycle completes before exit)
- Verify APScheduler uses PostgreSQL job store (not in-memory)
- Verify `cycle_interval_minutes` is configurable via env var

## Activity Log

- 2026-03-09T19:41:43Z - system - lane=planned - Prompt created.
- 2026-03-13T15:08:37Z – claude-sonnet-4-6 – shell_pid=22328 – lane=doing – Assigned agent via workflow command
- 2026-03-13T20:31:11Z – claude-sonnet-4-6 – shell_pid=22328 – lane=for_review – Pipeline orchestrator complete: APScheduler sequential cycles, dual-lane scraping, 167 tests, 97.93% coverage, all gates green
- 2026-03-13T20:31:45Z – claude-sonnet-4-6 – shell_pid=4480 – lane=doing – Started review via workflow command
- 2026-03-13T20:33:43Z – claude-sonnet-4-6 – shell_pid=4480 – lane=done – Review passed: All quality gates green (ruff, mypy, bandit, 97.93% coverage, 167 tests). CycleRunner orchestrates full cycle with source isolation, dual-lane scraping switches to PRAW after 3 consecutive rate-limit errors. CollectionRun created with status='failed' updated to success/partial on completion. APScheduler uses PostgreSQL job store with max_instances=1. Graceful SIGTERM shutdown implemented. Comment text never logged or stored. Full docstrings on all public APIs.

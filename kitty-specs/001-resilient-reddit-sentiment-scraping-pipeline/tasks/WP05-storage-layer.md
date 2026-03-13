---
work_package_id: WP05
title: Storage Layer
lane: "doing"
dependencies: [WP01]
base_branch: 001-resilient-reddit-sentiment-scraping-pipeline-WP01
base_commit: 7e38de562c61693212607d5f4fb1061125053261
created_at: '2026-03-13T14:53:47.615744+00:00'
subtasks:
- T022
- T023
- T024
- T025
- T026
- T027
phase: Phase 1 - Core Components
assignee: ''
agent: ''
shell_pid: "6432"
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-03-09T19:41:43Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
requirement_refs:
- FR-004
- FR-005
- FR-006
- FR-011
---

# Work Package Prompt: WP05 - Storage Layer

## Objectives & Success Criteria

- SQLAlchemy 2.x async models match `contracts/schema.sql` exactly (same columns, types, constraints)
- Alembic initial migration creates all tables and indexes when applied to a fresh database
- `SignalStore.bulk_insert_signals()` inserts multiple signals atomically; idempotent on re-run
- `RunStore.create_run()` inserts with `status='failed'` (pessimistic default); `update_run_status()` sets final status
- `RunStore.get_last_successful_run()` returns `None` when no successful run exists
- `SourceStore.get_active_sources()` returns only enabled subreddits
- Integration tests pass against a real PostgreSQL instance; no test hits the real internet
- `ruff`, `mypy`, `bandit` clean

## Context & Constraints

- **Data model**: `kitty-specs/001-.../data-model.md` — canonical entity definitions
- **Schema**: `kitty-specs/001-.../contracts/schema.sql` — DDL source of truth
- **Spec**: FR-004, FR-005 (zero PII), FR-006 (incremental), FR-011 (configurable sources)
- **WP05 is parallel with WP02, WP03, WP04** — no shared code
- **Pessimistic default**: `CollectionRun` starts as `status='failed'` — a container crash mid-cycle leaves an accurate record

**Implementation command**: `spec-kitty implement WP05 --base WP01`

---

## Subtasks & Detailed Guidance

### Subtask T022 - SQLAlchemy async models

**Purpose**: Python representation of the database schema. Must match `contracts/schema.sql` exactly.

**Steps**:
1. Create `worker/src/storage/models.py`:

```python
"""
SQLAlchemy ORM models for SSE worker.

PRIVACY GUARANTEE: No model contains a column for Reddit usernames,
comment IDs, post IDs, or any user-attributable data.
All column definitions must match contracts/schema.sql exactly.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Index, Integer,
    Numeric, SmallInteger, String, Text, Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DataSource(Base):
    """A configured Reddit subreddit. Never deleted -- only disabled."""
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subreddit_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_data_sources_enabled", "enabled", postgresql_where=(enabled == True)),
    )


class CollectionRun(Base):
    """One pipeline execution cycle. Append-only."""
    __tablename__ = "collection_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="failed")
    sources_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sources_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    signals: Mapped[list[SentimentSignal]] = relationship("SentimentSignal", back_populates="run")

    __table_args__ = (
        CheckConstraint("status IN ('success', 'partial', 'failed')", name="ck_run_status"),
        Index("idx_collection_runs_started_at", "started_at"),
        Index("idx_collection_runs_status", "status"),
    )


class SentimentSignal(Base):
    """Atomic sentiment signal. Immutable after insert. Never contains PII."""
    __tablename__ = "sentiment_signals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    collection_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ticker_symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    sentiment_polarity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    upvote_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_subreddit: Mapped[str] = mapped_column(String(50), nullable=False)

    run: Mapped[CollectionRun] = relationship("CollectionRun", back_populates="signals")

    __table_args__ = (
        CheckConstraint("sentiment_polarity IN (-1, 1)", name="ck_signal_polarity"),
        CheckConstraint("upvote_weight >= 0", name="ck_signal_upvotes"),
        Index("idx_signals_ticker_time", "ticker_symbol", "collected_at"),
        Index("idx_signals_run", "collection_run_id"),
        Index("idx_signals_collected_at", "collected_at"),
        Index("idx_signals_subreddit", "source_subreddit"),
    )


class ScoredResult(Base):
    """Derived scoring algorithm output. Multiple algorithms per ticker/window."""
    __tablename__ = "scored_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticker_symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    algorithm_id: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_scored_confidence"),
        Index("idx_scored_ticker_algo_time", "ticker_symbol", "algorithm_id", "computed_at"),
        Index("idx_scored_computed_at", "computed_at"),
    )
```

**Files**: `worker/src/storage/models.py`

---

### Subtask T023 - Alembic migrations setup

**Purpose**: Reproducible schema creation via tracked migrations. The initial migration must create all tables and indexes exactly as defined in `contracts/schema.sql`.

**Steps**:
1. Initialize Alembic in `worker/`:
   ```bash
   cd worker
   alembic init migrations
   ```
2. Edit `worker/migrations/env.py`:
   - Import `Base` from `worker.src.storage.models`
   - Set `target_metadata = Base.metadata`
   - Configure async engine from `DATABASE_URL` env var
3. Generate initial migration:
   ```bash
   alembic revision --autogenerate -m "initial schema"
   ```
4. Review the generated migration — verify it matches `contracts/schema.sql` (all tables, indexes, constraints)
5. Add to `worker/pyproject.toml` scripts or document in README:
   ```bash
   # Apply migrations
   alembic upgrade head

   # Verify no unapplied migrations (used in CI)
   alembic check
   ```
6. Add `alembic check` step to GitHub Actions CI

**Files**: `worker/migrations/`, `worker/alembic.ini`

**Notes**: APScheduler will create its own internal tables — do NOT add those to Alembic migrations. Let APScheduler manage them.

---

### Subtask T024 - SignalStore CRUD

**Purpose**: Bulk-insert sentiment signals efficiently. Must be idempotent (re-running a cycle won't duplicate signals due to `ON CONFLICT DO NOTHING`).

**Steps**:
1. Create `worker/src/storage/signals.py`:

```python
"""
SignalStore: persistence operations for SentimentSignal.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SentimentSignal


class SignalStore:
    """CRUD operations for SentimentSignal records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_insert_signals(
        self,
        signals: list[dict],
    ) -> int:
        """
        Insert multiple signals atomically.

        Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.

        Args:
            signals: List of dicts with keys:
                collection_run_id, ticker_symbol, sentiment_polarity,
                upvote_weight, collected_at, source_subreddit

        Returns:
            Number of signals actually inserted (excluding conflicts).
        """
        if not signals:
            return 0
        stmt = insert(SentimentSignal).values(signals)
        stmt = stmt.on_conflict_do_nothing()
        result = await self._session.execute(stmt)
        return result.rowcount

    async def get_signals_for_window(
        self,
        ticker_symbol: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[SentimentSignal]:
        """
        Retrieve signals for a ticker within a time window.

        Used by scoring algorithms.
        """
        stmt = (
            select(SentimentSignal)
            .where(SentimentSignal.ticker_symbol == ticker_symbol.upper())
            .where(SentimentSignal.collected_at >= window_start)
            .where(SentimentSignal.collected_at <= window_end)
            .order_by(SentimentSignal.collected_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
```

**Files**: `worker/src/storage/signals.py`

---

### Subtask T025 - RunStore CRUD

**Purpose**: Track each collection cycle with pessimistic default status — a crash mid-cycle leaves status='failed' without any cleanup code.

**Steps**:
1. Create `worker/src/storage/runs.py`:

```python
"""
RunStore: persistence for CollectionRun records.

Design: pessimistic default -- runs insert as 'failed' and are
promoted to 'success'/'partial' only on clean completion.
A container crash mid-cycle leaves an accurate failure record.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CollectionRun


class RunStore:
    """CRUD operations for CollectionRun records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self) -> CollectionRun:
        """
        Create a new collection run with pessimistic status='failed'.

        Returns:
            The newly created CollectionRun (not yet committed).
        """
        run = CollectionRun(
            id=uuid.uuid4(),
            started_at=datetime.now(tz=timezone.utc),
            status="failed",
        )
        self._session.add(run)
        return run

    async def update_run_status(
        self,
        run: CollectionRun,
        status: str,
        sources_attempted: int,
        sources_succeeded: int,
        signals_stored: int,
        error_summary: str | None = None,
    ) -> None:
        """
        Update a run's outcome fields on completion.

        Args:
            status: 'success', 'partial', or 'failed'.
            error_summary: Human-readable description. Must not contain PII.
        """
        run.status = status
        run.completed_at = datetime.now(tz=timezone.utc)
        run.sources_attempted = sources_attempted
        run.sources_succeeded = sources_succeeded
        run.signals_stored = signals_stored
        run.error_summary = error_summary

    async def get_last_successful_run(self) -> CollectionRun | None:
        """
        Return the most recent run with status='success' or 'partial'.

        Returns None if no successful run exists (first run ever).
        The pipeline uses this to determine the `since` timestamp for incremental fetch.
        """
        stmt = (
            select(CollectionRun)
            .where(CollectionRun.status.in_(["success", "partial"]))
            .order_by(CollectionRun.started_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
```

**Files**: `worker/src/storage/runs.py`

---

### Subtask T026 - SourceStore CRUD

**Purpose**: Load active subreddits from database at the start of each cycle. Config changes (add/disable subreddit) take effect on next cycle with no restart.

**Steps**:
1. Create `worker/src/storage/sources.py`:

```python
"""
SourceStore: manage configured Reddit data sources.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DataSource


class SourceStore:
    """CRUD operations for DataSource records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_sources(self) -> list[DataSource]:
        """Return all enabled data sources."""
        stmt = select(DataSource).where(DataSource.enabled == True)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def disable_source(self, subreddit_name: str) -> None:
        """
        Disable a subreddit by name.

        Used by the pipeline when a subreddit is permanently unavailable
        (e.g., banned). Soft delete -- record preserved for audit.
        """
        from datetime import datetime, timezone
        stmt = select(DataSource).where(
            DataSource.subreddit_name == subreddit_name.lower()
        )
        result = await self._session.execute(stmt)
        source = result.scalar_one_or_none()
        if source:
            source.enabled = False
            source.disabled_at = datetime.now(tz=timezone.utc)
```

**Files**: `worker/src/storage/sources.py`

---

### Subtask T027 - Storage integration tests

**Purpose**: Verify all CRUD operations against a real PostgreSQL instance. These are integration tests — they require the database to be running.

**Steps**:
1. Add database fixture to `worker/tests/conftest.py`:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from worker.src.storage.models import Base
import os

@pytest_asyncio.fixture
async def db_session():
    url = os.getenv("DATABASE_URL", "postgresql+asyncpg://sse:sse@localhost:5432/sse_test")
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

2. Create `worker/tests/integration/test_storage.py`:
   - Test `SignalStore.bulk_insert_signals()`: insert 10 signals, verify count
   - Test idempotency: insert same signals twice, verify no duplicates
   - Test `RunStore` full lifecycle: create -> update_status -> get_last_successful
   - Test `RunStore.get_last_successful_run()` returns `None` on fresh database
   - Test `SourceStore.get_active_sources()` returns only enabled sources
   - Test `SourceStore.disable_source()` sets `enabled=False` and `disabled_at`
   - Verify no PII column names exist in schema (programmatic assertion)

**Files**: `worker/tests/conftest.py` (update), `worker/tests/integration/test_storage.py`

---

## Test Strategy

- Integration tests require PostgreSQL (available in GitHub Actions via service container)
- Use a separate `sse_test` database to avoid polluting dev data
- Schema created fresh per test session, dropped after
- Run: `pytest tests/integration/test_storage.py -v`

## Risks & Mitigations

- **Migration drift**: `alembic check` in CI catches this before merge
- **Async session management**: Use `async with` consistently; never hold sessions across yield boundaries in non-fixture code
- **UUID generation**: Use `uuid.uuid4()` in Python, not `gen_random_uuid()` from PostgreSQL, for testability

## Review Guidance

- Verify `SentimentSignal` has no `username`, `comment_id`, `post_id`, or `author` columns
- Verify `CollectionRun` is inserted with `status='failed'` by default
- Verify `bulk_insert_signals()` uses `ON CONFLICT DO NOTHING`
- Verify `get_last_successful_run()` returns `None` on empty database
- Verify Alembic migration matches `contracts/schema.sql` (compare column by column)

## Activity Log

- 2026-03-09T19:41:43Z - system - lane=planned - Prompt created.

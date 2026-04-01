"""
Unit tests for RunStore.

All database interactions are mocked — no PostgreSQL connection required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.storage.models import CollectionRun
from src.storage.runs import RunStore


def _make_session() -> AsyncMock:
    session = AsyncMock()
    # session.add() is synchronous in SQLAlchemy — override to avoid coroutine warning.
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# create_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_run_returns_collection_run() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()
    assert isinstance(run, CollectionRun)


@pytest.mark.asyncio
async def test_create_run_default_status_is_failed() -> None:
    """Pessimistic default: new runs must start as 'failed'."""
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_create_run_has_uuid_id() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()
    assert isinstance(run.id, uuid.UUID)


@pytest.mark.asyncio
async def test_create_run_started_at_is_utc() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()
    assert run.started_at.tzinfo is not None


@pytest.mark.asyncio
async def test_create_run_adds_to_session() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()
    session.add.assert_called_once_with(run)


# ---------------------------------------------------------------------------
# update_run_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_run_status_sets_fields() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()

    await store.update_run_status(
        run=run,
        status="success",
        sources_attempted=3,
        sources_succeeded=3,
        signals_stored=150,
        comments_processed=500,
    )

    assert run.status == "success"
    assert run.sources_attempted == 3
    assert run.sources_succeeded == 3
    assert run.signals_stored == 150
    assert run.comments_processed == 500
    assert run.error_summary is None
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_update_run_status_sets_completed_at() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()

    before = datetime.now(tz=UTC)
    await store.update_run_status(
        run=run,
        status="failed",
        sources_attempted=2,
        sources_succeeded=1,
        signals_stored=0,
        error_summary="scrape timed out",
    )
    after = datetime.now(tz=UTC)

    assert run.completed_at is not None
    assert before <= run.completed_at <= after


@pytest.mark.asyncio
async def test_update_run_status_records_error_summary() -> None:
    session = _make_session()
    store = RunStore(session)
    run = await store.create_run()

    await store.update_run_status(
        run=run,
        status="partial",
        sources_attempted=2,
        sources_succeeded=1,
        signals_stored=42,
        error_summary="one source rate-limited",
    )

    assert run.error_summary == "one source rate-limited"


# ---------------------------------------------------------------------------
# get_last_successful_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_last_successful_run_returns_none_on_empty_db() -> None:
    """No successful runs → must return None (e.g. first ever run)."""
    session = _make_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    store = RunStore(session)
    result = await store.get_last_successful_run()

    assert result is None


@pytest.mark.asyncio
async def test_get_last_successful_run_returns_run() -> None:
    session = _make_session()
    run = CollectionRun(
        id=uuid.uuid4(),
        started_at=datetime.now(tz=UTC),
        status="success",
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = run
    session.execute.return_value = mock_result

    store = RunStore(session)
    result = await store.get_last_successful_run()

    assert result is run
    assert result.status == "success"


@pytest.mark.asyncio
async def test_get_last_successful_run_queries_db() -> None:
    session = _make_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    store = RunStore(session)
    await store.get_last_successful_run()

    session.execute.assert_called_once()

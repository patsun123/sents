"""
Integration tests for the storage layer.

These tests require a running PostgreSQL instance.  They are skipped
automatically when the database is unavailable.

To run locally::

    DATABASE_URL=postgresql+asyncpg://sentix:sentix@localhost:5432/sentix_test \\
        pytest tests/integration/test_storage.py -v

In CI the database is provided as a service container.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

# ---------------------------------------------------------------------------
# Skip entire module when PostgreSQL is unavailable.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.asyncio


def _pg_available() -> bool:
    """Return True when DATABASE_URL is set or a local sentix_test DB responds."""
    import os  # noqa: PLC0415
    import socket  # noqa: PLC0415

    if os.getenv("DATABASE_URL"):
        return True
    try:
        with socket.create_connection(("localhost", 5432), timeout=1):
            return True
    except OSError:
        return False


skip_no_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not available — skipping integration tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal_dict(run_id: uuid.UUID, ticker: str = "GME") -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "collection_run_id": run_id,
        "ticker_symbol": ticker,
        "sentiment_polarity": 1,
        "upvote_weight": 5,
        "collected_at": datetime.now(tz=UTC),
        "source_subreddit": "wallstreetbets",
    }


# ---------------------------------------------------------------------------
# SignalStore integration tests
# ---------------------------------------------------------------------------


@skip_no_pg
async def test_bulk_insert_signals_inserts_correct_count(db_session: object) -> None:  # type: ignore[misc]
    """Inserting 10 signals returns rowcount=10."""
    from src.storage.runs import RunStore  # noqa: PLC0415
    from src.storage.signals import SignalStore  # noqa: PLC0415

    run_store = RunStore(db_session)  # type: ignore[arg-type]
    run = await run_store.create_run()
    await db_session.flush()  # type: ignore[union-attr]

    signal_store = SignalStore(db_session)  # type: ignore[arg-type]
    signals = [_signal_dict(run.id) for _ in range(10)]
    count = await signal_store.bulk_insert_signals(signals)
    assert count == 10


@skip_no_pg
async def test_bulk_insert_idempotency(db_session: object) -> None:  # type: ignore[misc]
    """Inserting the same signals twice must not create duplicates."""
    from src.storage.runs import RunStore  # noqa: PLC0415
    from src.storage.signals import SignalStore  # noqa: PLC0415

    run_store = RunStore(db_session)  # type: ignore[arg-type]
    run = await run_store.create_run()
    await db_session.flush()  # type: ignore[union-attr]

    signals = [_signal_dict(run.id) for _ in range(5)]
    signal_store = SignalStore(db_session)  # type: ignore[arg-type]

    first = await signal_store.bulk_insert_signals(signals)
    second = await signal_store.bulk_insert_signals(signals)

    assert first == 5
    assert second == 0  # all conflicts — no new rows


# ---------------------------------------------------------------------------
# RunStore integration tests
# ---------------------------------------------------------------------------


@skip_no_pg
async def test_run_lifecycle(db_session: object) -> None:  # type: ignore[misc]
    """Full cycle: create → flush → update_status → get_last_successful."""
    from src.storage.runs import RunStore  # noqa: PLC0415

    store = RunStore(db_session)  # type: ignore[arg-type]

    run = await store.create_run()
    assert run.status == "failed"

    await db_session.flush()  # type: ignore[union-attr]

    await store.update_run_status(
        run=run,
        status="success",
        sources_attempted=2,
        sources_succeeded=2,
        signals_stored=99,
    )
    await db_session.commit()  # type: ignore[union-attr]

    last = await store.get_last_successful_run()
    assert last is not None
    assert last.id == run.id
    assert last.status == "success"
    assert last.signals_stored == 99


@skip_no_pg
async def test_get_last_successful_run_returns_none_on_fresh_db(
    db_session: object,  # type: ignore[misc]
) -> None:
    """A fresh database with no runs → get_last_successful_run returns None."""
    from src.storage.runs import RunStore  # noqa: PLC0415

    store = RunStore(db_session)  # type: ignore[arg-type]
    result = await store.get_last_successful_run()
    assert result is None


# ---------------------------------------------------------------------------
# SourceStore integration tests
# ---------------------------------------------------------------------------


@skip_no_pg
async def test_get_active_sources_returns_only_enabled(db_session: object) -> None:  # type: ignore[misc]
    """get_active_sources must exclude disabled records."""
    from src.storage.models import DataSource  # noqa: PLC0415
    from src.storage.sources import SourceStore  # noqa: PLC0415

    enabled = DataSource(
        id=uuid.uuid4(),
        subreddit_name="wallstreetbets",
        enabled=True,
        added_at=datetime.now(tz=UTC),
    )
    disabled = DataSource(
        id=uuid.uuid4(),
        subreddit_name="pennystocks",
        enabled=False,
        added_at=datetime.now(tz=UTC),
    )
    db_session.add(enabled)  # type: ignore[union-attr]
    db_session.add(disabled)  # type: ignore[union-attr]
    await db_session.flush()  # type: ignore[union-attr]

    store = SourceStore(db_session)  # type: ignore[arg-type]
    sources = await store.get_active_sources()

    names = {s.subreddit_name for s in sources}
    assert "wallstreetbets" in names
    assert "pennystocks" not in names


@skip_no_pg
async def test_disable_source_sets_enabled_false(db_session: object) -> None:  # type: ignore[misc]
    """disable_source must set enabled=False and disabled_at."""
    from src.storage.models import DataSource  # noqa: PLC0415
    from src.storage.sources import SourceStore  # noqa: PLC0415

    source = DataSource(
        id=uuid.uuid4(),
        subreddit_name="options",
        enabled=True,
        added_at=datetime.now(tz=UTC),
    )
    db_session.add(source)  # type: ignore[union-attr]
    await db_session.flush()  # type: ignore[union-attr]

    store = SourceStore(db_session)  # type: ignore[arg-type]
    await store.disable_source("options")

    assert source.enabled is False
    assert source.disabled_at is not None


# ---------------------------------------------------------------------------
# PII schema assertion
# ---------------------------------------------------------------------------


@skip_no_pg
async def test_no_pii_columns_in_schema(db_session: object) -> None:  # type: ignore[misc]
    """Programmatic assertion: no PII column names exist in any table."""
    from src.storage.models import (  # noqa: PLC0415
        CollectionRun,
        DataSource,
        SentimentSignal,
    )

    forbidden = {"username", "author", "comment_id", "post_id", "user_id"}
    for model in (DataSource, CollectionRun, SentimentSignal):
        cols = {c.name for c in model.__table__.columns}
        assert forbidden.isdisjoint(cols), (
            f"PII columns found in {model.__tablename__}: {forbidden & cols}"
        )

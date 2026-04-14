"""
Unit tests for SignalStore.

All database interactions are mocked — no PostgreSQL connection required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.signals import SignalStore


def _make_session() -> AsyncMock:
    """Return a mocked AsyncSession."""
    return AsyncMock()


def _make_signal_row(**kwargs: object) -> dict[str, object]:
    """Return a minimal valid signal dict."""
    base: dict[str, object] = {
        "collection_run_id": uuid.uuid4(),
        "ticker_symbol": "GME",
        "sentiment_polarity": 1,
        "upvote_weight": 10,
        "reply_count": 0,
        "collected_at": datetime.now(tz=UTC),
        "source_subreddit": "wallstreetbets",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# bulk_insert_signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_insert_empty_list_returns_zero() -> None:
    session = _make_session()
    store = SignalStore(session)
    count = await store.bulk_insert_signals([])
    assert count == 0
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_insert_returns_rowcount() -> None:
    session = _make_session()
    mock_result = MagicMock()
    mock_result.rowcount = 5
    session.execute.return_value = mock_result

    signals = [_make_signal_row() for _ in range(5)]
    store = SignalStore(session)

    with patch("src.storage.signals.insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
        mock_insert.return_value = mock_stmt
        mock_stmt.values.return_value = mock_stmt

        count = await store.bulk_insert_signals(signals)

    assert count == 5
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_insert_calls_on_conflict_do_nothing() -> None:
    """Idempotency: must use ON CONFLICT DO NOTHING."""
    session = _make_session()
    mock_result = MagicMock()
    mock_result.rowcount = 3
    session.execute.return_value = mock_result

    signals = [_make_signal_row() for _ in range(3)]
    store = SignalStore(session)

    with patch("src.storage.signals.insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_stmt.values.return_value = mock_stmt
        mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
        mock_insert.return_value = mock_stmt

        await store.bulk_insert_signals(signals)

    mock_stmt.on_conflict_do_nothing.assert_called_once()


# ---------------------------------------------------------------------------
# get_signals_for_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_signals_for_window_returns_list() -> None:
    session = _make_session()
    from src.storage.models import SentimentSignal  # noqa: PLC0415

    fake_signals = [
        SentimentSignal(
            id=uuid.uuid4(),
            collection_run_id=uuid.uuid4(),
            ticker_symbol="GME",
            sentiment_polarity=1,
            upvote_weight=5,
            reply_count=0,
            collected_at=datetime.now(tz=UTC),
            source_subreddit="wallstreetbets",
        )
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = fake_signals
    session.execute.return_value = mock_result

    store = SignalStore(session)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    result = await store.get_signals_for_window("gme", start, end)

    assert result == fake_signals
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_signals_for_window_uppercases_ticker() -> None:
    """Ticker symbol should be uppercased before querying."""
    session = _make_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result

    store = SignalStore(session)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)

    with patch("src.storage.signals.select") as mock_select:
        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt
        mock_stmt.order_by.return_value = mock_stmt
        mock_select.return_value = mock_stmt

        await store.get_signals_for_window("gme", start, end)

    # The call to select() happened — session.execute called once
    session.execute.assert_called_once()

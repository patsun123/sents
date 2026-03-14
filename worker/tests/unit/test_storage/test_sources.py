"""
Unit tests for SourceStore.

All database interactions are mocked — no PostgreSQL connection required.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.storage.models import DataSource
from src.storage.sources import SourceStore


def _make_session() -> AsyncMock:
    return AsyncMock()


def _make_source(
    subreddit: str = "wallstreetbets",
    enabled: bool = True,
) -> DataSource:
    return DataSource(
        id=uuid.uuid4(),
        subreddit_name=subreddit,
        enabled=enabled,
        added_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# get_active_sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_sources_returns_list() -> None:
    session = _make_session()
    sources = [_make_source("wallstreetbets"), _make_source("stocks")]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sources
    session.execute.return_value = mock_result

    store = SourceStore(session)
    result = await store.get_active_sources()

    assert result == sources
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_active_sources_returns_empty_list_when_none() -> None:
    session = _make_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result

    store = SourceStore(session)
    result = await store.get_active_sources()

    assert result == []


# ---------------------------------------------------------------------------
# disable_source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disable_source_sets_enabled_false() -> None:
    session = _make_session()
    source = _make_source("wallstreetbets", enabled=True)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = source
    session.execute.return_value = mock_result

    store = SourceStore(session)
    await store.disable_source("wallstreetbets")

    assert source.enabled is False


@pytest.mark.asyncio
async def test_disable_source_sets_disabled_at() -> None:
    session = _make_session()
    source = _make_source("wallstreetbets", enabled=True)
    assert source.disabled_at is None

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = source
    session.execute.return_value = mock_result

    before = datetime.now(tz=UTC)
    store = SourceStore(session)
    await store.disable_source("wallstreetbets")
    after = datetime.now(tz=UTC)

    assert source.disabled_at is not None
    assert before <= source.disabled_at <= after


@pytest.mark.asyncio
async def test_disable_source_lowercases_name() -> None:
    """Subreddit name lookup must be case-insensitive (lowercased before query)."""
    session = _make_session()
    source = _make_source("wallstreetbets", enabled=True)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = source
    session.execute.return_value = mock_result

    store = SourceStore(session)
    await store.disable_source("WallStreetBets")

    # The source must still be disabled regardless of input case
    assert source.enabled is False


@pytest.mark.asyncio
async def test_disable_source_noop_when_not_found() -> None:
    """Disabling a non-existent subreddit must not raise."""
    session = _make_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    store = SourceStore(session)
    # Should not raise
    await store.disable_source("doesnotexist")

    session.execute.assert_called_once()

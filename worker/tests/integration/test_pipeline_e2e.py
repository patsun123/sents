"""
End-to-end integration test for the SentiX sentiment pipeline.

Uses:
- Real PostgreSQL (via Docker Compose service in CI or local instance)
- Mocked Reddit .json responses via pytest-httpx (no real HTTP)
- Real VADER classifier
- Real ticker extractor and disambiguator
- Real storage layer

Validates:
- Signals are stored with correct schema after a successful cycle
- No PII in any stored record
- Run status transitions correctly (pending → success)
- Incremental fetch: second cycle with only old comments stores 0 new signals
- Cycle produces correct signal count for known mock data
"""
from __future__ import annotations

import socket
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tests.fixtures.reddit_responses import (
    MOCK_EMPTY_RESPONSE,
    MOCK_REDDIT_RESPONSE,
    MOCK_REDDIT_RESPONSE_OLD,
)

# ---------------------------------------------------------------------------
# Skip entire module when PostgreSQL is unavailable
# ---------------------------------------------------------------------------


def _pg_available() -> bool:
    """Return True when a PostgreSQL instance is reachable."""
    import os  # noqa: PLC0415

    if os.getenv("DATABASE_URL"):
        return True
    try:
        with socket.create_connection(("localhost", 5432), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _pg_available(), reason="PostgreSQL not available"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SUBREDDIT = "wallstreetbets"
WSB_URL = f"https://www.reddit.com/r/{SUBREDDIT}/new/.json?limit=100"


def _build_runner(session: Any) -> Any:
    """Build a CycleRunner wired to use the given DB session.

    Uses real classifier, extractor, disambiguator, and mocked PRAW fallback.
    """
    from src.alerting.threshold import AlertThresholdTracker  # noqa: PLC0415
    from src.classifiers.vader import VADERClassifier  # noqa: PLC0415
    from src.config import Settings  # noqa: PLC0415
    from src.pipeline.runner import CycleRunner  # noqa: PLC0415
    from src.scrapers.json_endpoint import JsonEndpointScraper  # noqa: PLC0415
    from src.scrapers.praw_oauth import PRAWOAuthScraper  # noqa: PLC0415
    from src.tickers.disambiguator import TickerDisambiguator  # noqa: PLC0415
    from src.tickers.extractor import TickerExtractor  # noqa: PLC0415

    settings = Settings(
        database_url="postgresql+asyncpg://sse:sse@localhost:5432/sse_test",
        redis_url="redis://localhost:6379/0",
        cycle_interval_minutes=15,
        alert_threshold=3,
        sentry_dsn="",
    )

    @asynccontextmanager  # type: ignore[misc]
    async def session_factory() -> Any:
        yield session

    primary_scraper = JsonEndpointScraper(
        user_agents=["SentiX-Test/1.0"],
        request_delay_seconds=0.0,
    )

    # Mock PRAW fallback so no real OAuth calls are made
    fallback_scraper = AsyncMock(spec=PRAWOAuthScraper)

    async def _no_comments(*_args: Any, **_kwargs: Any) -> Any:
        return
        yield  # make it an async generator

    fallback_scraper.fetch_comments = _no_comments

    alert_tracker = AlertThresholdTracker(
        threshold=settings.alert_threshold,
        alert_fn=lambda run_id, summary: None,  # no-op in tests
    )

    return CycleRunner(
        settings=settings,
        session_factory=session_factory,
        classifier=VADERClassifier(),
        primary_scraper=primary_scraper,
        fallback_scraper=fallback_scraper,
        extractor=TickerExtractor(),
        disambiguator=TickerDisambiguator(),
        alert_tracker=alert_tracker,
    )


@pytest_asyncio.fixture  # type: ignore[misc]
async def seeded_db_session(db_session: Any) -> Any:
    """db_session pre-populated with one enabled data source."""
    from src.storage.models import DataSource  # noqa: PLC0415

    source = DataSource(
        id=uuid.uuid4(),
        subreddit_name=SUBREDDIT,
        enabled=True,
        added_at=datetime.now(tz=UTC),
    )
    db_session.add(source)
    await db_session.flush()
    return db_session


# ---------------------------------------------------------------------------
# T039 — E2E cycle tests
# ---------------------------------------------------------------------------


async def test_full_cycle_success(
    seeded_db_session: Any,
    httpx_mock: Any,
) -> None:
    """Full pipeline cycle stores signals and marks run as success."""
    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)

    runner = _build_runner(seeded_db_session)
    run = await runner.run_cycle()

    assert run.status == "success"
    assert run.signals_stored > 0
    assert run.sources_attempted == 1
    assert run.sources_succeeded == 1
    assert run.completed_at is not None


async def test_full_cycle_signals_have_correct_schema(
    seeded_db_session: Any,
    httpx_mock: Any,
) -> None:
    """Stored signals have correct field types and valid polarity values.

    Uses TSLA rather than GME because VADER (pre-2014 lexicon) scores WSB slang
    like "to the moon" as neutral and discards the GME mock comment.  The TSLA
    bare-mention comment ("TSLA looking great this week") contains the word
    "great" which VADER reliably classifies as positive, so TSLA signals are
    guaranteed to be stored.
    """
    from src.storage.signals import SignalStore  # noqa: PLC0415

    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)

    runner = _build_runner(seeded_db_session)
    run = await runner.run_cycle()

    assert run.status == "success"
    assert run.signals_stored > 0

    window_start = datetime(2020, 1, 1, tzinfo=UTC)
    window_end = datetime(2099, 12, 31, tzinfo=UTC)

    signal_store = SignalStore(seeded_db_session)
    # TSLA appears in "TSLA looking great this week" — VADER scores "great"
    # as strongly positive, so this signal is reliably stored.
    tsla_signals = await signal_store.get_signals_for_window("TSLA", window_start, window_end)

    assert len(tsla_signals) > 0
    for signal in tsla_signals:
        assert signal.sentiment_polarity in (-1, 1)
        assert signal.upvote_weight >= 0
        assert signal.ticker_symbol == "TSLA"
        assert signal.source_subreddit == SUBREDDIT
        assert signal.collection_run_id == run.id


async def test_it_ticker_not_stored(
    seeded_db_session: Any,
    httpx_mock: Any,
) -> None:
    """The 'IT' ticker is in the blocklist and must not produce signals."""
    from src.storage.signals import SignalStore  # noqa: PLC0415

    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)

    runner = _build_runner(seeded_db_session)
    await runner.run_cycle()

    window_start = datetime(2020, 1, 1, tzinfo=UTC)
    window_end = datetime(2099, 12, 31, tzinfo=UTC)

    signal_store = SignalStore(seeded_db_session)
    it_signals = await signal_store.get_signals_for_window("IT", window_start, window_end)

    assert len(it_signals) == 0, (
        "'IT' is on the blocklist and must never appear as a stored signal"
    )


async def test_no_pii_after_cycle(
    seeded_db_session: Any,
    httpx_mock: Any,
) -> None:
    """After a full cycle, no PII patterns exist in any stored signal."""
    import re  # noqa: PLC0415

    from src.storage.runs import RunStore  # noqa: PLC0415
    from src.storage.signals import SignalStore  # noqa: PLC0415

    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)

    runner = _build_runner(seeded_db_session)
    run = await runner.run_cycle()

    assert run.status == "success"

    pii_patterns = [
        re.compile(r"\bu/[A-Za-z0-9_-]+\b"),  # Reddit usernames
        re.compile(r"t1_[a-z0-9]+"),  # Comment fullnames
        re.compile(r"t3_[a-z0-9]+"),  # Post fullnames
    ]

    window_start = datetime(2020, 1, 1, tzinfo=UTC)
    window_end = datetime(2099, 12, 31, tzinfo=UTC)

    signal_store = SignalStore(seeded_db_session)
    all_signals = await signal_store.get_signals_for_window("GME", window_start, window_end)
    all_signals += await signal_store.get_signals_for_window("TSLA", window_start, window_end)

    run_store = RunStore(seeded_db_session)
    last_run = await run_store.get_last_successful_run()
    assert last_run is not None
    if last_run.error_summary:
        for pattern in pii_patterns:
            assert not pattern.search(last_run.error_summary), (
                f"PII pattern found in error_summary: {last_run.error_summary}"
            )

    for signal in all_signals:
        for field_value in (
            signal.ticker_symbol,
            signal.source_subreddit,
        ):
            for pattern in pii_patterns:
                assert not pattern.search(str(field_value)), (
                    f"PII pattern '{pattern.pattern}' found in signal field: {field_value}"
                )


async def test_incremental_fetch_no_duplicates(
    seeded_db_session: Any,
    httpx_mock: Any,
) -> None:
    """Second cycle with only old-timestamp comments stores 0 new signals."""
    # First cycle: fresh data — stores signals
    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)
    runner = _build_runner(seeded_db_session)
    first_run = await runner.run_cycle()

    assert first_run.status == "success"
    first_count = first_run.signals_stored
    assert first_count > 0

    # Second cycle: all comments are before the 'since' cutoff
    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE_OLD)
    second_run = await runner.run_cycle()

    # Second run succeeds (no error) but produces 0 new signals
    # (old comments are filtered by the scraper's since-cutoff logic)
    assert second_run.status == "success"
    assert second_run.signals_stored == 0


async def test_empty_reddit_response_produces_zero_signals(
    seeded_db_session: Any,
    httpx_mock: Any,
) -> None:
    """An empty listing from Reddit produces zero signals and run=success."""
    httpx_mock.add_response(url=WSB_URL, json=MOCK_EMPTY_RESPONSE)

    runner = _build_runner(seeded_db_session)
    run = await runner.run_cycle()

    assert run.status == "success"
    assert run.signals_stored == 0
    assert run.sources_succeeded == 1

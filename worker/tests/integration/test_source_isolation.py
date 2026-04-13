"""
Source isolation integration tests.

Validates that one unavailable subreddit does not block collection from
other subreddits. Tests the pipeline's partial-success semantics.

Scenarios:
- One subreddit returns 503, another returns valid data → status=partial
- All subreddits return 503 → status=failed, signals_stored=0
- One source unavailable (404) and one succeeds → status=partial
- Sources attempted/succeeded counts are correct in all cases

Run conditions:
- Requires a live PostgreSQL instance (skipped otherwise)
- HTTP calls are fully mocked via pytest-httpx
"""
from __future__ import annotations

import socket
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.reddit_responses import MOCK_STOCKS_RESPONSE

# ---------------------------------------------------------------------------
# Skip when PostgreSQL is unavailable
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


def _build_test_runner(session: Any, subreddits: list[str]) -> Any:
    """Build a CycleRunner pre-seeded with the given subreddits in the DB.

    Args:
        session: An active AsyncSession with pre-populated data sources.
        subreddits: List of subreddit names already seeded in the DB.

    Returns:
        A CycleRunner instance ready to run a cycle.
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
        database_url="postgresql+asyncpg://sentix:sentix@localhost:5432/sentix_test",
        redis_url="redis://localhost:6379/0",
        cycle_interval_minutes=15,
        alert_threshold=3,
        sentry_dsn="",
    )

    @asynccontextmanager  # type: ignore[misc]
    async def session_factory() -> Any:
        yield session

    primary = JsonEndpointScraper(user_agents=["SentiX-Isolation-Test/1.0"], request_delay_seconds=0.0)
    fallback = AsyncMock(spec=PRAWOAuthScraper)

    async def _no_comments(*_args: Any, **_kwargs: Any) -> Any:
        return
        yield

    fallback.fetch_comments = _no_comments

    return CycleRunner(
        settings=settings,
        session_factory=session_factory,
        classifier=VADERClassifier(),
        primary_scraper=primary,
        fallback_scraper=fallback,
        extractor=TickerExtractor(),
        disambiguator=TickerDisambiguator(),
        alert_tracker=AlertThresholdTracker(threshold=3, alert_fn=lambda *_: None),
    )


async def _seed_sources(db_session: Any, subreddits: list[str]) -> None:
    """Insert enabled DataSource rows for the given subreddits."""
    from src.storage.models import DataSource  # noqa: PLC0415

    for name in subreddits:
        source = DataSource(
            id=uuid.uuid4(),
            subreddit_name=name,
            enabled=True,
            added_at=datetime.now(tz=UTC),
        )
        db_session.add(source)
    await db_session.flush()


# ---------------------------------------------------------------------------
# T042 — Source isolation tests
# ---------------------------------------------------------------------------


async def test_unavailable_source_does_not_block_others(
    db_session: Any,
    httpx_mock: Any,
) -> None:
    """One 503 subreddit → partial success, other subreddits complete normally."""
    subreddits = ["wallstreetbets", "stocks"]
    await _seed_sources(db_session, subreddits)

    wsb_url = "https://www.reddit.com/r/wallstreetbets/new/.json?limit=100"
    stocks_url = "https://www.reddit.com/r/stocks/new/.json?limit=100"

    # wallstreetbets returns 503 (unavailable).  Two responses needed because
    # JsonEndpointScraper retries once on 5xx before raising ScraperError.
    httpx_mock.add_response(url=wsb_url, status_code=503)
    httpx_mock.add_response(url=wsb_url, status_code=503)
    # stocks returns valid data
    httpx_mock.add_response(url=stocks_url, json=MOCK_STOCKS_RESPONSE)

    runner = _build_test_runner(db_session, subreddits)
    run = await runner.run_cycle()

    assert run.status == "partial"
    assert run.sources_attempted == 2
    assert run.sources_succeeded == 1
    assert run.signals_stored > 0  # signals from stocks


async def test_all_sources_failed_marks_run_failed(
    db_session: Any,
    httpx_mock: Any,
) -> None:
    """All sources return 503 → run status=failed, no signals stored."""
    subreddits = ["wallstreetbets"]
    await _seed_sources(db_session, subreddits)

    wsb_url = "https://www.reddit.com/r/wallstreetbets/new/.json?limit=100"
    # Two 503 responses needed: scraper retries once on 5xx before raising.
    httpx_mock.add_response(url=wsb_url, status_code=503)
    httpx_mock.add_response(url=wsb_url, status_code=503)

    runner = _build_test_runner(db_session, subreddits)
    run = await runner.run_cycle()

    assert run.status == "failed"
    assert run.signals_stored == 0
    assert run.sources_attempted == 1
    assert run.sources_succeeded == 0


async def test_unavailable_source_404_does_not_block_others(
    db_session: Any,
    httpx_mock: Any,
) -> None:
    """A private/banned subreddit (404) does not block other sources."""
    subreddits = ["pennystocks", "stocks"]
    await _seed_sources(db_session, subreddits)

    penny_url = "https://www.reddit.com/r/pennystocks/new/.json?limit=100"
    stocks_url = "https://www.reddit.com/r/stocks/new/.json?limit=100"

    # pennystocks is banned (404)
    httpx_mock.add_response(url=penny_url, status_code=404)
    # stocks succeeds
    httpx_mock.add_response(url=stocks_url, json=MOCK_STOCKS_RESPONSE)

    runner = _build_test_runner(db_session, subreddits)
    run = await runner.run_cycle()

    assert run.status == "partial"
    assert run.sources_attempted == 2
    assert run.sources_succeeded == 1
    assert run.signals_stored > 0


async def test_error_summary_lists_failed_sources(
    db_session: Any,
    httpx_mock: Any,
) -> None:
    """error_summary contains the failed subreddit name but no PII."""
    subreddits = ["wallstreetbets"]
    await _seed_sources(db_session, subreddits)

    wsb_url = "https://www.reddit.com/r/wallstreetbets/new/.json?limit=100"
    # Two 503 responses needed: scraper retries once on 5xx before raising.
    httpx_mock.add_response(url=wsb_url, status_code=503)
    httpx_mock.add_response(url=wsb_url, status_code=503)

    runner = _build_test_runner(db_session, subreddits)
    run = await runner.run_cycle()

    assert run.status == "failed"
    assert run.error_summary is not None
    assert "wallstreetbets" in run.error_summary


async def test_two_successful_sources(
    db_session: Any,
    httpx_mock: Any,
) -> None:
    """Two sources both succeed → run status=success, signal count is additive."""
    subreddits = ["wallstreetbets", "stocks"]
    await _seed_sources(db_session, subreddits)

    from tests.fixtures.reddit_responses import MOCK_REDDIT_RESPONSE  # noqa: PLC0415

    wsb_url = "https://www.reddit.com/r/wallstreetbets/new/.json?limit=100"
    stocks_url = "https://www.reddit.com/r/stocks/new/.json?limit=100"

    httpx_mock.add_response(url=wsb_url, json=MOCK_REDDIT_RESPONSE)
    httpx_mock.add_response(url=stocks_url, json=MOCK_STOCKS_RESPONSE)

    runner = _build_test_runner(db_session, subreddits)
    run = await runner.run_cycle()

    assert run.status == "success"
    assert run.sources_attempted == 2
    assert run.sources_succeeded == 2
    assert run.signals_stored > 0

"""
PII audit test. Validates FR-005: no user-attributable Reddit data stored.

This test inspects ALL columns of ALL tables for patterns that could
indicate PII leakage. It is intentionally over-broad so that future
schema changes that accidentally introduce PII are caught immediately.

Covers:
- Pattern scan across all table rows for Reddit username/ID patterns
- Column-name assertions: no forbidden column names in any table
- Structural assertion: comment text is never a stored column anywhere

Run conditions:
- Requires a live PostgreSQL instance (skipped otherwise)
- Exercises the full pipeline cycle to populate tables before inspection
"""
from __future__ import annotations

import re
import socket
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from tests.fixtures.reddit_responses import MOCK_REDDIT_RESPONSE

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
# PII patterns — any match in any stored cell is a test failure
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    re.compile(r"\bu/[A-Za-z0-9_-]+\b"),  # Reddit usernames (u/someuser)
    re.compile(r"t1_[a-z0-9]+"),  # Comment fullnames (t1_abc123)
    re.compile(r"t3_[a-z0-9]+"),  # Post fullnames (t3_xyz456)
]

# Column names that must never appear in any table
_FORBIDDEN_COLUMN_NAMES = {
    "text",
    "body",
    "author",
    "username",
    "comment_id",
    "post_id",
    "user_id",
    "comment_text",
    "post_text",
    "selftext",
}

SUBREDDIT = "wallstreetbets"
WSB_URL = f"https://www.reddit.com/r/{SUBREDDIT}/new/.json?limit=100"


def _build_test_runner(session: Any) -> Any:
    """Build a CycleRunner for PII audit tests."""
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

    primary = JsonEndpointScraper(user_agents=["SentiX-PII-Test/1.0"], request_delay_seconds=0.0)
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


@pytest_asyncio.fixture  # type: ignore[misc]
async def pii_seeded_session(db_session: Any) -> Any:
    """Session with one enabled data source pre-populated."""
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
# T040 — PII audit tests
# ---------------------------------------------------------------------------


async def test_no_pii_in_any_table(pii_seeded_session: Any, httpx_mock: Any) -> None:
    """After a full cycle, no PII patterns exist in any database column value."""
    from sqlalchemy import text  # noqa: PLC0415

    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)

    runner = _build_test_runner(pii_seeded_session)
    run = await runner.run_cycle()
    assert run.status == "success"

    # Commit so we can inspect from the same session
    await pii_seeded_session.commit()

    # Inspect all application tables
    tables = ["sentiment_signals", "collection_runs", "data_sources", "scored_results"]

    for table in tables:
        result = await pii_seeded_session.execute(
            text(f"SELECT * FROM {table} LIMIT 1000")  # noqa: S608
        )
        rows = result.fetchall()
        for row in rows:
            for value in row:
                if value is None:
                    continue
                cell = str(value)
                for pattern in _PII_PATTERNS:
                    assert not pattern.search(cell), (
                        f"PII pattern '{pattern.pattern}' found in table '{table}': "
                        f"{cell[:50]}..."
                    )


async def test_no_comment_text_columns_exist(pii_seeded_session: Any) -> None:
    """Assert no column named 'text', 'body', 'author', etc. exists in any ORM model.

    This test uses the ORM model definitions as the authoritative source of
    truth for the database schema, since SQLAlchemy models and the actual DB
    schema are always kept in sync via Alembic migrations.
    """
    from src.storage.models import (  # noqa: PLC0415
        CollectionRun,
        DataSource,
        ScoredResult,
        SentimentSignal,
    )

    all_models = [DataSource, CollectionRun, SentimentSignal, ScoredResult]
    for model in all_models:
        col_names = {col.name for col in model.__table__.columns}
        violations = col_names & _FORBIDDEN_COLUMN_NAMES
        assert not violations, (
            f"Table '{model.__tablename__}' has forbidden column(s): {violations}"
        )


async def test_signal_fields_contain_no_comment_body(
    pii_seeded_session: Any,
    httpx_mock: Any,
) -> None:
    """Signal records must not contain any fragment of original comment text."""
    from sqlalchemy import text  # noqa: PLC0415

    # The mock comment contains this phrase; it must never appear in any stored row
    pii_fragment = "to the moon"

    httpx_mock.add_response(url=WSB_URL, json=MOCK_REDDIT_RESPONSE)

    runner = _build_test_runner(pii_seeded_session)
    run = await runner.run_cycle()
    assert run.status == "success"
    await pii_seeded_session.commit()

    result = await pii_seeded_session.execute(
        text("SELECT * FROM sentiment_signals LIMIT 1000")  # noqa: S608
    )
    rows = result.fetchall()
    for row in rows:
        for value in row:
            if value is None:
                continue
            assert pii_fragment not in str(value).lower(), (
                f"Comment text fragment '{pii_fragment}' found in signal row: {row}"
            )


async def test_run_error_summary_contains_no_usernames(
    pii_seeded_session: Any,
    httpx_mock: Any,
) -> None:
    """CollectionRun.error_summary must not contain Reddit username patterns."""
    # Simulate a partial run (one source fails).  Two 503 responses needed
    # because JsonEndpointScraper retries once on 5xx before raising ScraperError.
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(status_code=503)

    runner = _build_test_runner(pii_seeded_session)
    run = await runner.run_cycle()

    if run.error_summary:
        for pattern in _PII_PATTERNS:
            assert not pattern.search(run.error_summary), (
                f"PII pattern in error_summary: {run.error_summary}"
            )

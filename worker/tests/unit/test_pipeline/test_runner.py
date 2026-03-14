"""
Unit tests for CycleRunner.

All external dependencies (scraper, classifier, extractor, disambiguator,
stores) are mocked so no real database or HTTP calls are made.

Test matrix:
- Successful cycle: status='success', correct signal count
- One source fails with ScraperUnavailableError: status='partial'
- One source fails with generic exception: status='partial'
- All sources fail: status='failed'
- Neutral comments (discarded=True) produce no signals
- ScraperRateLimitError increments consecutive_rate_limits counter
- Lane switches to fallback after 3 consecutive rate-limit errors
- comment.text never appears in any stored signal dict (PII guarantee)
- error_summary contains subreddit names, not usernames
- Empty sources list: status='success', 0 signals
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.classifiers.base import ClassificationResult
from src.config import Settings
from src.pipeline.runner import _RATE_LIMIT_THRESHOLD, CycleRunner
from src.scrapers.base import RawComment, ScraperRateLimitError, ScraperUnavailableError
from src.storage.models import CollectionRun, DataSource
from src.tickers.extractor import ExtractedTicker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    """Create a Settings instance with safe test defaults."""
    return Settings(
        database_url="postgresql+asyncpg://sse:sse@localhost/sse_test",
        redis_url="redis://localhost:6379/0",
        cycle_interval_minutes=15,
        alert_threshold=3,
        sentry_dsn="",
        log_level="DEBUG",
        **overrides,
    )


def _make_source(name: str) -> DataSource:
    """Create a DataSource with the given subreddit name."""
    src = DataSource(subreddit_name=name)
    src.id = uuid.uuid4()
    return src


def _make_run() -> CollectionRun:
    """Create a CollectionRun with a stable ID."""
    run = CollectionRun(status="failed")
    run.id = uuid.uuid4()
    run.started_at = datetime.now(tz=UTC)
    return run


def _make_comment(text: str = "GME to the moon", upvotes: int = 10) -> RawComment:
    """Create a RawComment."""
    return RawComment(
        text=text,
        upvotes=upvotes,
        created_utc=datetime.now(tz=UTC),
    )


async def _async_gen(*items: RawComment):
    """Async generator that yields the given items."""
    for item in items:
        yield item


async def _async_gen_empty():
    """Async generator that yields nothing."""
    return
    yield  # make it an async generator


def _build_runner(
    settings: Settings | None = None,
    primary_scraper: Any = None,
    fallback_scraper: Any = None,
    classifier: Any = None,
    extractor: Any = None,
    disambiguator: Any = None,
    run_store: Any = None,
    signal_store: Any = None,
    source_store: Any = None,
) -> tuple[CycleRunner, Any]:
    """
    Build a CycleRunner with all dependencies mocked.

    Returns the runner and the mock session factory callable.
    """
    if settings is None:
        settings = _make_settings()

    # Default mock stores
    if run_store is None:
        run_store = AsyncMock()
        run_store.create_run.return_value = _make_run()
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

    if signal_store is None:
        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

    if source_store is None:
        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

    if primary_scraper is None:
        primary_scraper = MagicMock()
        primary_scraper.fetch_comments.return_value = _async_gen_empty()
        primary_scraper.is_available.return_value = True

    if fallback_scraper is None:
        fallback_scraper = MagicMock()
        fallback_scraper.fetch_comments.return_value = _async_gen_empty()
        fallback_scraper.is_available.return_value = True

    if classifier is None:
        classifier = MagicMock()
        classifier.classify.return_value = ClassificationResult(
            polarity=1, confidence=0.8, discarded=False
        )

    if extractor is None:
        extractor = MagicMock()
        extractor.extract.return_value = [ExtractedTicker(symbol="GME", explicit=True)]

    if disambiguator is None:
        disambiguator = MagicMock()
        disambiguator.filter.return_value = ["GME"]

    # Build mock session context manager
    mock_session = AsyncMock()
    mock_session.flush.return_value = None
    mock_session.commit.return_value = None

    # Patch store classes so the runner uses our mocks
    with (
        patch("src.pipeline.runner.RunStore", return_value=run_store),
        patch("src.pipeline.runner.SignalStore", return_value=signal_store),
        patch("src.pipeline.runner.SourceStore", return_value=source_store),
    ):
        pass  # just to verify patches work

    # Build session factory as an async context manager
    @asynccontextmanager
    async def session_factory():
        yield mock_session

    runner = CycleRunner(
        settings=settings,
        session_factory=session_factory,
        classifier=classifier,
        primary_scraper=primary_scraper,
        fallback_scraper=fallback_scraper,
        extractor=extractor,
        disambiguator=disambiguator,
    )

    return runner, mock_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCycleRunnerSuccess:
    """Tests for the happy path — all sources succeed."""

    @pytest.mark.asyncio
    async def test_successful_cycle_returns_run(self) -> None:
        """run_cycle() returns a CollectionRun on success."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("wallstreetbets")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 1

        comment = _make_comment()
        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.return_value = _async_gen(comment)

        extractor = MagicMock()
        extractor.extract.return_value = [ExtractedTicker(symbol="GME", explicit=True)]

        disambiguator = MagicMock()
        disambiguator.filter.return_value = ["GME"]

        classifier = MagicMock()
        classifier.classify.return_value = ClassificationResult(
            polarity=1, confidence=0.9, discarded=False
        )

        with (
            patch("src.pipeline.runner.RunStore", return_value=run_store),
            patch("src.pipeline.runner.SignalStore", return_value=signal_store),
            patch("src.pipeline.runner.SourceStore", return_value=source_store),
        ):
            runner, _ = _build_runner(
                primary_scraper=primary_scraper,
                fallback_scraper=MagicMock(),
                classifier=classifier,
                extractor=extractor,
                disambiguator=disambiguator,
            )
            # Re-wire stores directly via patches around actual call
            runner._extractor = extractor
            runner._disambiguator = disambiguator
            runner._classifier = classifier
            runner._primary_scraper = primary_scraper
            runner._fallback_scraper = MagicMock()

            @asynccontextmanager
            async def sf():
                session = AsyncMock()
                session.flush.return_value = None
                session.commit.return_value = None
                with (
                    patch("src.pipeline.runner.RunStore", return_value=run_store),
                    patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                    patch("src.pipeline.runner.SourceStore", return_value=source_store),
                ):
                    yield session

            runner._session_factory = sf

            result = await runner.run_cycle()

        assert result is run

    @pytest.mark.asyncio
    async def test_successful_cycle_status_is_success(self) -> None:
        """update_run_status is called with 'success' when all sources succeed."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("wallstreetbets")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 2

        comment = _make_comment()
        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.return_value = _async_gen(comment)

        extractor = MagicMock()
        extractor.extract.return_value = [ExtractedTicker(symbol="TSLA", explicit=False)]
        disambiguator = MagicMock()
        disambiguator.filter.return_value = ["TSLA"]
        classifier = MagicMock()
        classifier.classify.return_value = ClassificationResult(
            polarity=-1, confidence=0.7, discarded=False
        )

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=classifier,
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=extractor,
            disambiguator=disambiguator,
        )

        await runner.run_cycle()

        run_store.update_run_status.assert_called_once()
        call_kwargs = run_store.update_run_status.call_args
        assert call_kwargs.kwargs["status"] == "success"
        assert call_kwargs.kwargs["sources_attempted"] == 1
        assert call_kwargs.kwargs["sources_succeeded"] == 1

    @pytest.mark.asyncio
    async def test_neutral_comment_discarded_no_signal(self) -> None:
        """Neutral comments (discarded=True) produce no signals."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("stocks")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        comment = _make_comment(text="I love this stock")
        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.return_value = _async_gen(comment)

        extractor = MagicMock()
        extractor.extract.return_value = [ExtractedTicker(symbol="GME", explicit=True)]
        disambiguator = MagicMock()
        disambiguator.filter.return_value = ["GME"]
        # Classifier marks as neutral/discarded
        classifier = MagicMock()
        classifier.classify.return_value = ClassificationResult(
            polarity=0, confidence=0.01, discarded=True
        )

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=classifier,
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=extractor,
            disambiguator=disambiguator,
        )

        await runner.run_cycle()

        # bulk_insert_signals must have been called with an empty list
        call_args = signal_store.bulk_insert_signals.call_args
        signals_passed = call_args[0][0]
        assert signals_passed == []

    @pytest.mark.asyncio
    async def test_signal_dict_does_not_contain_comment_text(self) -> None:
        """PII guarantee: comment.text never appears in any stored signal dict."""
        secret_text = "NEVER_STORE_THIS_TEXT_IN_DB"  # noqa: S105
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("investing")]

        captured_signals: list[Any] = []

        async def capture_signals(signals: list[Any]) -> int:
            captured_signals.extend(signals)
            return len(signals)

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.side_effect = capture_signals

        comment = _make_comment(text=secret_text)
        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.return_value = _async_gen(comment)

        extractor = MagicMock()
        extractor.extract.return_value = [ExtractedTicker(symbol="AAPL", explicit=True)]
        disambiguator = MagicMock()
        disambiguator.filter.return_value = ["AAPL"]
        classifier = MagicMock()
        classifier.classify.return_value = ClassificationResult(
            polarity=1, confidence=0.9, discarded=False
        )

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=classifier,
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=extractor,
            disambiguator=disambiguator,
        )

        await runner.run_cycle()

        assert len(captured_signals) == 1
        signal = captured_signals[0]
        # The signal dict must not contain the comment text
        for _key, value in signal.items():
            assert secret_text not in str(value), (
                f"PII leak detected: comment text found in signal[{_key!r}]"
            )

    @pytest.mark.asyncio
    async def test_empty_sources_returns_success(self) -> None:
        """Zero active sources -> status='success', 0 signals."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=MagicMock(),
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )

        await runner.run_cycle()

        call_kwargs = run_store.update_run_status.call_args.kwargs
        assert call_kwargs["status"] == "success"
        assert call_kwargs["sources_attempted"] == 0
        assert call_kwargs["sources_succeeded"] == 0
        assert call_kwargs["signals_stored"] == 0


class TestCycleRunnerSourceIsolation:
    """Tests for per-source failure isolation."""

    @pytest.mark.asyncio
    async def test_one_source_unavailable_partial_success(self) -> None:
        """One ScraperUnavailableError -> status='partial', other sources still run."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_ok = _make_source("stocks")
        source_bad = _make_source("banned_sub")

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [source_bad, source_ok]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 1

        comment = _make_comment()

        call_count = 0

        async def scraper_fetch(subreddit: str, since: datetime, limit: int = 500):
            nonlocal call_count
            call_count += 1
            if subreddit == "banned_sub":
                raise ScraperUnavailableError("Subreddit is private.")
            yield comment

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = scraper_fetch

        extractor = MagicMock()
        extractor.extract.return_value = [ExtractedTicker(symbol="MSFT", explicit=True)]
        disambiguator = MagicMock()
        disambiguator.filter.return_value = ["MSFT"]
        classifier = MagicMock()
        classifier.classify.return_value = ClassificationResult(
            polarity=1, confidence=0.8, discarded=False
        )

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=classifier,
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=extractor,
            disambiguator=disambiguator,
        )

        await runner.run_cycle()

        call_kwargs = run_store.update_run_status.call_args.kwargs
        assert call_kwargs["status"] == "partial"
        assert call_kwargs["sources_attempted"] == 2
        assert call_kwargs["sources_succeeded"] == 1
        assert call_kwargs["error_summary"] is not None

    @pytest.mark.asyncio
    async def test_one_source_generic_exception_partial(self) -> None:
        """A generic exception on one source -> status='partial'."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_good = _make_source("investing")
        source_bad = _make_source("broken_sub")

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [source_bad, source_good]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        comment = _make_comment()

        async def scraper_fetch(subreddit: str, since: datetime, limit: int = 500):
            if subreddit == "broken_sub":
                raise RuntimeError("Unexpected network failure")
            yield comment

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = scraper_fetch

        extractor = MagicMock()
        extractor.extract.return_value = []
        disambiguator = MagicMock()
        disambiguator.filter.return_value = []

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=extractor,
            disambiguator=disambiguator,
        )

        await runner.run_cycle()

        call_kwargs = run_store.update_run_status.call_args.kwargs
        assert call_kwargs["status"] == "partial"

    @pytest.mark.asyncio
    async def test_all_sources_fail_status_failed(self) -> None:
        """All sources failing -> status='failed'."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [
            _make_source("sub1"),
            _make_source("sub2"),
        ]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def always_fail(subreddit: str, since: datetime, limit: int = 500):
            raise ScraperUnavailableError("Banned")
            yield  # make it an async generator

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = always_fail

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )

        await runner.run_cycle()

        call_kwargs = run_store.update_run_status.call_args.kwargs
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["sources_succeeded"] == 0

    @pytest.mark.asyncio
    async def test_error_summary_contains_subreddit_names_only(self) -> None:
        """error_summary lists failed subreddit names, not usernames or PII."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("wsb_private")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def fail_fetch(subreddit: str, since: datetime, limit: int = 500):
            raise ScraperUnavailableError("private")
            yield

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = fail_fetch

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )

        await runner.run_cycle()

        call_kwargs = run_store.update_run_status.call_args.kwargs
        assert call_kwargs["error_summary"] is not None
        # Must contain the subreddit name
        assert "wsb_private" in call_kwargs["error_summary"]


class TestCycleRunnerIncrementalScraping:
    """Tests for incremental scraping (since timestamp)."""

    @pytest.mark.asyncio
    async def test_first_run_uses_one_hour_fallback(self) -> None:
        """When no previous successful run, 'since' defaults to now - 1 hour."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None  # No previous run
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("stocks")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        captured_since: list[datetime] = []

        async def capture_since(subreddit: str, since: datetime, limit: int = 500):
            captured_since.append(since)
            return
            yield

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = capture_since

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        before = datetime.now(tz=UTC)

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )
        runner._extractor.extract.return_value = []
        runner._disambiguator.filter.return_value = []

        await runner.run_cycle()

        assert len(captured_since) == 1
        since = captured_since[0]
        # Should be roughly 1 hour ago
        expected = before - timedelta(hours=1)
        diff = abs((since - expected).total_seconds())
        assert diff < 5, f"Expected since ~1h ago, got {since!r}"

    @pytest.mark.asyncio
    async def test_subsequent_run_uses_last_run_timestamp(self) -> None:
        """When a previous successful run exists, 'since' equals its started_at."""
        prev_run = _make_run()
        prev_run.started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = prev_run
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("investing")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        captured_since: list[datetime] = []

        async def capture_since(subreddit: str, since: datetime, limit: int = 500):
            captured_since.append(since)
            return
            yield

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = capture_since

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )
        runner._extractor.extract.return_value = []
        runner._disambiguator.filter.return_value = []

        await runner.run_cycle()

        assert len(captured_since) == 1
        assert captured_since[0] == prev_run.started_at


class TestCycleRunnerLaneSwitching:
    """Tests for dual-lane scraper switching."""

    @pytest.mark.asyncio
    async def test_rate_limit_increments_counter(self) -> None:
        """ScraperRateLimitError increments consecutive_rate_limits."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("stocks")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def rate_limited(subreddit: str, since: datetime, limit: int = 500):
            raise ScraperRateLimitError(retry_after_seconds=60)
            yield

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = rate_limited

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )

        assert runner._consecutive_rate_limits == 0
        await runner.run_cycle()
        assert runner._consecutive_rate_limits == 1

    @pytest.mark.asyncio
    async def test_primary_scraper_used_below_threshold(self) -> None:
        """Primary scraper is used when consecutive_rate_limits < threshold."""
        runner, _ = _build_runner()
        runner._consecutive_rate_limits = _RATE_LIMIT_THRESHOLD - 1
        assert runner._active_scraper is runner._primary_scraper

    @pytest.mark.asyncio
    async def test_fallback_scraper_used_at_threshold(self) -> None:
        """Fallback scraper is used when consecutive_rate_limits >= threshold."""
        runner, _ = _build_runner()
        runner._consecutive_rate_limits = _RATE_LIMIT_THRESHOLD
        assert runner._active_scraper is runner._fallback_scraper

    @pytest.mark.asyncio
    async def test_successful_scrape_resets_rate_limit_counter(self) -> None:
        """A successful scrape resets the consecutive rate-limit counter."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("investing")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def ok_fetch(subreddit: str, since: datetime, limit: int = 500):
            return
            yield

        primary_scraper = MagicMock()
        primary_scraper.is_available.return_value = True
        primary_scraper.fetch_comments.side_effect = ok_fetch

        @asynccontextmanager
        async def sf():
            session = AsyncMock()
            session.flush.return_value = None
            session.commit.return_value = None
            with (
                patch("src.pipeline.runner.RunStore", return_value=run_store),
                patch("src.pipeline.runner.SignalStore", return_value=signal_store),
                patch("src.pipeline.runner.SourceStore", return_value=source_store),
            ):
                yield session

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=sf,
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )
        runner._extractor.extract.return_value = []
        runner._disambiguator.filter.return_value = []
        runner._consecutive_rate_limits = 2  # Previously had some failures

        await runner.run_cycle()

        assert runner._consecutive_rate_limits == 0

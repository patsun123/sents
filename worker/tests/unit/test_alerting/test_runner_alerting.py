"""
Unit tests for WP07 alerting integrations in CycleRunner:
- AlertThresholdTracker is called on success and failure
- Health file is written after success/partial cycles
- Fallback scraper lane-switch log is emitted
- Cycle duration warning is emitted when cycle runs long

All dependencies are mocked — no database or network access.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.alerting.threshold import AlertThresholdTracker
from src.config import Settings
from src.pipeline.runner import _RATE_LIMIT_THRESHOLD, CycleRunner
from src.scrapers.base import RawComment, ScraperUnavailableError
from src.storage.models import CollectionRun, DataSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://sentix:sentix@localhost/sentix_test",
        "redis_url": "redis://localhost:6379/0",
        "cycle_interval_minutes": 15,
        "alert_threshold": 3,
        "sentry_dsn": "",
        "log_level": "DEBUG",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_run() -> CollectionRun:
    run = CollectionRun(status="failed")
    run.id = uuid.uuid4()
    run.started_at = datetime.now(tz=UTC)
    return run


def _make_source(name: str) -> DataSource:
    src = DataSource(subreddit_name=name)
    src.id = uuid.uuid4()
    return src


def _make_comment(text: str = "GME to the moon", upvotes: int = 10) -> RawComment:
    return RawComment(text=text, upvotes=upvotes, created_utc=datetime.now(tz=UTC))


async def _async_gen_empty():  # type: ignore[return]
    return
    yield  # make it an async generator


async def _async_gen(*items: RawComment):  # type: ignore[return]
    for item in items:
        yield item


def _build_session_factory(
    run_store: Any, signal_store: Any, source_store: Any
) -> Any:
    """Return an async context manager session factory with mocked stores."""

    @asynccontextmanager
    async def sf():  # type: ignore[return]
        session = AsyncMock()
        session.flush.return_value = None
        session.commit.return_value = None
        with (
            patch("src.pipeline.runner.RunStore", return_value=run_store),
            patch("src.pipeline.runner.SignalStore", return_value=signal_store),
            patch("src.pipeline.runner.SourceStore", return_value=source_store),
        ):
            yield session

    return sf


# ---------------------------------------------------------------------------
# Tests: AlertThresholdTracker integration in CycleRunner
# ---------------------------------------------------------------------------


class TestCycleRunnerAlertTrackerIntegration:
    """Tests that CycleRunner correctly calls AlertThresholdTracker."""

    @pytest.mark.asyncio
    async def test_tracker_record_success_called_on_success_cycle(self) -> None:
        """AlertThresholdTracker.record_success() is called after a success cycle."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        tracker = MagicMock(spec=AlertThresholdTracker)

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=_build_session_factory(run_store, signal_store, source_store),
            classifier=MagicMock(),
            primary_scraper=MagicMock(),
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
            alert_tracker=tracker,
        )

        await runner.run_cycle()

        tracker.record_success.assert_called_once()
        tracker.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracker_record_failure_called_on_failed_cycle(self) -> None:
        """AlertThresholdTracker.record_failure() is called after a failed cycle."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("broken_sub")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def fail_fetch(subreddit: str, since: datetime, limit: int = 500):  # type: ignore[return]
            raise ScraperUnavailableError("private")
            yield

        primary_scraper = MagicMock()
        primary_scraper.fetch_comments.side_effect = fail_fetch

        tracker = MagicMock(spec=AlertThresholdTracker)

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=_build_session_factory(run_store, signal_store, source_store),
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
            alert_tracker=tracker,
        )

        await runner.run_cycle()

        tracker.record_failure.assert_called_once()
        tracker.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_tracker_record_success_called_on_partial_cycle(self) -> None:
        """AlertThresholdTracker.record_success() is called even on partial cycles."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [
            _make_source("good_sub"),
            _make_source("bad_sub"),
        ]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def selective_fetch(subreddit: str, since: datetime, limit: int = 500):  # type: ignore[return]
            if subreddit == "bad_sub":
                raise ScraperUnavailableError("banned")
            return
            yield

        primary_scraper = MagicMock()
        primary_scraper.fetch_comments.side_effect = selective_fetch

        tracker = MagicMock(spec=AlertThresholdTracker)

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=_build_session_factory(run_store, signal_store, source_store),
            classifier=MagicMock(),
            primary_scraper=primary_scraper,
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
            alert_tracker=tracker,
        )
        runner._extractor.extract.return_value = []
        runner._disambiguator.filter.return_value = []

        await runner.run_cycle()

        # partial cycle -> record_success (not a hard failure)
        tracker.record_success.assert_called_once()
        tracker.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_tracker_does_not_crash(self) -> None:
        """CycleRunner works fine with alert_tracker=None (default)."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=_build_session_factory(run_store, signal_store, source_store),
            classifier=MagicMock(),
            primary_scraper=MagicMock(),
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
            alert_tracker=None,
        )

        # Must not raise
        await runner.run_cycle()


# ---------------------------------------------------------------------------
# Tests: Health file written on success/partial
# ---------------------------------------------------------------------------


class TestCycleRunnerHealthFile:
    """Tests that the .health file is written on non-failed cycles."""

    @pytest.mark.asyncio
    async def test_health_file_written_on_success(self, tmp_path: Path) -> None:
        """_HEALTH_FILE.write_text is called when status='success'."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        # Patch _HEALTH_FILE to write to a temp path instead of cwd
        health_path = tmp_path / ".health"
        with patch("src.pipeline.runner._HEALTH_FILE", health_path):
            runner = CycleRunner(
                settings=_make_settings(),
                session_factory=_build_session_factory(run_store, signal_store, source_store),
                classifier=MagicMock(),
                primary_scraper=MagicMock(),
                fallback_scraper=MagicMock(),
                extractor=MagicMock(),
                disambiguator=MagicMock(),
            )
            await runner.run_cycle()

        assert health_path.exists(), ".health file must be written after a successful cycle"
        content = health_path.read_text()
        # Content should be a parseable ISO timestamp
        assert len(content) > 10

    @pytest.mark.asyncio
    async def test_health_file_not_written_on_failed_cycle(self, tmp_path: Path) -> None:
        """_HEALTH_FILE is NOT written when status='failed'."""
        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = [_make_source("broken")]

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        async def always_fail(subreddit: str, since: datetime, limit: int = 500):  # type: ignore[return]
            raise ScraperUnavailableError("banned")
            yield

        primary_scraper = MagicMock()
        primary_scraper.fetch_comments.side_effect = always_fail

        health_path = tmp_path / ".health"
        with patch("src.pipeline.runner._HEALTH_FILE", health_path):
            runner = CycleRunner(
                settings=_make_settings(),
                session_factory=_build_session_factory(run_store, signal_store, source_store),
                classifier=MagicMock(),
                primary_scraper=primary_scraper,
                fallback_scraper=MagicMock(),
                extractor=MagicMock(),
                disambiguator=MagicMock(),
            )
            await runner.run_cycle()

        assert not health_path.exists(), ".health must NOT be written after a failed cycle"


# ---------------------------------------------------------------------------
# Tests: Fallback lane-switch log message (line 132)
# ---------------------------------------------------------------------------


class TestCycleRunnerFallbackLaneLog:
    """Tests that fallback scraper activation is logged."""

    @pytest.mark.asyncio
    async def test_fallback_lane_log_emitted_when_switched(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When fallback scraper is active, a lane-switch log is emitted."""
        import logging  # noqa: PLC0415

        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        runner = CycleRunner(
            settings=_make_settings(),
            session_factory=_build_session_factory(run_store, signal_store, source_store),
            classifier=MagicMock(),
            primary_scraper=MagicMock(),
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )
        # Force fallback lane active
        runner._consecutive_rate_limits = _RATE_LIMIT_THRESHOLD

        with caplog.at_level(logging.INFO, logger="src.pipeline.runner"):
            await runner.run_cycle()

        assert any(
            "lane=fallback" in record.message or "fallback" in record.message
            for record in caplog.records
        ), "Expected a fallback lane log message"


# ---------------------------------------------------------------------------
# Tests: Cycle duration warning (line 227)
# ---------------------------------------------------------------------------


class TestCycleRunnerDurationWarning:
    """Tests that a warning is emitted when a cycle runs too long."""

    @pytest.mark.asyncio
    async def test_duration_warning_emitted_for_slow_cycle(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warning is logged when the cycle duration exceeds the threshold."""
        import logging  # noqa: PLC0415

        run = _make_run()
        run_store = AsyncMock()
        run_store.create_run.return_value = run
        run_store.get_last_successful_run.return_value = None
        run_store.update_run_status.return_value = None

        source_store = AsyncMock()
        source_store.get_active_sources.return_value = []

        signal_store = AsyncMock()
        signal_store.bulk_insert_signals.return_value = 0

        # Use a very short cycle interval (1 minute) so any test duration exceeds 80%
        settings = _make_settings(cycle_interval_minutes=1)

        runner = CycleRunner(
            settings=settings,
            session_factory=_build_session_factory(run_store, signal_store, source_store),
            classifier=MagicMock(),
            primary_scraper=MagicMock(),
            fallback_scraper=MagicMock(),
            extractor=MagicMock(),
            disambiguator=MagicMock(),
        )

        # Patch datetime.now to simulate a slow cycle by returning a far-future time
        # on the second call (the elapsed time check).
        import src.pipeline.runner as runner_module  # noqa: PLC0415

        original_now = datetime.now

        call_count = 0

        def fake_now(tz=None):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            real_now = original_now(tz=tz)
            if call_count > 1:
                # Simulate 60 seconds elapsed (exceeds 80% of 1-minute interval = 48s)
                from datetime import timedelta  # noqa: PLC0415

                return real_now + timedelta(seconds=60)
            return real_now

        with (
            patch.object(runner_module, "datetime", wraps=datetime) as mock_dt,
            caplog.at_level(logging.WARNING, logger="src.pipeline.runner"),
        ):
            mock_dt.now.side_effect = fake_now
            await runner.run_cycle()

        assert any(
            "cycle_duration_exceeded" in record.message or "elapsed" in record.message
            for record in caplog.records
        ), "Expected a cycle_duration_exceeded warning message"

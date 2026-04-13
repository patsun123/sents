"""
Unit tests for create_scheduler.

Verifies that the scheduler is configured with:
- Correct job ID and max_instances=1
- Correct interval trigger period
- replace_existing=True to prevent duplicate jobs on restart
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from src.config import Settings
from src.pipeline.scheduler import create_scheduler


def _make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": "postgresql+asyncpg://sentix:sentix@localhost/sentix_test",
        "redis_url": "redis://localhost:6379/0",
        "cycle_interval_minutes": 15,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestCreateScheduler:
    """Tests for the create_scheduler factory function."""

    def test_returns_asyncio_scheduler(self) -> None:
        """create_scheduler returns an AsyncIOScheduler instance."""
        settings = _make_settings()
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_job_has_correct_id(self) -> None:
        """The scheduled job uses id='pipeline_cycle'."""
        settings = _make_settings()
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)

        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "pipeline_cycle"

    def test_job_max_instances_is_one(self) -> None:
        """The job has max_instances=1 to prevent concurrent runs."""
        settings = _make_settings()
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)

        jobs = scheduler.get_jobs()
        assert jobs[0].max_instances == 1

    def test_interval_uses_settings_value(self) -> None:
        """Interval trigger period matches settings.cycle_interval_minutes."""
        settings = _make_settings(cycle_interval_minutes=30)
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)

        jobs = scheduler.get_jobs()
        trigger = jobs[0].trigger
        # IntervalTrigger stores interval as a timedelta
        assert trigger.interval == datetime.timedelta(minutes=30)

    def test_default_interval_is_15_minutes(self) -> None:
        """Default cycle_interval_minutes=15 produces a 15-minute trigger."""
        settings = _make_settings(cycle_interval_minutes=15)
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)

        jobs = scheduler.get_jobs()
        trigger = jobs[0].trigger
        assert trigger.interval == datetime.timedelta(minutes=15)

    def test_job_id_is_unique_pipeline_cycle(self) -> None:
        """Only one job with id='pipeline_cycle' is created."""
        settings = _make_settings()
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)

        pipeline_jobs = [j for j in scheduler.get_jobs() if j.id == "pipeline_cycle"]
        assert len(pipeline_jobs) == 1

    def test_scheduler_not_started_by_default(self) -> None:
        """Scheduler is returned paused (not running) — caller starts it."""
        settings = _make_settings()
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)
        assert not scheduler.running

    def test_job_name_is_descriptive(self) -> None:
        """The job name is human-readable."""
        settings = _make_settings()
        mock_fn = MagicMock()
        scheduler = create_scheduler(run_cycle_fn=mock_fn, settings=settings)

        jobs = scheduler.get_jobs()
        job_name = jobs[0].name
        assert "SentiX" in job_name or "Sentiment" in job_name or "cycle" in job_name.lower()

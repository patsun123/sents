"""
Scheduler: APScheduler-backed 15-minute cycle trigger.

Uses AsyncIOScheduler with PostgreSQL job store for restart persistence.
max_instances=1 prevents APScheduler from launching concurrent jobs.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import Settings

logger = logging.getLogger(__name__)


def create_scheduler(
    run_cycle_fn: Callable[[], Coroutine[Any, Any, Any]],
    settings: Settings,
) -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance.

    The scheduler persists job state to PostgreSQL so that restarting the
    container does not create duplicate jobs or miss scheduled intervals.
    ``max_instances=1`` is set at the APScheduler level as an additional
    concurrency guard on top of ``CycleQueue``'s asyncio lock.

    Args:
        run_cycle_fn: Async callable to invoke each interval.  Typically
            a wrapper that calls ``CycleQueue.submit(CycleRunner.run_cycle())``.
        settings: Worker settings (cycle_interval_minutes, database_url).

    Returns:
        Configured :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler`
        (not yet started — call ``.start()`` to activate).
    """
    # APScheduler uses its own sync SQLAlchemy connection; strip asyncpg driver
    sync_db_url = settings.database_url.replace("+asyncpg", "")

    jobstores = {"default": SQLAlchemyJobStore(url=sync_db_url)}

    scheduler = AsyncIOScheduler(jobstores=jobstores)
    scheduler.add_job(
        run_cycle_fn,
        trigger=IntervalTrigger(minutes=settings.cycle_interval_minutes),
        id="pipeline_cycle",
        name="SSE Sentiment Collection Cycle",
        replace_existing=True,
        max_instances=1,  # APScheduler-level concurrency guard
    )

    logger.info(
        "Scheduler configured: interval=%d minutes, jobstore=postgresql",
        settings.cycle_interval_minutes,
    )

    return scheduler

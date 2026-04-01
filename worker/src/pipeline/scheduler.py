"""
Scheduler: APScheduler-backed 15-minute cycle trigger.

Uses AsyncIOScheduler with an in-memory job store.  Docker's
``restart: unless-stopped`` policy provides restart resilience; a persistent
job store is unnecessary and would prevent closures from being used as the
cycle callback (APScheduler cannot pickle local functions).
max_instances=1 prevents APScheduler from launching concurrent jobs.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone

from ..config import Settings

logger = logging.getLogger(__name__)


def create_scheduler(
    run_cycle_fn: Callable[[], Coroutine[Any, Any, Any]],
    settings: Settings,
) -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance.

    Uses the default in-memory job store so that any callable (including
    closures) can be scheduled without serialisation constraints.
    ``max_instances=1`` is set at the APScheduler level as an additional
    concurrency guard on top of ``CycleQueue``'s asyncio lock.

    Args:
        run_cycle_fn: Async callable to invoke each interval.  Typically
            a wrapper that calls ``CycleQueue.submit(CycleRunner.run_cycle())``.
        settings: Worker settings (cycle_interval_minutes).

    Returns:
        Configured :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler`
        (not yet started — call ``.start()`` to activate).
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_cycle_fn,
        trigger=IntervalTrigger(minutes=settings.cycle_interval_minutes),
        next_run_time=datetime.now(timezone.utc),
        id="pipeline_cycle",
        name="SSE Sentiment Collection Cycle",
        replace_existing=True,
        max_instances=1,  # APScheduler-level concurrency guard
    )

    logger.info(
        "Scheduler configured: interval=%d minutes, jobstore=memory",
        settings.cycle_interval_minutes,
    )

    return scheduler

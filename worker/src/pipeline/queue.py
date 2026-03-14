"""
CycleQueue: enforces sequential, non-concurrent cycle execution.

APScheduler max_instances=1 prevents concurrent job starts.
CycleQueue provides an additional asyncio.Lock for fine-grained
in-process sequencing and "queue one" overflow behavior.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CycleQueue:
    """
    Ensures pipeline cycles run sequentially.

    At most ONE cycle runs at a time. If a new cycle is triggered
    while one is running, it queues and runs immediately after.
    Additional triggers while the queue is full are dropped.

    This provides an in-process sequencing layer on top of APScheduler's
    ``max_instances=1`` job-level guard.
    """

    def __init__(self) -> None:
        """Initialise the lock and queue state."""
        self._lock: asyncio.Lock = asyncio.Lock()
        self._queued: bool = False

    async def submit(self, coro: Awaitable[object]) -> None:
        """
        Submit a cycle coroutine for sequential execution.

        Behaviour:
        - If idle: acquire lock and run immediately.
        - If running and queue empty: queue one — run immediately after current finishes.
        - If running and queue full: drop with a warning log.

        Args:
            coro: Awaitable to execute (typically ``CycleRunner.run_cycle()``).
        """
        if self._lock.locked():
            if not self._queued:
                self._queued = True
                logger.warning(
                    "cycle_queued: previous cycle still running, one cycle queued"
                )
                # Wait for the lock to become available, then run
                async with self._lock:
                    self._queued = False
                    await coro
            else:
                logger.warning(
                    "cycle_dropped: queue already full, dropping trigger"
                )
            return

        async with self._lock:
            await coro

"""
Unit tests for CycleQueue.

Tests sequential execution guarantees, queue-one overflow behaviour,
and drop semantics when the queue is full.
"""
from __future__ import annotations

import asyncio

import pytest

from src.pipeline.queue import CycleQueue


class TestCycleQueueIdle:
    """Tests when the queue is idle (lock is not held)."""

    @pytest.mark.asyncio
    async def test_submit_runs_immediately_when_idle(self) -> None:
        """When idle, submitted coroutine runs immediately."""
        queue = CycleQueue()
        executed: list[int] = []

        async def task() -> None:
            executed.append(1)

        await queue.submit(task())
        assert executed == [1]

    @pytest.mark.asyncio
    async def test_multiple_sequential_submits(self) -> None:
        """Multiple sequential submits all execute in order."""
        queue = CycleQueue()
        order: list[int] = []

        async def task(n: int) -> None:
            order.append(n)

        await queue.submit(task(1))
        await queue.submit(task(2))
        await queue.submit(task(3))

        assert order == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_lock_not_held_after_completion(self) -> None:
        """Lock is released after coroutine completes."""
        queue = CycleQueue()

        async def noop() -> None:
            pass

        await queue.submit(noop())
        assert not queue._lock.locked()


class TestCycleQueueConcurrency:
    """Tests concurrent submit behaviour."""

    @pytest.mark.asyncio
    async def test_concurrent_submit_queues_one(self) -> None:
        """One cycle queues while another is running; both execute."""
        queue = CycleQueue()
        executed: list[int] = []
        barrier = asyncio.Event()

        async def slow_task() -> None:
            executed.append(1)
            await barrier.wait()

        async def fast_task() -> None:
            executed.append(2)

        # Start slow task in background (holds lock)
        slow_fut = asyncio.create_task(queue.submit(slow_task()))
        # Give the event loop a tick so slow_task acquires the lock
        await asyncio.sleep(0)

        # Queue fast_task while slow_task is running
        fast_fut = asyncio.create_task(queue.submit(fast_task()))
        await asyncio.sleep(0)

        # Release the barrier so slow_task finishes
        barrier.set()
        await asyncio.gather(slow_fut, fast_fut)

        # Both should have executed: slow first, then fast
        assert 1 in executed
        assert 2 in executed

    @pytest.mark.asyncio
    async def test_drop_when_queue_full(self) -> None:
        """Third concurrent submit is dropped when queue is full."""
        queue = CycleQueue()
        executed: list[int] = []
        barrier1 = asyncio.Event()

        async def slow_task() -> None:
            executed.append(1)
            await barrier1.wait()

        async def queued_task() -> None:
            executed.append(2)

        async def dropped_task() -> None:
            executed.append(3)  # should NOT execute

        # Start slow_task — holds lock
        slow_fut = asyncio.create_task(queue.submit(slow_task()))
        await asyncio.sleep(0)

        # Submit queued_task — should queue (queue empty)
        queued_fut = asyncio.create_task(queue.submit(queued_task()))
        await asyncio.sleep(0)

        # Submit dropped_task — queue is full, should be dropped
        dropped_fut = asyncio.create_task(queue.submit(dropped_task()))
        await asyncio.sleep(0)

        # Release slow_task
        barrier1.set()
        await asyncio.gather(slow_fut, queued_fut, dropped_fut)

        # slow and queued ran, but dropped_task was silently dropped
        assert 1 in executed
        assert 2 in executed
        assert 3 not in executed

    @pytest.mark.asyncio
    async def test_queued_flag_reset_after_queued_task_runs(self) -> None:
        """_queued flag is reset to False after the queued task runs."""
        queue = CycleQueue()
        barrier = asyncio.Event()

        async def slow() -> None:
            await barrier.wait()

        async def queued() -> None:
            pass

        slow_fut = asyncio.create_task(queue.submit(slow()))
        await asyncio.sleep(0)

        queued_fut = asyncio.create_task(queue.submit(queued()))
        await asyncio.sleep(0)

        assert queue._queued is True

        barrier.set()
        await asyncio.gather(slow_fut, queued_fut)

        assert queue._queued is False


class TestCycleQueueStateSafety:
    """Tests for state correctness around errors."""

    @pytest.mark.asyncio
    async def test_exception_in_coro_releases_lock(self) -> None:
        """If the submitted coroutine raises, the lock is still released."""
        queue = CycleQueue()

        async def failing_task() -> None:
            raise ValueError("Oops")

        with pytest.raises(ValueError, match="Oops"):
            await queue.submit(failing_task())

        assert not queue._lock.locked()

    @pytest.mark.asyncio
    async def test_subsequent_submit_works_after_exception(self) -> None:
        """After an exception, the queue can accept and run new tasks."""
        queue = CycleQueue()
        executed: list[int] = []

        async def failing_task() -> None:
            raise RuntimeError("fail")

        async def ok_task() -> None:
            executed.append(42)

        with pytest.raises(RuntimeError):
            await queue.submit(failing_task())

        await queue.submit(ok_task())
        assert executed == [42]

"""
RunStore: persistence for CollectionRun records.

Design: pessimistic default -- runs are inserted as ``status='failed'`` and
are promoted to ``'success'`` or ``'partial'`` only on clean completion.
A container crash mid-cycle leaves an accurate failure record without any
cleanup code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CollectionRun


class RunStore:
    """CRUD operations for CollectionRun records.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self) -> CollectionRun:
        """Create a new collection run with pessimistic ``status='failed'``.

        The run is added to the session but *not* committed.  The caller is
        responsible for committing or rolling back the session.

        Returns:
            The newly created :class:`.CollectionRun` instance.
        """
        run = CollectionRun(
            id=uuid.uuid4(),
            started_at=datetime.now(tz=UTC),
            status="failed",
        )
        self._session.add(run)
        return run

    async def update_run_status(
        self,
        run: CollectionRun,
        status: str,
        sources_attempted: int,
        sources_succeeded: int,
        signals_stored: int,
        error_summary: str | None = None,
    ) -> None:
        """Update a run's outcome fields on completion.

        Sets ``completed_at`` to the current UTC time.

        Args:
            run: The :class:`.CollectionRun` to update (must be in session).
            status: Final status — ``'success'``, ``'partial'``, or
                ``'failed'``.
            sources_attempted: Number of data sources the cycle attempted.
            sources_succeeded: Number of sources that returned data.
            signals_stored: Total signals persisted during the cycle.
            error_summary: Human-readable operational description.
                Must not contain PII.
        """
        run.status = status
        run.completed_at = datetime.now(tz=UTC)
        run.sources_attempted = sources_attempted
        run.sources_succeeded = sources_succeeded
        run.signals_stored = signals_stored
        run.error_summary = error_summary

    async def get_last_successful_run(self) -> CollectionRun | None:
        """Return the most recent run with ``status='success'`` or ``'partial'``.

        The pipeline uses this to determine the ``since`` timestamp for
        incremental scraping.

        Returns:
            The most recent successful :class:`.CollectionRun`, or ``None``
            if no successful run has ever been recorded (e.g. first run).
        """
        stmt = (
            select(CollectionRun)
            .where(CollectionRun.status.in_(["success", "partial"]))
            .order_by(CollectionRun.started_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

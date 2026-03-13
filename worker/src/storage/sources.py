"""
SourceStore: manage configured Reddit data sources.

Active sources are read at the start of each pipeline cycle so that
configuration changes (add/disable a subreddit) take effect on the next cycle
without requiring a service restart.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DataSource


class SourceStore:
    """CRUD operations for DataSource records.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_sources(self) -> list[DataSource]:
        """Return all enabled data sources.

        Returns:
            List of :class:`.DataSource` rows where ``enabled=True``.
        """
        stmt = select(DataSource).where(DataSource.enabled == True)  # noqa: E712
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def disable_source(self, subreddit_name: str) -> None:
        """Disable a subreddit by name.

        Used by the pipeline when a subreddit is permanently unavailable
        (e.g. banned or private).  This is a soft-delete — the record is
        preserved for audit purposes.

        Args:
            subreddit_name: Subreddit name (case-insensitive).  Will be
                lower-cased before querying.
        """
        stmt = select(DataSource).where(
            DataSource.subreddit_name == subreddit_name.lower()
        )
        result = await self._session.execute(stmt)
        source = result.scalar_one_or_none()
        if source:
            source.enabled = False
            source.disabled_at = datetime.now(tz=UTC)

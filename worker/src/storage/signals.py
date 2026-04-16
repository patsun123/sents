"""
SignalStore: persistence operations for SentimentSignal.

Design note: signals are immutable after insert.  Idempotency is achieved via
``INSERT ... ON CONFLICT DO NOTHING``, so re-running a collection cycle will
not create duplicate rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SentimentSignal


class SignalStore:
    """CRUD operations for SentimentSignal records.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_insert_signals(
        self,
        signals: list[dict[str, object]],
    ) -> int:
        """Insert multiple signals atomically.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` for idempotency so that
        re-running a collection cycle against already-stored signals is safe.

        Args:
            signals: List of dicts.  Each dict must contain the keys
                ``collection_run_id``, ``ticker_symbol``,
                ``sentiment_polarity``, ``upvote_weight``, ``reply_count``,
                ``collected_at``, ``source_subreddit``, ``source_thread_url``, and
                ``source_content_type``.
                No PII fields are accepted.

        Returns:
            Number of rows actually inserted (excluding conflicts).
        """
        if not signals:
            return 0

        stmt = insert(SentimentSignal).values(signals)
        stmt = stmt.on_conflict_do_nothing()
        raw = await self._session.execute(stmt)
        cursor = cast(CursorResult[tuple[()]], raw)
        return cursor.rowcount

    async def get_signals_for_window(
        self,
        ticker_symbol: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[SentimentSignal]:
        """Retrieve signals for a ticker within a time window.

        Used by scoring algorithms to aggregate signals.

        Args:
            ticker_symbol: Upper-cased ticker, e.g. ``'GME'``.
            window_start: Inclusive start of the window (timezone-aware).
            window_end: Inclusive end of the window (timezone-aware).

        Returns:
            List of :class:`.SentimentSignal` rows ordered by
            ``collected_at`` ascending.
        """
        stmt = (
            select(SentimentSignal)
            .where(SentimentSignal.ticker_symbol == ticker_symbol.upper())
            .where(SentimentSignal.collected_at >= window_start)
            .where(SentimentSignal.collected_at <= window_end)
            .order_by(SentimentSignal.collected_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

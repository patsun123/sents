"""
SQLAlchemy ORM models for SSE worker.

PRIVACY GUARANTEE: No model contains a column for Reddit usernames,
comment IDs, post IDs, or any user-attributable data.
All column definitions must match contracts/schema.sql exactly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all SSE ORM models."""


class DataSource(Base):
    """A configured Reddit subreddit to scrape.

    Records are never deleted — only disabled via the ``enabled`` flag.
    Soft-delete preserves history for audit purposes.
    """

    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subreddit_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "idx_data_sources_enabled",
            "enabled",
            postgresql_where=(enabled == True),  # noqa: E712
        ),
    )


class CollectionRun(Base):
    """One pipeline execution cycle.

    Append-only — status starts as ``'failed'`` (pessimistic default).
    A container crash mid-cycle leaves an accurate failure record without
    any cleanup code.
    """

    __tablename__ = "collection_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="failed")
    sources_attempted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sources_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    signals: Mapped[list[SentimentSignal]] = relationship(
        "SentimentSignal", back_populates="run"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'partial', 'failed')", name="ck_run_status"
        ),
        Index("idx_collection_runs_started_at", "started_at"),
        Index("idx_collection_runs_status", "status"),
    )


class SentimentSignal(Base):
    """Atomic sentiment signal.

    Immutable after insert.  Never contains PII — no username, comment ID,
    post ID, or any user-attributable data is stored.
    """

    __tablename__ = "sentiment_signals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("collection_runs.id"),
        nullable=False,
    )
    ticker_symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    sentiment_polarity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    upvote_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_subreddit: Mapped[str] = mapped_column(String(50), nullable=False)

    run: Mapped[CollectionRun] = relationship(
        "CollectionRun", back_populates="signals"
    )

    __table_args__ = (
        CheckConstraint(
            "sentiment_polarity IN (-1, 1)", name="ck_signal_polarity"
        ),
        CheckConstraint("upvote_weight >= 0", name="ck_signal_upvotes"),
        Index("idx_signals_ticker_time", "ticker_symbol", "collected_at"),
        Index("idx_signals_run", "collection_run_id"),
        Index("idx_signals_collected_at", "collected_at"),
        Index("idx_signals_subreddit", "source_subreddit"),
    )


class ScoredResult(Base):
    """Derived scoring algorithm output.

    Multiple algorithms can produce results per ticker/window.
    Cached in Redis for API serving; PostgreSQL is the durable store.
    """

    __tablename__ = "scored_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticker_symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    algorithm_id: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    signal_window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "confidence BETWEEN 0 AND 1", name="ck_scored_confidence"
        ),
        Index(
            "idx_scored_ticker_algo_time",
            "ticker_symbol",
            "algorithm_id",
            "computed_at",
        ),
        Index("idx_scored_computed_at", "computed_at"),
    )

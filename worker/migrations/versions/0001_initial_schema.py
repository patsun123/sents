"""Initial schema: data_sources, collection_runs, sentiment_signals, scored_results.

Revision ID: 0001
Revises:
Create Date: 2026-03-13 00:00:00.000000

This migration creates all tables, indexes, and constraints that match
``contracts/schema.sql`` exactly.  The ``pgcrypto`` extension is enabled for
compatibility with the SQL contract, but UUID primary keys are generated in
Python (``uuid.uuid4()``) rather than via ``gen_random_uuid()``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create all SentiX tables, indexes, and constraints."""

    # Enable pgcrypto for gen_random_uuid() compatibility (used in raw SQL).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # data_sources
    # ------------------------------------------------------------------
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subreddit_name", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subreddit_name", name="uq_data_sources_subreddit_name"),
    )
    op.create_index(
        "idx_data_sources_enabled",
        "data_sources",
        ["enabled"],
        postgresql_where=sa.text("enabled = TRUE"),
    )

    # ------------------------------------------------------------------
    # collection_runs
    # ------------------------------------------------------------------
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'failed'"),
        ),
        sa.Column(
            "sources_attempted", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "sources_succeeded", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "signals_stored", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('success', 'partial', 'failed')", name="ck_run_status"
        ),
    )
    op.create_index("idx_collection_runs_started_at", "collection_runs", ["started_at"])
    op.create_index("idx_collection_runs_status", "collection_runs", ["status"])

    # ------------------------------------------------------------------
    # sentiment_signals
    # ------------------------------------------------------------------
    op.create_table(
        "sentiment_signals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("collection_run_id", sa.Uuid(), nullable=False),
        sa.Column("ticker_symbol", sa.String(10), nullable=False),
        sa.Column("sentiment_polarity", sa.SmallInteger(), nullable=False),
        sa.Column(
            "upvote_weight", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("source_subreddit", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
            name="fk_signals_collection_run_id",
        ),
        sa.CheckConstraint(
            "sentiment_polarity IN (-1, 1)", name="ck_signal_polarity"
        ),
        sa.CheckConstraint("upvote_weight >= 0", name="ck_signal_upvotes"),
    )
    op.create_index(
        "idx_signals_ticker_time", "sentiment_signals", ["ticker_symbol", "collected_at"]
    )
    op.create_index("idx_signals_run", "sentiment_signals", ["collection_run_id"])
    op.create_index("idx_signals_collected_at", "sentiment_signals", ["collected_at"])
    op.create_index("idx_signals_subreddit", "sentiment_signals", ["source_subreddit"])

    # ------------------------------------------------------------------
    # scored_results
    # ------------------------------------------------------------------
    op.create_table(
        "scored_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ticker_symbol", sa.String(10), nullable=False),
        sa.Column("algorithm_id", sa.String(50), nullable=False),
        sa.Column("score", sa.Numeric(10, 6), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("signal_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name="ck_scored_confidence"
        ),
    )
    op.create_index(
        "idx_scored_ticker_algo_time",
        "scored_results",
        ["ticker_symbol", "algorithm_id", "computed_at"],
    )
    op.create_index("idx_scored_computed_at", "scored_results", ["computed_at"])


def downgrade() -> None:
    """Drop all SentiX tables in reverse dependency order."""
    op.drop_table("scored_results")
    op.drop_table("sentiment_signals")
    op.drop_table("collection_runs")
    op.drop_table("data_sources")

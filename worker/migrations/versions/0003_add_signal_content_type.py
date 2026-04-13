"""Add source_content_type column to sentiment_signals.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-13 00:00:00.000000

Stores whether a signal came from a Reddit post or comment so higher-level
aggregations can weight those content types differently without persisting
derived scores.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add source_content_type with a safe default and supporting constraints."""
    op.add_column(
        "sentiment_signals",
        sa.Column(
            "source_content_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'comment'"),
        ),
    )
    op.create_check_constraint(
        "ck_signal_content_type",
        "sentiment_signals",
        "source_content_type IN ('post', 'comment')",
    )
    op.create_index(
        "idx_signals_content_type",
        "sentiment_signals",
        ["source_content_type"],
    )


def downgrade() -> None:
    """Remove the source_content_type signal metadata."""
    op.drop_index("idx_signals_content_type", table_name="sentiment_signals")
    op.drop_constraint("ck_signal_content_type", "sentiment_signals", type_="check")
    op.drop_column("sentiment_signals", "source_content_type")

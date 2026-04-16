"""Add reply_count column to sentiment_signals.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add numeric reply-count engagement metadata to stored signals."""
    op.add_column(
        "sentiment_signals",
        sa.Column(
            "reply_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_signal_reply_count",
        "sentiment_signals",
        "reply_count >= 0",
    )


def downgrade() -> None:
    """Remove reply-count metadata from stored signals."""
    op.drop_constraint("ck_signal_reply_count", "sentiment_signals", type_="check")
    op.drop_column("sentiment_signals", "reply_count")

"""Add source_thread_url to sentiment signals.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sentiment_signals",
        sa.Column(
            "source_thread_url",
            sa.String(length=512),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("sentiment_signals", "source_thread_url", server_default=None)


def downgrade() -> None:
    op.drop_column("sentiment_signals", "source_thread_url")

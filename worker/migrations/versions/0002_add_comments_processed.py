"""Add comments_processed column to collection_runs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-15 00:00:00.000000

Tracks how many Reddit comments were processed (scanned) per collection
cycle.  This is a privacy-safe aggregate counter — no comment IDs, text,
or user-attributable data is stored.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add comments_processed column with server default 0."""
    op.add_column(
        "collection_runs",
        sa.Column(
            "comments_processed",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Remove comments_processed column."""
    op.drop_column("collection_runs", "comments_processed")

"""Named pricing configuration presets for scenario comparison.

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:02:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "003"
down_revision: str = "002"
branch_labels = None
depends_on = None

_SEED_CONFIGS = [
    (
        "balanced",
        "Balanced",
        "Default configuration -- all weights at 1.0. Matches the live pricing engine defaults.",
        {
            "sensitivity": 1.0,
            "max_delta_pct": 0.10,
            "upvote_weight_multiplier": 1.0,
            "volume_scaling_function": "log",
            "volume_weight_multiplier": 1.0,
            "min_mentions": 3,
        },
    ),
    (
        "upvote-heavy",
        "Upvote-Heavy",
        "Reddit karma (upvote score) drives 2x more of the signal than the default.",
        {
            "sensitivity": 1.0,
            "max_delta_pct": 0.10,
            "upvote_weight_multiplier": 2.0,
            "volume_scaling_function": "log",
            "volume_weight_multiplier": 1.0,
            "min_mentions": 3,
        },
    ),
    (
        "volume-heavy",
        "Volume-Heavy",
        "Mention count drives the signal linearly (not log-scaled), amplified 2x.",
        {
            "sensitivity": 1.0,
            "max_delta_pct": 0.10,
            "upvote_weight_multiplier": 1.0,
            "volume_scaling_function": "linear",
            "volume_weight_multiplier": 2.0,
            "min_mentions": 3,
        },
    ),
]


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.execute("""
        CREATE TABLE pricing_configurations (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            slug        VARCHAR(64) UNIQUE NOT NULL,
            name        VARCHAR(128) NOT NULL,
            description TEXT,
            params      JSONB NOT NULL,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("CREATE INDEX idx_pricing_configs_slug ON pricing_configurations (slug)")
    op.execute("CREATE INDEX idx_pricing_configs_active ON pricing_configurations (is_active)")

    import json
    for slug, name, description, params in _SEED_CONFIGS:
        op.execute(
            sa.text("""
                INSERT INTO pricing_configurations (slug, name, description, params)
                VALUES (:slug, :name, :description, :params::jsonb)
            """),
            {
                "slug": slug,
                "name": name,
                "description": description,
                "params": json.dumps(params),
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pricing_configurations CASCADE")

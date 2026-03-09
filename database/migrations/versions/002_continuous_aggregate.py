"""TimescaleDB continuous aggregate for 1-hour sentiment price buckets.

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:01:00.000000
"""
from __future__ import annotations

from alembic import op

revision: str = "002"
down_revision: str = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Continuous aggregate: 1-hour buckets of sentiment_prices
    op.execute("""
        CREATE MATERIALIZED VIEW sentiment_prices_1h
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', time)      AS bucket,
            ticker,
            last(sentiment_price, time)       AS sentiment_price,
            last(real_price_at_calc, time)    AS real_price,
            avg(sentiment_delta)              AS avg_sentiment_delta
        FROM sentiment_prices
        GROUP BY bucket, ticker
        WITH NO DATA
    """)

    # Refresh policy: keep last 3 days fresh, refresh hourly
    op.execute("""
        SELECT add_continuous_aggregate_policy(
            'sentiment_prices_1h',
            start_offset  => INTERVAL '3 days',
            end_offset    => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour'
        )
    """)


def downgrade() -> None:
    op.execute("""
        SELECT remove_continuous_aggregate_policy('sentiment_prices_1h', if_exists => TRUE)
    """)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS sentiment_prices_1h CASCADE")

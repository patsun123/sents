"""Initial schema — all core tables.

Revision ID: 001
Revises:
Create Date: 2026-03-01 00:00:00.000000

Column names are authoritative: application code must match these names.
"""
from __future__ import annotations

from alembic import op

revision: str = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- Extensions ----------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # -- tickers -------------------------------------------------------------
    op.execute("""
        CREATE TABLE tickers (
            symbol      VARCHAR(10)  PRIMARY KEY,
            name        VARCHAR(255),
            is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        INSERT INTO tickers (symbol, name) VALUES
            ('TSLA', 'Tesla, Inc.'),
            ('NVDA', 'NVIDIA Corporation'),
            ('GME',  'GameStop Corp.'),
            ('PLTR', 'Palantir Technologies Inc.'),
            ('SOFI', 'SoFi Technologies, Inc.'),
            ('RIVN', 'Rivian Automotive, Inc.')
    """)

    # -- reddit_raw ----------------------------------------------------------
    # One row per (Reddit post/comment × ticker mentioned).
    # Canonical name: reddit_raw  (NOT reddit_raw_data).
    # UNIQUE: (reddit_id, ticker_mentioned) — not reddit_id alone.
    op.execute("""
        CREATE TABLE reddit_raw (
            id                  BIGSERIAL    PRIMARY KEY,
            reddit_id           VARCHAR(20)  NOT NULL,
            ticker_mentioned    VARCHAR(10)  NOT NULL REFERENCES tickers(symbol),
            subreddit           VARCHAR(100) NOT NULL,
            author              VARCHAR(100),
            title               TEXT,
            content             TEXT,
            score               INTEGER      NOT NULL DEFAULT 0,
            upvote_ratio        DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            num_comments        INTEGER      NOT NULL DEFAULT 0,
            post_url            TEXT,
            post_type           VARCHAR(10)  NOT NULL DEFAULT 'post',
            content_fingerprint VARCHAR(64),
            is_duplicate        BOOLEAN      NOT NULL DEFAULT FALSE,
            created_utc         TIMESTAMPTZ  NOT NULL,
            scraped_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT reddit_raw_unique_post_ticker
                UNIQUE (reddit_id, ticker_mentioned)
        )
    """)

    op.execute("CREATE INDEX idx_reddit_raw_ticker   ON reddit_raw (ticker_mentioned)")
    op.execute("CREATE INDEX idx_reddit_raw_created  ON reddit_raw (created_utc)")
    op.execute("""
        CREATE INDEX idx_reddit_raw_fingerprint
            ON reddit_raw (content_fingerprint, scraped_at)
            WHERE is_duplicate = FALSE
    """)

    # -- comment_sentiment ---------------------------------------------------
    # NLP output: one row per (reddit_raw row × NLP backend).
    # reddit_comment_id is a BIGINT FK to reddit_raw.id (the surrogate PK),
    # not Reddit's string ID.
    op.execute("""
        CREATE TABLE comment_sentiment (
            id                  BIGSERIAL        PRIMARY KEY,
            reddit_comment_id   BIGINT           NOT NULL
                                    REFERENCES reddit_raw(id) ON DELETE CASCADE,
            backend             VARCHAR(20)      NOT NULL,
            compound_score      DOUBLE PRECISION NOT NULL,
            positive_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
            negative_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
            neutral_score       DOUBLE PRECISION NOT NULL DEFAULT 0,
            raw_scores          JSONB,
            analyzed_at         TIMESTAMPTZ      NOT NULL DEFAULT now(),
            CONSTRAINT comment_sentiment_unique
                UNIQUE (reddit_comment_id, backend)
        )
    """)

    op.execute("""
        CREATE INDEX idx_comment_sentiment_post
            ON comment_sentiment (reddit_comment_id)
    """)

    # -- ticker_sentiment_snapshot -------------------------------------------
    # Per-ticker aggregate per time window per backend.
    # UNIQUE: (ticker, window_start, window_end, backend).
    op.execute("""
        CREATE TABLE ticker_sentiment_snapshot (
            id                      BIGSERIAL        PRIMARY KEY,
            ticker                  VARCHAR(10)      NOT NULL REFERENCES tickers(symbol),
            window_start            TIMESTAMPTZ      NOT NULL,
            window_end              TIMESTAMPTZ      NOT NULL,
            backend                 VARCHAR(20)      NOT NULL,
            avg_sentiment_compound  DOUBLE PRECISION NOT NULL DEFAULT 0,
            weighted_mention_count  DOUBLE PRECISION NOT NULL DEFAULT 0,
            avg_upvote_score        DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ      NOT NULL DEFAULT now(),
            CONSTRAINT snapshot_unique
                UNIQUE (ticker, window_start, window_end, backend)
        )
    """)

    op.execute("""
        CREATE INDEX idx_snapshot_ticker_window
            ON ticker_sentiment_snapshot (ticker, window_end DESC)
    """)

    # -- real_prices (TimescaleDB hypertable) --------------------------------
    # One row per price fetch per ticker. Partitioned on `time`.
    op.execute("""
        CREATE TABLE real_prices (
            time            TIMESTAMPTZ      NOT NULL,
            ticker          VARCHAR(10)      NOT NULL REFERENCES tickers(symbol),
            price           DOUBLE PRECISION NOT NULL,
            source          VARCHAR(20)      NOT NULL DEFAULT 'yfinance',
            market_status   VARCHAR(20)      NOT NULL DEFAULT 'unknown',
            created_at      TIMESTAMPTZ      NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        SELECT create_hypertable('real_prices', 'time',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE)
    """)

    op.execute("""
        CREATE INDEX idx_real_prices_ticker ON real_prices (ticker, time DESC)
    """)

    # -- sentiment_prices (TimescaleDB hypertable) ---------------------------
    # Final computed prices: sentiment_price = real_price + sentiment_delta.
    # PRIMARY KEY (time, ticker) is required by TimescaleDB.
    op.execute("""
        CREATE TABLE sentiment_prices (
            time                TIMESTAMPTZ      NOT NULL,
            ticker              VARCHAR(10)      NOT NULL REFERENCES tickers(symbol),
            sentiment_price     DOUBLE PRECISION NOT NULL,
            real_price_at_calc  DOUBLE PRECISION NOT NULL,
            sentiment_delta     DOUBLE PRECISION NOT NULL,
            parameters_version  VARCHAR(50)      NOT NULL DEFAULT 'default',
            created_at          TIMESTAMPTZ      NOT NULL DEFAULT now(),
            PRIMARY KEY (time, ticker)
        )
    """)

    op.execute("""
        SELECT create_hypertable('sentiment_prices', 'time',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE)
    """)

    op.execute("""
        CREATE INDEX idx_sentiment_prices_ticker
            ON sentiment_prices (ticker, time DESC)
    """)

    # -- pricing_parameters --------------------------------------------------
    # Live formula parameters. Single active row managed via DB/config.
    op.execute("""
        CREATE TABLE pricing_parameters (
            id                          SERIAL           PRIMARY KEY,
            sensitivity                 DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            max_delta_pct               DOUBLE PRECISION NOT NULL DEFAULT 0.10,
            upvote_weight_multiplier    DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            volume_scaling_function     VARCHAR(10)      NOT NULL DEFAULT 'log',
            volume_weight_multiplier    DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            min_mentions                INTEGER          NOT NULL DEFAULT 3,
            updated_at                  TIMESTAMPTZ      NOT NULL DEFAULT now()
        )
    """)

    # Seed one default row
    op.execute("INSERT INTO pricing_parameters DEFAULT VALUES")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pricing_parameters     CASCADE")
    op.execute("DROP TABLE IF EXISTS sentiment_prices       CASCADE")
    op.execute("DROP TABLE IF EXISTS real_prices            CASCADE")
    op.execute("DROP TABLE IF EXISTS ticker_sentiment_snapshot CASCADE")
    op.execute("DROP TABLE IF EXISTS comment_sentiment      CASCADE")
    op.execute("DROP TABLE IF EXISTS reddit_raw             CASCADE")
    op.execute("DROP TABLE IF EXISTS tickers                CASCADE")

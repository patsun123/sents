-- =============================================================================
-- SSE Database Initialization
-- Runs automatically on first postgres container startup (empty data volume).
-- Combines user creation + full schema migrations in dependency order.
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- Users (least-privilege service accounts)
-- =============================================================================
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sse_api') THEN
    CREATE ROLE sse_api WITH LOGIN PASSWORD 'changeme_api';
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sse_scraper') THEN
    CREATE ROLE sse_scraper WITH LOGIN PASSWORD 'changeme_scraper';
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sse_processor') THEN
    CREATE ROLE sse_processor WITH LOGIN PASSWORD 'changeme_processor';
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sse_pricing') THEN
    CREATE ROLE sse_pricing WITH LOGIN PASSWORD 'changeme_pricing';
  END IF;
END $$;
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sse_admin') THEN
    CREATE ROLE sse_admin WITH LOGIN PASSWORD 'changeme_admin' SUPERUSER;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO sse_api, sse_scraper, sse_processor, sse_pricing;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO sse_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sse_admin;

-- =============================================================================
-- Migration 001 — Core tables
-- =============================================================================
CREATE TABLE tickers (
    symbol      VARCHAR(10)  PRIMARY KEY,
    name        VARCHAR(255),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

INSERT INTO tickers (symbol, name) VALUES
    ('TSLA', 'Tesla, Inc.'),
    ('NVDA', 'NVIDIA Corporation'),
    ('GME',  'GameStop Corp.'),
    ('PLTR', 'Palantir Technologies Inc.'),
    ('SOFI', 'SoFi Technologies, Inc.'),
    ('RIVN', 'Rivian Automotive, Inc.');

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
    CONSTRAINT reddit_raw_unique_post_ticker UNIQUE (reddit_id, ticker_mentioned)
);

CREATE INDEX idx_reddit_raw_ticker      ON reddit_raw (ticker_mentioned);
CREATE INDEX idx_reddit_raw_created     ON reddit_raw (created_utc);
CREATE INDEX idx_reddit_raw_fingerprint ON reddit_raw (content_fingerprint, scraped_at) WHERE is_duplicate = FALSE;

CREATE TABLE comment_sentiment (
    id                  BIGSERIAL        PRIMARY KEY,
    reddit_comment_id   BIGINT           NOT NULL REFERENCES reddit_raw(id) ON DELETE CASCADE,
    backend             VARCHAR(20)      NOT NULL,
    compound_score      DOUBLE PRECISION NOT NULL,
    positive_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
    negative_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
    neutral_score       DOUBLE PRECISION NOT NULL DEFAULT 0,
    raw_scores          JSONB,
    analyzed_at         TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT comment_sentiment_unique UNIQUE (reddit_comment_id, backend)
);

CREATE INDEX idx_comment_sentiment_post ON comment_sentiment (reddit_comment_id);

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
    CONSTRAINT snapshot_unique UNIQUE (ticker, window_start, window_end, backend)
);

CREATE INDEX idx_snapshot_ticker_window ON ticker_sentiment_snapshot (ticker, window_end DESC);

CREATE TABLE real_prices (
    time            TIMESTAMPTZ      NOT NULL,
    ticker          VARCHAR(10)      NOT NULL REFERENCES tickers(symbol),
    price           DOUBLE PRECISION NOT NULL,
    source          VARCHAR(20)      NOT NULL DEFAULT 'yfinance',
    market_status   VARCHAR(20)      NOT NULL DEFAULT 'unknown',
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now()
);

SELECT create_hypertable('real_prices', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
ALTER TABLE real_prices ADD CONSTRAINT real_prices_time_ticker_key UNIQUE (time, ticker);
CREATE INDEX idx_real_prices_ticker ON real_prices (ticker, time DESC);

CREATE TABLE sentiment_prices (
    time                TIMESTAMPTZ      NOT NULL,
    ticker              VARCHAR(10)      NOT NULL REFERENCES tickers(symbol),
    sentiment_price     DOUBLE PRECISION NOT NULL,
    real_price_at_calc  DOUBLE PRECISION NOT NULL,
    sentiment_delta     DOUBLE PRECISION NOT NULL,
    parameters_version  VARCHAR(50)      NOT NULL DEFAULT 'default',
    created_at          TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (time, ticker)
);

SELECT create_hypertable('sentiment_prices', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
CREATE INDEX idx_sentiment_prices_ticker ON sentiment_prices (ticker, time DESC);

CREATE TABLE pricing_parameters (
    id                          SERIAL           PRIMARY KEY,
    sensitivity                 DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    max_delta_pct               DOUBLE PRECISION NOT NULL DEFAULT 0.10,
    upvote_weight_multiplier    DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    volume_scaling_function     VARCHAR(10)      NOT NULL DEFAULT 'log',
    volume_weight_multiplier    DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    min_mentions                INTEGER          NOT NULL DEFAULT 3,
    updated_at                  TIMESTAMPTZ      NOT NULL DEFAULT now()
);

INSERT INTO pricing_parameters DEFAULT VALUES;

-- =============================================================================
-- Migration 002 — Continuous aggregate
-- =============================================================================
CREATE MATERIALIZED VIEW sentiment_prices_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)   AS bucket,
    ticker,
    last(sentiment_price, time)   AS sentiment_price,
    last(real_price_at_calc, time) AS real_price,
    avg(sentiment_delta)          AS avg_sentiment_delta
FROM sentiment_prices
GROUP BY bucket, ticker
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'sentiment_prices_1h',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- =============================================================================
-- Migration 003 — Pricing configurations
-- =============================================================================
CREATE TABLE pricing_configurations (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug        VARCHAR(64) UNIQUE NOT NULL,
    name        VARCHAR(128) NOT NULL,
    description TEXT,
    params      JSONB        NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_pricing_configs_slug   ON pricing_configurations (slug);
CREATE INDEX idx_pricing_configs_active ON pricing_configurations (is_active);

INSERT INTO pricing_configurations (slug, name, description, params) VALUES
    ('balanced',     'Balanced',     'Default configuration -- all weights at 1.0.',
     '{"sensitivity":1.0,"max_delta_pct":0.10,"upvote_weight_multiplier":1.0,"volume_scaling_function":"log","volume_weight_multiplier":1.0,"min_mentions":3,"decay_halflife_hours":12,"upvote_weight_min":0.1,"upvote_weight_max":10.0}'::jsonb),
    ('upvote-heavy', 'Upvote-Heavy', 'Reddit karma drives 2x more of the signal.',
     '{"sensitivity":1.0,"max_delta_pct":0.10,"upvote_weight_multiplier":2.0,"volume_scaling_function":"log","volume_weight_multiplier":1.0,"min_mentions":3,"decay_halflife_hours":12,"upvote_weight_min":0.1,"upvote_weight_max":10.0}'::jsonb),
    ('volume-heavy', 'Volume-Heavy', 'Mention count amplified 2x, linear scaling.',
     '{"sensitivity":1.0,"max_delta_pct":0.10,"upvote_weight_multiplier":1.0,"volume_scaling_function":"linear","volume_weight_multiplier":2.0,"min_mentions":3,"decay_halflife_hours":12,"upvote_weight_min":0.1,"upvote_weight_max":10.0}'::jsonb);

-- =============================================================================
-- Table grants (after tables exist)
-- =============================================================================
GRANT SELECT, INSERT, UPDATE ON reddit_raw TO sse_scraper;
GRANT SELECT ON reddit_raw TO sse_processor, sse_api;
GRANT SELECT, INSERT ON comment_sentiment TO sse_processor;
GRANT SELECT ON comment_sentiment TO sse_api;
GRANT SELECT, INSERT ON ticker_sentiment_snapshot TO sse_processor;
GRANT SELECT ON ticker_sentiment_snapshot TO sse_pricing, sse_api;
GRANT SELECT ON tickers TO sse_pricing, sse_scraper, sse_api;
GRANT SELECT ON pricing_parameters TO sse_pricing, sse_api;
GRANT SELECT ON pricing_configurations TO sse_pricing, sse_api;
GRANT SELECT, INSERT ON real_prices TO sse_pricing;
GRANT SELECT ON real_prices TO sse_api;
GRANT SELECT, INSERT ON sentiment_prices TO sse_pricing;
GRANT SELECT ON sentiment_prices TO sse_api;
GRANT SELECT ON sentiment_prices_1h TO sse_api;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sse_scraper, sse_processor, sse_pricing;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO sse_admin;

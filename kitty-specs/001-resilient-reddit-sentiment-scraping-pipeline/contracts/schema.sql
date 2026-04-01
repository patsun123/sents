-- SentiX Sentiment Pipeline: PostgreSQL Schema
-- Feature: 001-resilient-reddit-sentiment-scraping-pipeline
-- Date: 2026-03-09
--
-- Privacy guarantee: No Reddit usernames, comment IDs, post IDs,
-- or any user-attributable data exists in any table.

-- ─────────────────────────────────────────────
-- Extensions
-- ─────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()


-- ─────────────────────────────────────────────
-- data_sources
-- Configurable list of subreddits to scrape.
-- Never deleted — only disabled.
-- ─────────────────────────────────────────────

CREATE TABLE data_sources (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    subreddit_name  VARCHAR(50) NOT NULL UNIQUE,  -- lowercase, no r/ prefix
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at     TIMESTAMPTZ NULL      -- NULL = currently active
);

CREATE INDEX idx_data_sources_enabled ON data_sources (enabled) WHERE enabled = TRUE;


-- ─────────────────────────────────────────────
-- collection_runs
-- One row per pipeline execution cycle.
-- Append-only — never updated after status is set.
-- ─────────────────────────────────────────────

CREATE TABLE collection_runs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'failed'
                            CHECK (status IN ('success', 'partial', 'failed')),
    sources_attempted   INTEGER     NOT NULL DEFAULT 0,
    sources_succeeded   INTEGER     NOT NULL DEFAULT 0,
    signals_stored      INTEGER     NOT NULL DEFAULT 0,
    comments_processed  INTEGER     NOT NULL DEFAULT 0,  -- aggregate counter only, no PII
    error_summary       TEXT        NULL      -- No PII; operational description only
);

CREATE INDEX idx_collection_runs_started_at ON collection_runs (started_at DESC);
CREATE INDEX idx_collection_runs_status     ON collection_runs (status);


-- ─────────────────────────────────────────────
-- sentiment_signals
-- The permanent, algorithm-agnostic source of truth.
-- One row per ticker mention in a comment.
-- Immutable after insert.
-- ─────────────────────────────────────────────

CREATE TABLE sentiment_signals (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_run_id   UUID        NOT NULL REFERENCES collection_runs(id),
    ticker_symbol       VARCHAR(10) NOT NULL,           -- e.g., 'GME', 'TSLA'
    sentiment_polarity  SMALLINT    NOT NULL
                            CHECK (sentiment_polarity IN (-1, 1)),  -- -1=negative, 1=positive
    upvote_weight       INTEGER     NOT NULL DEFAULT 0
                            CHECK (upvote_weight >= 0),             -- comment upvotes at collection time
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_subreddit    VARCHAR(50) NOT NULL             -- e.g., 'wallstreetbets'
);

-- Primary query pattern: score signals for a ticker in a time window
CREATE INDEX idx_signals_ticker_time    ON sentiment_signals (ticker_symbol, collected_at DESC);
-- Join pattern: find signals for a specific run
CREATE INDEX idx_signals_run            ON sentiment_signals (collection_run_id);
-- Time-range queries across all tickers
CREATE INDEX idx_signals_collected_at   ON sentiment_signals (collected_at DESC);
-- Source-based filtering
CREATE INDEX idx_signals_subreddit      ON sentiment_signals (source_subreddit);


-- ─────────────────────────────────────────────
-- scored_results
-- Derived outputs from scoring algorithms.
-- Multiple algorithm_ids can coexist per ticker/window.
-- Cached in Redis for API serving; PostgreSQL is durable store.
-- ─────────────────────────────────────────────

CREATE TABLE scored_results (
    id                  UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker_symbol       VARCHAR(10)    NOT NULL,
    algorithm_id        VARCHAR(50)    NOT NULL,   -- e.g., 'weighted_sum_v1', 'vader_base'
    score               NUMERIC(10, 6) NOT NULL,   -- range is algorithm-dependent
    confidence          NUMERIC(5, 4)  NOT NULL
                            CHECK (confidence BETWEEN 0 AND 1),
    mention_count       INTEGER        NOT NULL,
    signal_window_start TIMESTAMPTZ    NOT NULL,
    signal_window_end   TIMESTAMPTZ    NOT NULL,
    computed_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Primary query: latest score for a ticker by algorithm
CREATE INDEX idx_scored_ticker_algo_time
    ON scored_results (ticker_symbol, algorithm_id, computed_at DESC);
-- Time-ordered access across all results
CREATE INDEX idx_scored_computed_at
    ON scored_results (computed_at DESC);

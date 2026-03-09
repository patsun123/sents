-- =============================================================================
-- SSE Database User Privilege Setup
-- =============================================================================
-- This script creates five PostgreSQL users with least-privilege access.
-- All statements are idempotent using DO $$ ... IF NOT EXISTS pattern.
--
-- Database: sse
-- Users:
--   - sse_admin: ALL privileges on ALL tables (Alembic migrations only)
--   - sse_api: SELECT only on ALL tables (FastAPI backend — read-only)
--   - sse_scraper: SELECT + INSERT on reddit_raw only
--   - sse_processor: SELECT on reddit_raw; SELECT + INSERT on comment_sentiment, ticker_sentiment_snapshot
--   - sse_pricing: SELECT on ticker_sentiment_snapshot, tickers, pricing_parameters, pricing_configurations, real_prices; SELECT + INSERT on sentiment_prices
--
-- WARNING: Replace all 'changeme_*' passwords with strong passwords before production deployment.
-- =============================================================================

-- Enable necessary extensions for this script
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- 1. Create sse_admin role
-- =============================================================================
-- Purpose: Alembic database migrations only. Has ALL privileges.
-- WARNING: Do not use this account for application services.
--
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sse_admin') THEN
    CREATE ROLE sse_admin WITH LOGIN PASSWORD 'changeme_admin';
  END IF;
END $$;

-- =============================================================================
-- 2. Create sse_api role
-- =============================================================================
-- Purpose: FastAPI backend API server. Read-only access to all tables.
-- Cannot INSERT, UPDATE, DELETE, or modify any data.
--
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sse_api') THEN
    CREATE ROLE sse_api WITH LOGIN PASSWORD 'changeme_api';
  END IF;
END $$;

-- =============================================================================
-- 3. Create sse_scraper role
-- =============================================================================
-- Purpose: Reddit data scraper service. Can select and insert raw Reddit posts.
-- Limited to reddit_raw table only.
--
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sse_scraper') THEN
    CREATE ROLE sse_scraper WITH LOGIN PASSWORD 'changeme_scraper';
  END IF;
END $$;

-- =============================================================================
-- 4. Create sse_processor role
-- =============================================================================
-- Purpose: Sentiment processing service. Reads raw data, writes processed sentiment.
-- Can SELECT from reddit_raw and INSERT/SELECT on sentiment tables.
--
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sse_processor') THEN
    CREATE ROLE sse_processor WITH LOGIN PASSWORD 'changeme_processor';
  END IF;
END $$;

-- =============================================================================
-- 5. Create sse_pricing role
-- =============================================================================
-- Purpose: Pricing engine service. Reads sentiment snapshots and parameters, writes computed prices.
-- Read-only on reference tables; INSERT/SELECT on sentiment_prices only.
--
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sse_pricing') THEN
    CREATE ROLE sse_pricing WITH LOGIN PASSWORD 'changeme_pricing';
  END IF;
END $$;

-- =============================================================================
-- Schema Access: Grant USAGE to all service accounts
-- =============================================================================
-- All service roles need to access the public schema.
--
GRANT USAGE ON SCHEMA public TO sse_api, sse_scraper, sse_processor, sse_pricing;

-- =============================================================================
-- Default Privileges: Ensure future tables follow least-privilege principle
-- =============================================================================
-- sse_api: SELECT only on all new tables
-- sse_admin: ALL on all new tables (for migrations)
--
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO sse_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sse_admin;

-- =============================================================================
-- Table-Specific Privileges
-- =============================================================================

-- -----------------------------------------------
-- reddit_raw: sse_scraper (SELECT, INSERT only)
-- -----------------------------------------------
GRANT SELECT, INSERT ON TABLE reddit_raw TO sse_scraper;

-- -----------------------------------------------
-- reddit_raw: sse_processor (SELECT only)
-- -----------------------------------------------
GRANT SELECT ON TABLE reddit_raw TO sse_processor;

-- -----------------------------------------------
-- comment_sentiment: sse_processor (SELECT, INSERT)
-- -----------------------------------------------
GRANT SELECT, INSERT ON TABLE comment_sentiment TO sse_processor;

-- -----------------------------------------------
-- ticker_sentiment_snapshot: sse_processor (SELECT, INSERT)
-- -----------------------------------------------
GRANT SELECT, INSERT ON TABLE ticker_sentiment_snapshot TO sse_processor;

-- -----------------------------------------------
-- ticker_sentiment_snapshot: sse_pricing (SELECT only)
-- -----------------------------------------------
GRANT SELECT ON TABLE ticker_sentiment_snapshot TO sse_pricing;

-- -----------------------------------------------
-- tickers: sse_pricing (SELECT only)
-- -----------------------------------------------
GRANT SELECT ON TABLE tickers TO sse_pricing;

-- -----------------------------------------------
-- pricing_parameters: sse_pricing (SELECT only)
-- -----------------------------------------------
GRANT SELECT ON TABLE pricing_parameters TO sse_pricing;

-- -----------------------------------------------
-- pricing_configurations: sse_pricing (SELECT only)
-- -----------------------------------------------
GRANT SELECT ON TABLE pricing_configurations TO sse_pricing;

-- -----------------------------------------------
-- real_prices: sse_pricing (SELECT only)
-- -----------------------------------------------
GRANT SELECT ON TABLE real_prices TO sse_pricing;

-- -----------------------------------------------
-- sentiment_prices: sse_pricing (SELECT, INSERT)
-- -----------------------------------------------
GRANT SELECT, INSERT ON TABLE sentiment_prices TO sse_pricing;

-- =============================================================================
-- Sequence Privileges (for serial/auto-increment columns)
-- =============================================================================
-- Scraper can use reddit_raw sequences
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sse_scraper;

-- Processor can use sentiment table sequences
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sse_processor;

-- Pricing can use sentiment_prices sequences
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sse_pricing;

-- Admin gets all sequence privileges
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO sse_admin;

-- =============================================================================
-- Summary of User Privileges
-- =============================================================================
-- sse_admin:
--   ALL privileges on ALL tables and sequences (migrations only)
--
-- sse_api (FastAPI):
--   SELECT on: reddit_raw, comment_sentiment, ticker_sentiment_snapshot, tickers,
--              pricing_parameters, pricing_configurations, real_prices, sentiment_prices,
--              sentiment_scores
--   Cannot INSERT, UPDATE, DELETE, or modify data
--
-- sse_scraper (Reddit Data Scraper):
--   SELECT, INSERT on: reddit_raw
--   Cannot access any other tables
--
-- sse_processor (Sentiment Processor):
--   SELECT on: reddit_raw
--   SELECT, INSERT on: comment_sentiment, ticker_sentiment_snapshot
--
-- sse_pricing (Pricing Engine):
--   SELECT on: ticker_sentiment_snapshot, tickers, pricing_parameters, pricing_configurations, real_prices
--   SELECT, INSERT on: sentiment_prices
--
-- =============================================================================

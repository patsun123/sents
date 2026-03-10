# Data Model: Resilient Reddit Sentiment Scraping Pipeline

**Phase**: 1 — Design
**Date**: 2026-03-09
**Feature**: [spec.md](spec.md) | [plan.md](plan.md) | [research.md](research.md)

---

## Overview

Four entities. No user data ever persists. The `sentiment_signals` table is the permanent source of truth — all scoring algorithms operate on it. The other tables support pipeline operation and observability.

```
data_sources          collection_runs
     │                      │
     └──────────┬───────────┘
                │
        sentiment_signals
                │
          scored_results
```

---

## Entity: DataSource

Represents a configured Reddit subreddit. Managed via configuration — no code change required to add/remove sources.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Unique source identifier |
| `subreddit_name` | VARCHAR(50) | NOT NULL, UNIQUE | Subreddit name without `r/` prefix |
| `enabled` | BOOLEAN | NOT NULL, DEFAULT true | Whether to collect from this source |
| `added_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | When source was added |
| `disabled_at` | TIMESTAMPTZ | NULLABLE | When source was disabled (null = active) |

**Indexes**: `subreddit_name` (unique), `enabled` (partial index on `enabled = true`)

**Rules**:
- Sources are never deleted — only disabled. Preserves historical audit trail.
- `subreddit_name` is lowercase, no spaces (e.g., `wallstreetbets`, not `r/wallstreetbets`)

---

## Entity: CollectionRun

A record of one complete pipeline execution cycle. One row per 15-minute run attempt.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Unique run identifier |
| `started_at` | TIMESTAMPTZ | NOT NULL | When the cycle began |
| `completed_at` | TIMESTAMPTZ | NULLABLE | When the cycle finished (null = still running or failed) |
| `status` | VARCHAR(20) | NOT NULL | `success`, `partial`, `failed` |
| `sources_attempted` | INTEGER | NOT NULL | Number of subreddits attempted |
| `sources_succeeded` | INTEGER | NOT NULL, DEFAULT 0 | Number of subreddits successfully scraped |
| `signals_stored` | INTEGER | NOT NULL, DEFAULT 0 | Total new signals written this cycle |
| `error_summary` | TEXT | NULLABLE | Human-readable failure description (no PII) |

**Indexes**: `started_at DESC` (time-ordered queries), `status` (filter by outcome)

**Status transitions**:
- Cycle starts → `status = 'failed'` (pessimistic default, updated on completion)
- All sources succeed → `status = 'success'`
- Some sources fail → `status = 'partial'`
- Cycle crashes before completion → `status = 'failed'` (default never overwritten)

**Rules**:
- `error_summary` must never contain Reddit usernames, comment text, or any PII
- One row per cycle — no updates after `status` is set (append-only)

---

## Entity: SentimentSignal

The atomic unit of storage and the algorithm-agnostic source of truth. One row per ticker mention in a comment.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Unique signal identifier |
| `collection_run_id` | UUID | FK → collection_runs.id, NOT NULL | Which cycle produced this signal |
| `ticker_symbol` | VARCHAR(10) | NOT NULL | Uppercase ticker (e.g., `GME`, `TSLA`) |
| `sentiment_polarity` | SMALLINT | NOT NULL, CHECK IN (-1, 1) | `-1` = negative, `1` = positive |
| `upvote_weight` | INTEGER | NOT NULL, DEFAULT 0, CHECK >= 0 | Comment upvote count at time of collection |
| `collected_at` | TIMESTAMPTZ | NOT NULL | Timestamp of collection (not post creation time) |
| `source_subreddit` | VARCHAR(50) | NOT NULL | Which subreddit this signal came from |

**Indexes**:
- `(ticker_symbol, collected_at DESC)` — primary query pattern for scoring
- `collection_run_id` — join to collection_runs
- `collected_at DESC` — time-range queries
- `source_subreddit` — filter by source

**Rules**:
- No comment text, comment ID, post ID, username, or any Reddit identifier is stored
- `sentiment_polarity` is binary: `-1` or `1` only. Neutral is excluded — ambiguous comments are discarded
- `upvote_weight` is captured at moment of scraping; it is not updated if upvotes change later
- Signals are immutable after insert — never updated, only inserted and queried
- `source_subreddit` is stored for future optional per-source analysis, not displayed in UI

**Volume estimate**: ~200–1,500 rows per cycle × 96 cycles/day ≈ 20,000–145,000 rows/day at initial scale

---

## Entity: ScoredResult

A derived, computed output from a scoring algorithm applied to a set of SentimentSignals. Multiple algorithms produce multiple rows for the same ticker and time window.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Unique result identifier |
| `ticker_symbol` | VARCHAR(10) | NOT NULL | Uppercase ticker |
| `algorithm_id` | VARCHAR(50) | NOT NULL | Algorithm identifier (e.g., `weighted_sum_v1`, `vader_base`) |
| `score` | NUMERIC(10, 6) | NOT NULL | Computed sentiment score (range algorithm-dependent) |
| `confidence` | NUMERIC(5, 4) | NOT NULL, CHECK BETWEEN 0 AND 1 | Volume-based: normalised mention count (0 = no data, 1 = max volume seen) |
| `mention_count` | INTEGER | NOT NULL | Number of signals used in this computation |
| `signal_window_start` | TIMESTAMPTZ | NOT NULL | Earliest signal included in computation |
| `signal_window_end` | TIMESTAMPTZ | NOT NULL | Latest signal included in computation |
| `computed_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | When this result was calculated |

**Indexes**:
- `(ticker_symbol, algorithm_id, computed_at DESC)` — primary query pattern for frontend
- `computed_at DESC` — latest results

**Rules**:
- ScoredResults are cached in Redis for API serving; PostgreSQL is the durable store
- Multiple `algorithm_id` values can coexist for the same ticker and time window — this enables algorithm comparison
- ScoredResults are derived — if algorithm changes, old results remain; new results are appended
- `confidence` is normalised against the maximum mention count observed across all tickers in the same window

---

## Disambiguation Reference (Not a DB Table)

Maintained as a versioned flat file in `worker/src/tickers/`:

- **`false_positive_blocklist.txt`**: Common English words that are valid ticker symbols (e.g., `IT`, `NOW`, `ARE`, `ON`, `FOR`, `A`, `I`). One per line. Operator-editable.
- **`ticker_universe.txt`**: Full NYSE + NASDAQ ticker list. Used to validate that extracted symbols are real listed tickers. Updated periodically.

Both files are loaded at worker startup and hot-reloaded on config change (no restart required).

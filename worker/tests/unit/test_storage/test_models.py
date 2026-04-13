"""
Unit tests for SQLAlchemy ORM models.

Verifies:
- Table name constants
- Column presence and absence (PII check)
- Default values
- Constraint names
- Relationship declarations
"""

from __future__ import annotations

from src.storage.models import (
    Base,
    CollectionRun,
    DataSource,
    ScoredResult,
    SentimentSignal,
)

# ---------------------------------------------------------------------------
# Privacy / PII assertions
# ---------------------------------------------------------------------------


def _column_names(model: type) -> set[str]:
    """Return the set of column names for a mapped model."""
    return {c.name for c in model.__table__.columns}  # type: ignore[attr-defined]


def test_sentiment_signal_has_no_pii_columns() -> None:
    """SentimentSignal must never store Reddit usernames or comment IDs."""
    forbidden = {"username", "author", "comment_id", "post_id", "user_id"}
    cols = _column_names(SentimentSignal)
    assert forbidden.isdisjoint(cols), f"PII columns found: {forbidden & cols}"


def test_collection_run_has_no_pii_columns() -> None:
    """CollectionRun must not contain user-attributable data."""
    forbidden = {"username", "author", "comment_id", "post_id", "user_id"}
    cols = _column_names(CollectionRun)
    assert forbidden.isdisjoint(cols), f"PII columns found: {forbidden & cols}"


def test_data_source_has_no_pii_columns() -> None:
    """DataSource table should only hold subreddit configuration."""
    forbidden = {"username", "author", "comment_id", "post_id", "user_id"}
    cols = _column_names(DataSource)
    assert forbidden.isdisjoint(cols), f"PII columns found: {forbidden & cols}"


# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------


def test_table_names() -> None:
    """All tables must use the names defined in contracts/schema.sql."""
    assert DataSource.__tablename__ == "data_sources"
    assert CollectionRun.__tablename__ == "collection_runs"
    assert SentimentSignal.__tablename__ == "sentiment_signals"
    assert ScoredResult.__tablename__ == "scored_results"


# ---------------------------------------------------------------------------
# Column presence
# ---------------------------------------------------------------------------


def test_data_source_columns() -> None:
    cols = _column_names(DataSource)
    assert {"id", "subreddit_name", "enabled", "added_at", "disabled_at"} <= cols


def test_collection_run_columns() -> None:
    cols = _column_names(CollectionRun)
    assert {
        "id",
        "started_at",
        "completed_at",
        "status",
        "sources_attempted",
        "sources_succeeded",
        "signals_stored",
        "error_summary",
    } <= cols


def test_sentiment_signal_columns() -> None:
    cols = _column_names(SentimentSignal)
    assert {
        "id",
        "collection_run_id",
        "ticker_symbol",
        "sentiment_polarity",
        "upvote_weight",
        "collected_at",
        "source_subreddit",
        "source_content_type",
    } <= cols


def test_scored_result_columns() -> None:
    cols = _column_names(ScoredResult)
    assert {
        "id",
        "ticker_symbol",
        "algorithm_id",
        "score",
        "confidence",
        "mention_count",
        "signal_window_start",
        "signal_window_end",
        "computed_at",
    } <= cols


# ---------------------------------------------------------------------------
# Default values (Python-side)
# ---------------------------------------------------------------------------


def test_collection_run_column_default_is_failed() -> None:
    """The 'status' column INSERT default must be 'failed' (pessimistic).

    SQLAlchemy ``default`` values are column-level INSERT defaults — they fire
    on INSERT, not on Python constructor.  Verify via the column metadata.
    """
    col = CollectionRun.__table__.c["status"]
    assert col.default is not None
    assert col.default.arg == "failed"  # type: ignore[attr-defined]


def test_data_source_column_default_enabled_is_true() -> None:
    """The 'enabled' column INSERT default must be True."""
    col = DataSource.__table__.c["enabled"]
    assert col.default is not None
    assert col.default.arg is True  # type: ignore[attr-defined]


def test_sentiment_signal_column_default_upvote_weight_zero() -> None:
    """The 'upvote_weight' column INSERT default must be 0."""
    col = SentimentSignal.__table__.c["upvote_weight"]
    assert col.default is not None
    assert col.default.arg == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Constraints (inspect __table_args__)
# ---------------------------------------------------------------------------


def _constraint_names(model: type) -> set[str]:
    return {
        c.name
        for c in model.__table__.constraints  # type: ignore[attr-defined]
        if c.name is not None
    }


def test_collection_run_status_constraint_exists() -> None:
    assert "ck_run_status" in _constraint_names(CollectionRun)


def test_sentiment_signal_polarity_constraint_exists() -> None:
    assert "ck_signal_polarity" in _constraint_names(SentimentSignal)


def test_sentiment_signal_upvotes_constraint_exists() -> None:
    assert "ck_signal_upvotes" in _constraint_names(SentimentSignal)


def test_sentiment_signal_content_type_constraint_exists() -> None:
    assert "ck_signal_content_type" in _constraint_names(SentimentSignal)


def test_scored_result_confidence_constraint_exists() -> None:
    assert "ck_scored_confidence" in _constraint_names(ScoredResult)


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


def _index_names(model: type) -> set[str]:
    return {i.name for i in model.__table__.indexes}  # type: ignore[attr-defined]


def test_sentiment_signal_indexes_exist() -> None:
    idx = _index_names(SentimentSignal)
    assert "idx_signals_ticker_time" in idx
    assert "idx_signals_run" in idx
    assert "idx_signals_collected_at" in idx
    assert "idx_signals_subreddit" in idx
    assert "idx_signals_content_type" in idx


def test_collection_run_indexes_exist() -> None:
    idx = _index_names(CollectionRun)
    assert "idx_collection_runs_started_at" in idx
    assert "idx_collection_runs_status" in idx


def test_scored_result_indexes_exist() -> None:
    idx = _index_names(ScoredResult)
    assert "idx_scored_ticker_algo_time" in idx
    assert "idx_scored_computed_at" in idx


def test_data_source_partial_index_exists() -> None:
    assert "idx_data_sources_enabled" in _index_names(DataSource)


# ---------------------------------------------------------------------------
# Base metadata
# ---------------------------------------------------------------------------


def test_base_metadata_contains_all_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert {
        "data_sources",
        "collection_runs",
        "sentiment_signals",
        "scored_results",
    } <= table_names

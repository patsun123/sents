"""
Unit tests for PIIFilter (structured JSON logging PII scrubbing).

Verifies that Reddit usernames are redacted from log messages and that
normal log messages pass through unchanged.
"""
from __future__ import annotations

import logging

import pytest

from src.logging_config import PIIFilter, configure_logging


class TestPIIFilter:
    """Tests for the PIIFilter logging filter."""

    def _make_record(self, message: str, level: int = logging.INFO) -> logging.LogRecord:
        """Create a LogRecord with the given message string."""
        record = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        return record

    def test_reddit_username_is_redacted(self) -> None:
        """Log messages containing u/Username patterns are redacted."""
        pii_filter = PIIFilter()
        record = self._make_record("Fetching comments from u/SomeRedditUser")

        pii_filter.filter(record)

        assert "SomeRedditUser" not in record.getMessage()
        assert "REDACTED" in record.getMessage()

    def test_record_without_pii_passes_through_unchanged(self) -> None:
        """Log messages without PII are emitted unchanged."""
        pii_filter = PIIFilter()
        message = "cycle_complete status=success signals_stored=42"
        record = self._make_record(message)

        pii_filter.filter(record)

        assert record.getMessage() == message

    def test_filter_always_returns_true(self) -> None:
        """PIIFilter.filter() always returns True — records are never suppressed."""
        pii_filter = PIIFilter()
        record_pii = self._make_record("u/SomeUser did something")
        record_clean = self._make_record("clean message")

        assert pii_filter.filter(record_pii) is True
        assert pii_filter.filter(record_clean) is True

    def test_multiple_pii_patterns_in_message_triggers_redaction(self) -> None:
        """A message with multiple Reddit usernames triggers redaction."""
        pii_filter = PIIFilter()
        record = self._make_record("Users u/Alice and u/Bob both upvoted")

        pii_filter.filter(record)

        assert "Alice" not in record.getMessage()
        assert "Bob" not in record.getMessage()
        assert "REDACTED" in record.getMessage()

    def test_ticker_symbol_not_mistaken_for_pii(self) -> None:
        """Ticker symbols like TSLA or GME are not redacted."""
        pii_filter = PIIFilter()
        message = "ticker_mention ticker=GME upvote_weight=100"
        record = self._make_record(message)

        pii_filter.filter(record)

        assert record.getMessage() == message

    def test_subreddit_name_not_redacted(self) -> None:
        """Subreddit names like r/wallstreetbets are NOT a PII pattern and pass through."""
        pii_filter = PIIFilter()
        message = "scraping subreddit=wallstreetbets"
        record = self._make_record(message)

        pii_filter.filter(record)

        assert record.getMessage() == message

    def test_username_pattern_boundary_detection(self) -> None:
        """Word-boundary matching — 'u/user' with surrounding context is caught."""
        pii_filter = PIIFilter()
        record = self._make_record("Found mention by u/TestUser_123 in comment")

        pii_filter.filter(record)

        assert "TestUser_123" not in record.getMessage()

    def test_username_too_short_not_redacted(self) -> None:
        """Reddit usernames shorter than 3 chars do not match the PII pattern."""
        pii_filter = PIIFilter()
        # Reddit minimum username length is 3, pattern requires 3-20
        message = "u/ab is too short to be a real username"
        record = self._make_record(message)

        pii_filter.filter(record)

        # "u/ab" has only 2 chars after 'u/' — should not match
        assert record.getMessage() == message


class TestConfigureLogging:
    """Smoke tests for configure_logging()."""

    def test_configure_logging_does_not_raise(self) -> None:
        """configure_logging() can be called without error."""
        configure_logging(level="WARNING")

    def test_configure_logging_sets_root_level(self) -> None:
        """configure_logging() configures the root logger at the given level."""
        configure_logging(level="DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_all_modules_can_log_without_raising(self, caplog: pytest.LogCaptureFixture) -> None:
        """All key modules can emit log records without exception."""
        configure_logging(level="DEBUG")

        modules_to_test = [
            "src.alerting",
            "src.logging_config",
            "src.alerting.threshold",
            "src.pipeline.runner",
        ]
        with caplog.at_level(logging.DEBUG):
            for module_name in modules_to_test:
                module_logger = logging.getLogger(module_name)
                # Should not raise
                module_logger.debug("smoke_test module=%s", module_name)

    def test_pii_filter_attached_to_root_handler(self) -> None:
        """After configure_logging(), the root handler has a PIIFilter attached."""
        configure_logging(level="INFO")
        root_logger = logging.getLogger()
        assert root_logger.handlers, "Root logger must have at least one handler"
        handler = root_logger.handlers[0]
        pii_filters = [f for f in handler.filters if isinstance(f, PIIFilter)]
        assert pii_filters, "PIIFilter must be attached to the console handler"

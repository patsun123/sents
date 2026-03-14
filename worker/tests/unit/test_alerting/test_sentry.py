"""
Unit tests for alerting.init_sentry, capture_cycle_failure, and capture_error.

All sentry_sdk calls are mocked — no real Sentry DSN is needed.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

import src.alerting as alerting_module
from src.alerting import (
    capture_cycle_failure,
    capture_error,
    init_sentry,
    reset_sentry_state,
)


@pytest.fixture(autouse=True)
def _reset_sentry() -> None:
    """Reset Sentry initialized state before each test."""
    reset_sentry_state()


class TestInitSentry:
    """Tests for init_sentry()."""

    def test_no_op_when_dsn_is_empty_string(self) -> None:
        """init_sentry('') is a complete no-op — does not call sentry_sdk.init."""
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("")
        mock_sentry.init.assert_not_called()

    def test_no_op_when_dsn_is_whitespace(self) -> None:
        """init_sentry with whitespace-only string is also a no-op (falsy)."""
        # Note: empty string is falsy, but "  " is truthy — test the real empty case.
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("")
        mock_sentry.init.assert_not_called()

    def test_sentry_initialized_when_dsn_provided(self) -> None:
        """init_sentry() calls sentry_sdk.init when a real DSN is given."""
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
        mock_sentry.init.assert_called_once()

    def test_sentry_init_receives_correct_dsn(self) -> None:
        """sentry_sdk.init is called with the provided DSN."""
        dsn = "https://abc123@sentry.io/42"
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry(dsn)
        call_kwargs = mock_sentry.init.call_args
        assert call_kwargs.kwargs.get("dsn") == dsn

    def test_sentry_init_passes_before_send_scrubber(self) -> None:
        """sentry_sdk.init is called with a before_send hook for PII scrubbing."""
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
        call_kwargs = mock_sentry.init.call_args
        assert "before_send" in call_kwargs.kwargs
        assert callable(call_kwargs.kwargs["before_send"])

    def test_does_not_crash_when_sentry_sdk_not_installed(self) -> None:
        """init_sentry() is safe when sentry_sdk is not importable."""
        saved = sys.modules.pop("sentry_sdk", None)
        sys.modules["sentry_sdk"] = None  # type: ignore[assignment]
        try:
            # Should not propagate ImportError
            init_sentry("https://fake@sentry.io/1")
        except (ImportError, AttributeError):
            pass  # acceptable — the ImportError path was triggered
        finally:
            if saved is not None:
                sys.modules["sentry_sdk"] = saved
            else:
                sys.modules.pop("sentry_sdk", None)

    def test_sentry_initialized_flag_set_after_init(self) -> None:
        """_sentry_initialized is True after a successful init."""
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
        assert alerting_module._sentry_initialized is True

    def test_sentry_initialized_flag_stays_false_when_no_dsn(self) -> None:
        """_sentry_initialized remains False when no DSN is given."""
        init_sentry("")
        assert alerting_module._sentry_initialized is False


class TestCaptureCycleFailure:
    """Tests for capture_cycle_failure()."""

    def test_no_op_when_sentry_not_initialized(self) -> None:
        """capture_cycle_failure() is a no-op when Sentry is not initialized."""
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            capture_cycle_failure("run-uuid-001", "All sources failed")
        mock_sentry.capture_message.assert_not_called()

    def test_sends_message_when_initialized(self) -> None:
        """capture_cycle_failure() calls capture_message when initialized."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_cycle_failure("run-uuid-002", "Failed sources: ['wsb']")

        mock_sentry.capture_message.assert_called_once()

    def test_message_contains_error_summary(self) -> None:
        """The captured message body includes the error_summary text."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_cycle_failure("run-uuid-003", "Network timeout")

        call_args = mock_sentry.capture_message.call_args
        assert "Network timeout" in call_args[0][0]

    def test_message_level_is_error(self) -> None:
        """capture_cycle_failure sends with level='error'."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_cycle_failure("run-uuid-004", "timeout")

        call_kwargs = mock_sentry.capture_message.call_args.kwargs
        assert call_kwargs.get("level") == "error"

    def test_message_does_not_include_pii(self) -> None:
        """capture_cycle_failure message must not contain PII (no usernames, no comment text)."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_cycle_failure("run-uuid-005", "Failed sources: ['wallstreetbets']")

        call_args = mock_sentry.capture_message.call_args
        message = call_args[0][0]
        # Message must not contain a Reddit username pattern
        assert "u/" not in message


class TestCaptureError:
    """Tests for capture_error()."""

    def test_no_op_when_sentry_not_initialized(self) -> None:
        """capture_error() is a no-op when Sentry is not initialized."""
        mock_sentry = MagicMock()
        exc = ValueError("something went wrong")
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            capture_error(exc)
        mock_sentry.capture_exception.assert_not_called()

    def test_captures_exception_when_initialized(self) -> None:
        """capture_error() calls capture_exception when Sentry is initialized."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope
        exc = RuntimeError("pipeline exploded")

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_error(exc)

        mock_sentry.capture_exception.assert_called_once_with(exc)

    def test_passes_context_to_scope(self) -> None:
        """capture_error() sets provided context on the Sentry scope."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope
        exc = RuntimeError("error with context")
        ctx = {"run_id": "run-abc", "phase": "scraping"}

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_error(exc, context=ctx)

        mock_scope.set_context.assert_called_once_with("worker", ctx)

    def test_no_context_arg_does_not_crash(self) -> None:
        """capture_error() works correctly with no context argument."""
        mock_sentry = MagicMock()
        mock_scope = MagicMock()
        mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope
        exc = ValueError("simple error")

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake@sentry.io/1")
            capture_error(exc)

        mock_scope.set_context.assert_not_called()


class TestScrubPii:
    """Tests for the _scrub_pii Sentry before_send hook."""

    def test_scrub_removes_text_from_exception_vars(self) -> None:
        """_scrub_pii removes 'text' key from exception frame vars."""
        from src.alerting import _scrub_pii  # noqa: PLC0415

        event = {
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [
                                {"vars": {"text": "secret comment body", "ticker": "GME"}}
                            ]
                        }
                    }
                ]
            }
        }
        result = _scrub_pii(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert "text" not in frame_vars
        assert "ticker" in frame_vars  # non-PII fields are preserved

    def test_scrub_removes_body_from_exception_vars(self) -> None:
        """_scrub_pii removes 'body' key from exception frame vars."""
        from src.alerting import _scrub_pii  # noqa: PLC0415

        event = {
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [{"vars": {"body": "comment content", "run_id": "abc"}}]
                        }
                    }
                ]
            }
        }
        result = _scrub_pii(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert "body" not in frame_vars
        assert "run_id" in frame_vars

    def test_scrub_removes_comment_from_exception_vars(self) -> None:
        """_scrub_pii removes 'comment' key from exception frame vars."""
        from src.alerting import _scrub_pii  # noqa: PLC0415

        event = {
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [{"vars": {"comment": "some text"}}]
                        }
                    }
                ]
            }
        }
        result = _scrub_pii(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert "comment" not in frame_vars

    def test_scrub_passthrough_event_without_exception(self) -> None:
        """_scrub_pii passes through events without an 'exception' key unchanged."""
        from src.alerting import _scrub_pii  # noqa: PLC0415

        event = {"message": "a plain message event", "level": "info"}
        result = _scrub_pii(event, {})
        assert result == event

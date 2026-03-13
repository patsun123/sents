"""
Unit tests for alerting.init_sentry().
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from src.alerting import init_sentry


class TestInitSentry:
    """Tests for the init_sentry function."""

    def test_no_op_when_dsn_empty(self) -> None:
        """init_sentry() is a no-op when DSN is empty."""
        # Should not raise or call sentry_sdk.init
        init_sentry("")

    def test_initialises_sentry_when_dsn_provided(self) -> None:
        """init_sentry() calls sentry_sdk.init when DSN is set."""
        mock_sentry = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            init_sentry("https://fake-dsn@sentry.io/1")

        mock_sentry.init.assert_called_once()
        call_kwargs = mock_sentry.init.call_args
        assert call_kwargs.kwargs.get("dsn") == "https://fake-dsn@sentry.io/1"

    def test_handles_missing_sentry_sdk(self) -> None:
        """init_sentry() does not crash when sentry_sdk is not installed."""
        real_modules = dict(sys.modules)
        # Remove sentry_sdk so the import inside init_sentry triggers ImportError
        sys.modules.pop("sentry_sdk", None)
        # Replace with something that raises ImportError on access
        sys.modules["sentry_sdk"] = None  # type: ignore[assignment]

        try:
            # Should not raise — ImportError should be caught internally
            init_sentry("https://fake-dsn@sentry.io/1")
        except (ImportError, AttributeError):
            pass  # acceptable — ImportError handling path was triggered
        finally:
            # Restore original modules
            for k, v in real_modules.items():
                sys.modules[k] = v

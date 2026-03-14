"""
Unit tests for AlertThresholdTracker.

Verifies the alert fires at exactly the right count, resets correctly,
and uses the injected alert function (never calls real Sentry).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.alerting.threshold import AlertThresholdTracker


class TestAlertThresholdTracker:
    """Tests for AlertThresholdTracker."""

    def test_no_alert_below_threshold(self) -> None:
        """Alert function is NOT called when failures < threshold."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=3, alert_fn=alert_fn)

        tracker.record_failure("run-001", "source failed")
        tracker.record_failure("run-002", "source failed")

        alert_fn.assert_not_called()

    def test_alert_fires_at_threshold(self) -> None:
        """Alert function IS called on the Nth consecutive failure (not N-1, not N+1)."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=3, alert_fn=alert_fn)

        tracker.record_failure("run-001", "err")
        tracker.record_failure("run-002", "err")
        tracker.record_failure("run-003", "err")  # Nth failure

        alert_fn.assert_called_once()

    def test_alert_fires_with_correct_arguments(self) -> None:
        """Alert function receives the run_id and error_summary of the Nth failure."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=2, alert_fn=alert_fn)

        tracker.record_failure("run-A", "error one")
        tracker.record_failure("run-B", "error two")  # triggers alert

        call_args = alert_fn.call_args
        assert call_args[0][0] == "run-B"
        assert "error two" in call_args[0][1]

    def test_alert_fires_again_on_subsequent_failures_past_threshold(self) -> None:
        """Alert fires on EVERY failure once threshold is reached (not just once total)."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=2, alert_fn=alert_fn)

        tracker.record_failure("run-1", "err")
        tracker.record_failure("run-2", "err")  # 2nd — fires
        tracker.record_failure("run-3", "err")  # 3rd — fires again

        assert alert_fn.call_count == 2

    def test_record_success_resets_counter(self) -> None:
        """record_success() resets the consecutive failure counter to zero."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=3, alert_fn=alert_fn)

        tracker.record_failure("run-001", "err")
        tracker.record_failure("run-002", "err")
        tracker.record_success()  # reset

        assert tracker.consecutive_failures == 0

    def test_failures_after_reset_restart_from_zero(self) -> None:
        """Failures recorded after a reset are counted from zero again."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=3, alert_fn=alert_fn)

        tracker.record_failure("run-001", "err")
        tracker.record_failure("run-002", "err")
        tracker.record_success()  # reset

        tracker.record_failure("run-003", "err")
        tracker.record_failure("run-004", "err")

        # Only 2 failures since reset — should not have fired yet
        alert_fn.assert_not_called()

    def test_alert_fires_after_reset_and_new_failures(self) -> None:
        """Alert fires correctly after a reset when threshold is reached again."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=2, alert_fn=alert_fn)

        # First wave: trigger once
        tracker.record_failure("r1", "e")
        tracker.record_failure("r2", "e")
        assert alert_fn.call_count == 1

        tracker.record_success()

        # Second wave: trigger again
        tracker.record_failure("r3", "e")
        tracker.record_failure("r4", "e")
        assert alert_fn.call_count == 2

    def test_consecutive_failures_property(self) -> None:
        """consecutive_failures property returns the current count."""
        tracker = AlertThresholdTracker(threshold=10, alert_fn=MagicMock())

        assert tracker.consecutive_failures == 0
        tracker.record_failure("r1", "e")
        assert tracker.consecutive_failures == 1
        tracker.record_failure("r2", "e")
        assert tracker.consecutive_failures == 2
        tracker.record_success()
        assert tracker.consecutive_failures == 0

    def test_threshold_of_one_fires_on_first_failure(self) -> None:
        """With threshold=1, the alert fires on the very first failure."""
        alert_fn = MagicMock()
        tracker = AlertThresholdTracker(threshold=1, alert_fn=alert_fn)

        tracker.record_failure("run-X", "immediate failure")

        alert_fn.assert_called_once()

    def test_multiple_successes_keep_counter_at_zero(self) -> None:
        """Multiple record_success() calls are idempotent — counter stays at 0."""
        tracker = AlertThresholdTracker(threshold=3, alert_fn=MagicMock())

        tracker.record_success()
        tracker.record_success()
        tracker.record_success()

        assert tracker.consecutive_failures == 0

"""
Alert threshold tracker for SentiX Worker.

Tracks consecutive cycle failures and fires an alert when the threshold
is reached.  Alert functions are injected at construction time so the
tracker is fully testable without real Sentry calls.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class AlertThresholdTracker:
    """
    Track consecutive cycle failures and fire alerts at a configurable threshold.

    The tracker is stateful per-process — it counts consecutive failures and
    fires the alert function exactly once each time the threshold is hit (not
    once total; every subsequent failure past the threshold also fires).

    Args:
        threshold: Number of consecutive failures required before alerting.
        alert_fn: Callable invoked with ``(run_id, error_summary)`` when the
                  threshold is reached.  Must be a no-op when Sentry is not
                  initialised.
    """

    def __init__(self, threshold: int, alert_fn: Callable[[str, str], None]) -> None:
        self._threshold = threshold
        self._alert_fn = alert_fn
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        """Return the current consecutive failure count."""
        return self._consecutive_failures

    def record_success(self) -> None:
        """
        Reset the consecutive failure counter after a successful cycle.

        This must be called from ``CycleRunner`` when a cycle completes with
        status ``'success'`` or ``'partial'`` (any non-failed outcome).
        """
        self._consecutive_failures = 0

    def record_failure(self, run_id: str, error_summary: str) -> None:
        """
        Increment the failure counter and fire an alert if the threshold is met.

        Args:
            run_id: UUID of the failed :class:`~storage.models.CollectionRun`.
            error_summary: Human-readable description of the failure.
                           Must not contain PII (usernames, comment text, etc.).
        """
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._alert_fn(run_id, error_summary)
            logger.error(
                "alert_threshold_exceeded",
                extra={
                    "consecutive_failures": self._consecutive_failures,
                    "threshold": self._threshold,
                    "run_id": run_id,
                },
            )

"""
Alerting: Sentry integration for SSE worker.

Initialises Sentry SDK if a DSN is configured.  When ``sentry_dsn`` is
empty (local development), this module is a no-op.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def init_sentry(dsn: str) -> None:
    """
    Initialise the Sentry SDK.

    If ``dsn`` is empty, Sentry is disabled and a debug log is emitted.
    This allows the worker to run in local development without requiring
    a Sentry account.

    Args:
        dsn: Sentry project DSN.  An empty string disables Sentry.
    """
    if not dsn:
        logger.debug("Sentry DSN not configured — alerting disabled.")
        return

    try:
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.init(
            dsn=dsn,
            # Capture 100% of errors; adjust traces_sample_rate for performance data
            traces_sample_rate=0.0,
        )
        logger.info("Sentry initialised.")
    except ImportError:
        logger.warning(
            "sentry-sdk is not installed — Sentry alerting disabled. "
            "Install sentry-sdk to enable error reporting."
        )

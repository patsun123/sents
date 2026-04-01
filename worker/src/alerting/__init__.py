"""
Alerting module: Sentry integration for SentiX Worker.

If SENTRY_DSN is not set, all functions are no-ops.
Never include Reddit usernames, comment bodies, or PII in any event.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_sentry_initialized = False


def _scrub_pii(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """
    Remove any accidentally included PII from Sentry events.

    This is a safety net — PII should never reach here because it is never
    stored. Belt-and-suspenders for the most sensitive compliance requirement.

    Args:
        event: Sentry event dictionary.
        hint: Sentry hint dictionary (unused).

    Returns:
        Sanitized event dictionary.
    """
    if "exception" in event:
        for exc in event["exception"].get("values", []):
            for frame in exc.get("stacktrace", {}).get("frames", []):
                vars_ = frame.get("vars", {})
                vars_.pop("text", None)
                vars_.pop("body", None)
                vars_.pop("comment", None)
    return event


def init_sentry(dsn: str) -> None:
    """
    Initialize Sentry SDK. No-op if DSN is empty or absent.

    Args:
        dsn: Sentry DSN from SENTRY_DSN env var. Empty string disables Sentry.
    """
    global _sentry_initialized
    if not dsn:
        logger.info("sentry_disabled reason=no_dsn_configured")
        return

    try:
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.1,
            before_send=_scrub_pii,  # type: ignore[arg-type]
        )
        _sentry_initialized = True
        logger.info("sentry_initialized")
    except ImportError:
        logger.warning(
            "sentry_sdk_not_installed — alerting disabled. "
            "Install sentry-sdk to enable error reporting."
        )


def capture_cycle_failure(run_id: str, error_summary: str) -> None:
    """
    Send a cycle failure event to Sentry.

    Args:
        run_id: UUID of the failed CollectionRun.
        error_summary: Human-readable description. Must not contain PII.
    """
    if not _sentry_initialized:
        return
    import sentry_sdk  # noqa: PLC0415

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("event_type", "cycle_failure")
        scope.set_context("run", {"run_id": run_id, "error_summary": error_summary})
        sentry_sdk.capture_message(
            f"Pipeline cycle failed: {error_summary}",
            level="error",
        )


def capture_error(exc: Exception, context: dict | None = None) -> None:  # type: ignore[type-arg]
    """
    Capture an arbitrary exception in Sentry.

    Args:
        exc: The exception to capture.
        context: Optional dict of additional context (must not contain PII).
    """
    if not _sentry_initialized:
        return
    import sentry_sdk  # noqa: PLC0415

    with sentry_sdk.push_scope() as scope:
        if context:
            scope.set_context("worker", context)
        sentry_sdk.capture_exception(exc)


def reset_sentry_state() -> None:
    """
    Reset the module-level Sentry initialization flag.

    This is intended for use in tests only, to allow re-testing init_sentry().
    """
    global _sentry_initialized
    _sentry_initialized = False

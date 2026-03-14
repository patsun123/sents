"""
Structured JSON logging configuration for SSE Worker.

All log records are emitted as JSON. PII fields are blocked
by a custom log filter at the root logger level.

Usage::

    from src.logging_config import configure_logging
    configure_logging(level="INFO")
"""
from __future__ import annotations

import logging
import logging.config
import re

# Patterns that indicate potential PII in log messages.
# Belt-and-suspenders — no PII should ever be logged, but this is a safety net.
_PII_PATTERNS = [
    re.compile(r"\bu/[A-Za-z0-9_-]{3,20}\b"),  # Reddit usernames e.g. u/SomeUser
]


class PIIFilter(logging.Filter):
    """
    Block log records containing potential PII patterns.

    Matches known PII patterns (e.g. Reddit usernames) in the formatted log
    message and replaces them with a redaction notice. The record is still
    emitted — it is never silently dropped — so operational visibility is
    preserved while PII is scrubbed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Inspect the formatted message and redact any PII.

        Args:
            record: The log record to inspect.

        Returns:
            Always ``True`` — records are never suppressed, only sanitized.
        """
        message = record.getMessage()
        for pattern in _PII_PATTERNS:
            if pattern.search(message):
                record.msg = "[REDACTED: potential PII detected in log message]"
                record.args = ()
                break
        return True


def configure_logging(level: str = "INFO") -> None:
    """
    Configure structured JSON logging for the worker.

    Sets up a root logger that emits JSON-formatted records via a
    :class:`PIIFilter`-protected :class:`logging.StreamHandler`.

    Falls back to plain-text formatting when ``python-json-logger`` is not
    installed (e.g. during local development without the full dependency set).

    Args:
        level: Log level string — one of ``DEBUG``, ``INFO``, ``WARNING``,
               ``ERROR``, or ``CRITICAL``.  Case-insensitive.
    """
    try:
        # Verify python-json-logger is importable before passing it to dictConfig.
        import pythonjsonlogger.jsonlogger  # noqa: PLC0415, F401

        formatter_class = "pythonjsonlogger.jsonlogger.JsonFormatter"
    except ImportError:
        formatter_class = "logging.Formatter"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "pii_filter": {"()": f"{__name__}.PIIFilter"},
            },
            "formatters": {
                "json": {
                    "()": formatter_class,
                    "fmt": "%(asctime)s %(name)s %(levelname)s %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%SZ",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "filters": ["pii_filter"],
                },
            },
            "root": {
                "level": level.upper(),
                "handlers": ["console"],
            },
        }
    )

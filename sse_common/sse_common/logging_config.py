"""
Centralised logging configuration for all SSE services.
Call configure_logging(service_name) once at application startup.
"""
from __future__ import annotations

import logging
import sys
from typing import Any


class _JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import traceback

        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extra_keys = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "id", "levelname", "levelno",
                "lineno", "module", "msecs", "message", "msg", "name",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName", "service",
            }
        }
        if extra_keys:
            payload["extra"] = extra_keys

        return json.dumps(payload, default=str)


class _ServiceFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self._service
        return True


def configure_logging(
    service_name: str,
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    """
    Configure root logger for an SSE service.

    Args:
        service_name: Identifier injected into every log record (e.g. "scraper").
        level: Log level string — INFO, DEBUG, WARNING, ERROR.
        json_output: If True, emit JSON. If False, emit human-readable (for local dev).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ServiceFilter(service_name))

    if json_output:
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s (%(service)s): %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "asyncio", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

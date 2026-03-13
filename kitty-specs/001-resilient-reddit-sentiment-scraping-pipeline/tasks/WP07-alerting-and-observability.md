---
work_package_id: WP07
title: Alerting & Observability
lane: "doing"
dependencies: [WP06]
base_branch: 001-resilient-reddit-sentiment-scraping-pipeline-WP06
base_commit: 9df8f58bdd2dee34d9306bfdab899bfccdcf422e
created_at: '2026-03-13T20:31:56.879516+00:00'
subtasks:
- T034
- T035
- T036
- T037
- T038
phase: Phase 3 - Operational Safety
assignee: ''
agent: ''
shell_pid: "11956"
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-03-09T19:41:43Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
requirement_refs:
- FR-009
- FR-010
---

# Work Package Prompt: WP07 - Alerting & Observability

## Objectives & Success Criteria

- Sentry captures unhandled exceptions and cycle failures; no-ops gracefully when `SENTRY_DSN` is absent
- All log output is structured JSON (no plain text logs in production)
- Log records NEVER contain Reddit usernames, comment text, or any PII
- Error threshold alert fires to Sentry when N consecutive cycles fail (N = `ALERT_THRESHOLD`, default 3)
- Docker health check reports unhealthy when no successful cycle has run in the last 20 minutes
- All alerting behaviour verified by unit tests with mocked Sentry SDK

## Context & Constraints

- **Spec**: FR-009 (logging), FR-010 (alerting)
- **Constitution**: Sentry for error alerting; structured logging throughout; no 24/7 monitoring required
- **Solo project**: Alerts come TO the developer; the system is otherwise self-healing
- **CRITICAL**: No PII in any log record at any level — not even in DEBUG logs

**Implementation command**: `spec-kitty implement WP07 --base WP06`

---

## Subtasks & Detailed Guidance

### Subtask T034 - Sentry integration

**Purpose**: Capture unhandled exceptions and deliberate cycle failure events. Absent DSN = no-op (safe for local dev).

**Steps**:
1. Create `worker/src/alerting/__init__.py`:

```python
"""
Alerting module: Sentry integration for SSE Worker.

If SENTRY_DSN is not set, all functions are no-ops.
Never include Reddit usernames, comment bodies, or PII in any event.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_sentry_initialized = False


def init_sentry(dsn: str) -> None:
    """
    Initialize Sentry SDK. No-op if DSN is empty or absent.

    Args:
        dsn: Sentry DSN from SENTRY_DSN env var.
    """
    global _sentry_initialized
    if not dsn:
        logger.info("sentry_disabled", reason="no_dsn_configured")
        return

    import sentry_sdk
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,
        before_send=_scrub_pii,
    )
    _sentry_initialized = True
    logger.info("sentry_initialized")


def _scrub_pii(event: dict, hint: dict) -> dict:
    """
    Remove any accidentally included PII from Sentry events.

    This is a safety net -- PII should never reach here, but
    belt-and-suspenders for the most sensitive compliance requirement.
    """
    # Remove any 'text' or 'body' fields from exception locals
    if "exception" in event:
        for exc in event["exception"].get("values", []):
            for frame in exc.get("stacktrace", {}).get("frames", []):
                frame.get("vars", {}).pop("text", None)
                frame.get("vars", {}).pop("body", None)
                frame.get("vars", {}).pop("comment", None)
    return event


def capture_cycle_failure(run_id: str, error_summary: str) -> None:
    """
    Send a cycle failure event to Sentry.

    Args:
        run_id: UUID of the failed CollectionRun.
        error_summary: Human-readable description. Must not contain PII.
    """
    if not _sentry_initialized:
        return
    import sentry_sdk
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("event_type", "cycle_failure")
        scope.set_context("run", {"run_id": run_id, "error_summary": error_summary})
        sentry_sdk.capture_message(
            f"Pipeline cycle failed: {error_summary}",
            level="error",
        )


def capture_error(exc: Exception, context: dict | None = None) -> None:
    """Capture an arbitrary exception in Sentry."""
    if not _sentry_initialized:
        return
    import sentry_sdk
    with sentry_sdk.push_scope() as scope:
        if context:
            scope.set_context("worker", context)
        sentry_sdk.capture_exception(exc)
```

**Files**: `worker/src/alerting/__init__.py`

---

### Subtask T035 - Structured JSON logging

**Purpose**: Every log record is a JSON object — machine-parseable, no PII, consistent fields across all modules.

**Steps**:
1. Create `worker/src/logging_config.py`:

```python
"""
Structured JSON logging configuration for SSE Worker.

All log records are emitted as JSON. PII fields are blocked
by a custom log filter at the root logger level.
"""
from __future__ import annotations

import logging
import logging.config
import re


_PII_PATTERNS = [
    re.compile(r"\bu/[A-Za-z0-9_-]{3,20}\b"),  # Reddit usernames
]


class PIIFilter(logging.Filter):
    """Block log records containing potential PII patterns."""

    def filter(self, record: logging.LogRecord) -> bool:
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

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
    """
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "pii_filter": {"()": PIIFilter},
        },
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
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
            "level": level,
            "handlers": ["console"],
        },
    })
```

2. Update `worker/src/main.py` to call `configure_logging(settings.log_level)` at startup

3. Audit all existing modules: replace any `logger.info(f"fetching {comment.text}")` patterns with structured calls:
   ```python
   # WRONG:
   logger.info(f"Processing comment: {comment.text}")

   # CORRECT:
   logger.info("processing_comment", extra={"ticker_count": len(candidates)})
   ```

**Files**: `worker/src/logging_config.py`, audit all `worker/src/` modules for logging calls

---

### Subtask T036 - Error threshold alerting

**Purpose**: Fire a Sentry alert when N consecutive cycles fail. Prevents silent degradation where the pipeline is broken but no one knows.

**Steps**:
1. Add consecutive failure tracking to `CycleRunner` (or a separate `AlertThresholdTracker`):

```python
class AlertThresholdTracker:
    """Track consecutive cycle failures and fire alerts at threshold."""

    def __init__(self, threshold: int, alert_fn) -> None:
        self._threshold = threshold
        self._alert_fn = alert_fn
        self._consecutive_failures = 0

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self, run_id: str, error_summary: str) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._alert_fn(run_id, error_summary)
            logger.error(
                "alert_threshold_exceeded",
                consecutive_failures=self._consecutive_failures,
                threshold=self._threshold,
            )
```

2. Instantiate `AlertThresholdTracker` in `main.py` and pass to `CycleRunner`
3. `CycleRunner.run_cycle()` calls `tracker.record_success()` or `tracker.record_failure()` based on run outcome

**Files**: `worker/src/alerting/threshold.py` (new), `worker/src/pipeline/runner.py` (integrate tracker)

---

### Subtask T037 - Docker health check

**Purpose**: Docker reports the container as unhealthy if no successful cycle has run recently, enabling Docker Compose to restart it automatically.

**Steps**:
1. Add health file writing to `CycleRunner.run_cycle()`:
   ```python
   # After successful commit:
   if status in ("success", "partial"):
       Path(".health").write_text(str(datetime.now(tz=timezone.utc).isoformat()))
   ```

2. Verify Dockerfile `HEALTHCHECK` (from WP01 T002):
   ```dockerfile
   HEALTHCHECK --interval=20m --timeout=10s --retries=3 --start-period=60s \
     CMD python -c "import os, time; f='.health'; \
       assert os.path.exists(f) and time.time()-os.path.getmtime(f) < 1200, \
       'No successful cycle in last 20 minutes'"
   ```
   - `1200` seconds = 20 minutes (one interval + 5 minutes grace)
   - File must exist AND be recent

3. Ensure `.health` file is created in the container's working directory (`/app/`)

**Files**: `worker/src/pipeline/runner.py` (health file write), `worker/Dockerfile` (verify HEALTHCHECK)

---

### Subtask T038 - Alerting unit tests

**Purpose**: Verify alert fires at the correct threshold, Sentry is mocked (never real calls in CI), and PII filter blocks Reddit usernames.

**Steps**:
1. Create `worker/tests/unit/test_alerting/test_sentry.py`:
   - Mock `sentry_sdk.capture_message` and `sentry_sdk.capture_exception`
   - Test: `init_sentry("")` is a no-op (no sentry_sdk import attempted)
   - Test: `capture_cycle_failure()` calls `sentry_sdk.capture_message` when initialized
   - Test: `capture_cycle_failure()` is a no-op when not initialized

2. Create `worker/tests/unit/test_alerting/test_threshold.py`:
   - Test: `record_failure()` called 2 times (threshold=3): no alert
   - Test: `record_failure()` called 3 times (threshold=3): alert fires once
   - Test: `record_success()` resets counter; failures after reset restart from 0

3. Create `worker/tests/unit/test_alerting/test_pii_filter.py`:
   - Test: log message containing `u/SomeRedditUsername` is redacted
   - Test: log message with no PII passes through unchanged
   - Test: all modules can log without raising (smoke test)

**Files**: `worker/tests/unit/test_alerting/test_sentry.py`, `test_threshold.py`, `test_pii_filter.py`

---

## Test Strategy

- `sentry_sdk` is NEVER called in tests — always mocked with `unittest.mock.patch`
- PII filter test uses `caplog` to inspect sanitized output
- Run: `pytest tests/unit/test_alerting/ -v`

## Risks & Mitigations

- **PII in Sentry events**: `_scrub_pii` is belt-and-suspenders; PII should never reach Sentry because it's never stored, but the scrubber is a safety net
- **Health file path**: Must match Dockerfile `WORKDIR`. Use `Path(__file__).parent.parent.parent / ".health"` or configure via env var

## Review Guidance

- Verify `init_sentry("")` does not crash and does not import `sentry_sdk`
- Verify `capture_cycle_failure()` does not include any subreddit comment content
- Verify alert fires on the Nth failure (not N+1, not N-1)
- Verify `record_success()` resets the consecutive failure counter
- Verify no log record in the entire test suite contains a mock Reddit username

## Activity Log

- 2026-03-09T19:41:43Z - system - lane=planned - Prompt created.

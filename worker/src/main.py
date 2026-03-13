"""
SSE Worker entry point.

Startup sequence:
  1. Load and validate settings
  2. Configure structured logging
  3. Initialise Sentry (if DSN configured)
  4. Build async SQLAlchemy session factory
  5. Run Alembic migrations (ensures schema is current)
  6. Seed default data sources (if table is empty)
  7. Initialise classifier (validate it is ready)
  8. Build CycleRunner, CycleQueue, and Scheduler
  9. Start APScheduler
  10. Run asyncio event loop until SIGTERM

Shutdown sequence (SIGTERM):
  1. Signal stop event
  2. Scheduler shuts down (wait=True lets current job finish)
  3. Process exits 0
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .alerting import init_sentry
from .classifiers import get_classifier
from .config import Settings, get_settings
from .pipeline.queue import CycleQueue
from .pipeline.runner import CycleRunner
from .pipeline.scheduler import create_scheduler
from .scrapers.json_endpoint import JsonEndpointScraper
from .scrapers.praw_oauth import PRAWOAuthScraper
from .storage.models import DataSource
from .tickers.disambiguator import TickerDisambiguator
from .tickers.extractor import TickerExtractor

logger = logging.getLogger(__name__)

_DEFAULT_SUBREDDITS = ["wallstreetbets", "stocks", "investing"]

_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (compatible; SSEWorker/1.0; +https://github.com/sse-worker)",
    "Mozilla/5.0 (X11; Linux x86_64) SSEWorker/1.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SSEWorker/1.0",
]


def _configure_logging(log_level: str) -> None:
    """Configure structured logging.

    Uses python-json-logger for JSON output if available; falls back to
    plain-text logging for local development without the dependency.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    try:
        import pythonjsonlogger.jsonlogger as _jl  # noqa: PLC0415

        formatter = _jl.JsonFormatter(  # type: ignore[attr-defined]
            "%(asctime)s %(name)s %(levelname)s %(message)s"
        )
        handler.setFormatter(formatter)
    except (ImportError, AttributeError):
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


async def _run_migrations(database_url: str) -> None:
    """
    Run Alembic migrations programmatically.

    Ensures the database schema is current before the worker starts
    accepting cycles.  Runs in a subprocess to avoid asyncpg/alembic
    event-loop conflicts.

    Args:
        database_url: Async database URL (with +asyncpg driver).
    """
    import os  # noqa: PLC0415
    import subprocess  # noqa: S404, PLC0415  # nosec B404

    env = dict(os.environ)
    env["DATABASE_URL"] = database_url

    result = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("migration_failed stderr=%s stdout=%s", result.stderr, result.stdout)
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")
    logger.info("migrations_applied output=%s", result.stdout.strip())


async def _seed_default_sources(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """
    Insert default subreddits if the data_sources table is empty.

    This is idempotent — if sources already exist, nothing happens.

    Args:
        session_factory: Factory for async database sessions.
    """
    from sqlalchemy import func, select  # noqa: PLC0415

    async with session_factory() as session:
        count_result = await session.execute(select(func.count()).select_from(DataSource))
        count = count_result.scalar_one()

        if count == 0:
            for subreddit_name in _DEFAULT_SUBREDDITS:
                session.add(DataSource(subreddit_name=subreddit_name))
            await session.commit()
            logger.info("default_sources_seeded subreddits=%s", _DEFAULT_SUBREDDITS)
        else:
            logger.debug("sources_already_exist count=%d", count)


async def main() -> None:
    """
    Wire all components together and run the scheduler until SIGTERM.

    This is the main async entry point.  It handles startup, runs the
    event loop, and ensures graceful shutdown on SIGTERM.
    """
    settings: Settings = get_settings()

    _configure_logging(settings.log_level)
    init_sentry(settings.sentry_dsn)

    logger.info("worker_starting log_level=%s", settings.log_level)

    # Build async engine + session factory
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Run migrations before anything else
    await _run_migrations(settings.database_url)

    # Seed default sources if table is empty
    await _seed_default_sources(session_factory)

    # Initialise classifier
    classifier = get_classifier()
    if not classifier.is_ready():
        raise RuntimeError("Classifier failed to initialise — cannot start worker.")
    logger.info("classifier_ready backend=%s", settings.classifier_backend)

    # Build scraper instances
    primary_scraper = JsonEndpointScraper(
        user_agents=_DEFAULT_USER_AGENTS,
        request_delay_seconds=1.0,
    )
    fallback_scraper = PRAWOAuthScraper()

    # Build extractor and disambiguator
    extractor = TickerExtractor()
    disambiguator = TickerDisambiguator()

    # Build CycleRunner
    runner = CycleRunner(
        settings=settings,
        session_factory=session_factory,
        classifier=classifier,
        primary_scraper=primary_scraper,
        fallback_scraper=fallback_scraper,
        extractor=extractor,
        disambiguator=disambiguator,
    )

    # Build CycleQueue (in-process sequential execution guard)
    cycle_queue = CycleQueue()

    async def run_cycle_job() -> None:
        """Callback invoked by APScheduler every interval."""
        await cycle_queue.submit(runner.run_cycle())

    # Create APScheduler instance
    scheduler = create_scheduler(run_cycle_fn=run_cycle_job, settings=settings)

    # Graceful shutdown event
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def _on_sigterm() -> None:
        logger.info("sigterm_received action=graceful_shutdown")
        stop_event.set()

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
    else:
        # Windows: signal.signal() instead of add_signal_handler
        signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

    scheduler.start()
    logger.info(
        "scheduler_started cycle_interval_minutes=%d",
        settings.cycle_interval_minutes,
    )

    # Block until SIGTERM or KeyboardInterrupt
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("keyboard_interrupt_received")
    finally:
        logger.info("scheduler_shutting_down wait=True")
        scheduler.shutdown(wait=True)  # wait=True lets current job finish
        await engine.dispose()
        logger.info("worker_stopped")

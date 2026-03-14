"""
CycleRunner: executes one complete collection cycle.

Cycle flow:
  1. Load active sources from database
  2. Get last successful run timestamp (for incremental fetch)
  3. For each source: scrape -> extract tickers -> classify -> accumulate signals
  4. Bulk insert all signals
  5. Update run status (success/partial/failed)
  6. Write .health file on success/partial for Docker health check
  7. Record success/failure with AlertThresholdTracker

Source isolation: one failed source does NOT abort others.
PII guarantee: RawComment objects are created in-memory and never stored.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..alerting.threshold import AlertThresholdTracker
from ..classifiers.base import SentimentClassifier
from ..config import Settings
from ..scrapers.base import RedditScraper, ScraperRateLimitError, ScraperUnavailableError
from ..storage.models import CollectionRun
from ..storage.runs import RunStore
from ..storage.signals import SignalStore
from ..storage.sources import SourceStore
from ..tickers.disambiguator import TickerDisambiguator
from ..tickers.extractor import TickerExtractor

logger = logging.getLogger(__name__)

# How many consecutive ScraperRateLimitError before switching lanes
_RATE_LIMIT_THRESHOLD = 3

# Warn if cycle duration exceeds this fraction of cycle_interval_minutes
_CYCLE_DURATION_WARN_FRACTION = 0.8

# Path to the health file written after each successful cycle.
# The Dockerfile HEALTHCHECK verifies this file's mtime.
_HEALTH_FILE = Path(".health")


class CycleRunner:
    """
    Orchestrates a single complete pipeline cycle.

    Coordinates scraping, ticker extraction, sentiment classification,
    and signal storage for all active data sources.

    Args:
        settings: Worker configuration (cycle_interval_minutes etc.).
        session_factory: Async context manager that yields an AsyncSession.
        classifier: Sentiment classifier implementation.
        primary_scraper: Primary Reddit scraper (JSON endpoint).
        fallback_scraper: Fallback scraper (PRAW OAuth).
        extractor: Ticker symbol extractor.
        disambiguator: Ticker disambiguation/validation filter.
        alert_tracker: Optional threshold tracker for consecutive-failure alerts.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Any],
        classifier: SentimentClassifier,
        primary_scraper: RedditScraper,
        fallback_scraper: RedditScraper,
        extractor: TickerExtractor,
        disambiguator: TickerDisambiguator,
        alert_tracker: AlertThresholdTracker | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._classifier = classifier
        self._primary_scraper = primary_scraper
        self._fallback_scraper = fallback_scraper
        self._extractor = extractor
        self._disambiguator = disambiguator
        self._alert_tracker = alert_tracker
        self._consecutive_rate_limits: int = 0

    @property
    def _active_scraper(self) -> RedditScraper:
        """Return the active scraper lane based on consecutive rate-limit count."""
        if self._consecutive_rate_limits >= _RATE_LIMIT_THRESHOLD:
            return self._fallback_scraper
        return self._primary_scraper

    async def run_cycle(self) -> CollectionRun:
        """
        Execute one complete collection cycle.

        Loads active sources, scrapes each, extracts tickers, classifies
        sentiment, and stores resulting signals. One failed source does not
        abort the cycle for other sources.

        Returns:
            The completed :class:`~storage.models.CollectionRun` record.
        """
        cycle_start = datetime.now(tz=UTC)
        warn_after_seconds = (
            self._settings.cycle_interval_minutes * 60 * _CYCLE_DURATION_WARN_FRACTION
        )

        async with self._session_factory() as session:
            run_store = RunStore(session)
            signal_store = SignalStore(session)
            source_store = SourceStore(session)

            run = await run_store.create_run()
            await session.flush()  # get run.id

            last_run = await run_store.get_last_successful_run()
            if last_run is not None:
                since = last_run.started_at
            else:
                since = datetime.now(tz=UTC) - timedelta(hours=1)

            sources = await source_store.get_active_sources()
            signals_batch: list[dict[str, Any]] = []
            succeeded = 0
            failed_sources: list[str] = []

            active_scraper = self._active_scraper
            scraper_switched = active_scraper is self._fallback_scraper
            if scraper_switched:
                logger.info(
                    "scraper_lane_active lane=fallback consecutive_rate_limits=%d",
                    self._consecutive_rate_limits,
                )

            for source in sources:
                try:
                    async for comment in active_scraper.fetch_comments(
                        source.subreddit_name, since
                    ):
                        candidates = self._extractor.extract(comment.text)
                        valid_tickers = self._disambiguator.filter(candidates)
                        for ticker in valid_tickers:
                            # comment.text is passed in-memory only — never stored
                            result = self._classifier.classify(comment.text)
                            if not result.discarded:
                                signals_batch.append(
                                    {
                                        "collection_run_id": run.id,
                                        "ticker_symbol": ticker,
                                        "sentiment_polarity": result.polarity,
                                        "upvote_weight": comment.upvotes,
                                        "collected_at": comment.created_utc,
                                        "source_subreddit": source.subreddit_name,
                                    }
                                )
                    succeeded += 1
                    # Reset rate-limit counter on successful source
                    self._consecutive_rate_limits = 0

                except ScraperRateLimitError:
                    self._consecutive_rate_limits += 1
                    failed_sources.append(source.subreddit_name)
                    logger.warning(
                        "scraper_rate_limited subreddit=%s consecutive_rate_limits=%d",
                        source.subreddit_name,
                        self._consecutive_rate_limits,
                    )

                except ScraperUnavailableError:
                    failed_sources.append(source.subreddit_name)
                    logger.warning(
                        "source_unavailable subreddit=%s",
                        source.subreddit_name,
                    )

                except Exception as exc:  # noqa: BLE001
                    failed_sources.append(source.subreddit_name)
                    logger.error(
                        "source_failed subreddit=%s error=%s",
                        source.subreddit_name,
                        str(exc),
                    )

            stored = await signal_store.bulk_insert_signals(signals_batch)

            if not failed_sources:
                status = "success"
            elif succeeded > 0:
                status = "partial"
            else:
                status = "failed"

            error_summary: str | None = None
            if failed_sources:
                error_summary = f"Failed sources: {failed_sources}"

            await run_store.update_run_status(
                run,
                status=status,
                sources_attempted=len(sources),
                sources_succeeded=succeeded,
                signals_stored=stored,
                error_summary=error_summary,
            )
            await session.commit()

            # Write health file after any non-failed cycle outcome so Docker
            # can detect that the pipeline is alive.
            if status in ("success", "partial"):
                _HEALTH_FILE.write_text(datetime.now(tz=UTC).isoformat())

            # Alert threshold tracking
            if self._alert_tracker is not None:
                if status == "failed":
                    self._alert_tracker.record_failure(
                        run_id=str(run.id),
                        error_summary=error_summary or "All sources failed",
                    )
                else:
                    self._alert_tracker.record_success()

            # Warn if cycle took too long
            elapsed = (datetime.now(tz=UTC) - cycle_start).total_seconds()
            if elapsed > warn_after_seconds:
                logger.warning(
                    "cycle_duration_exceeded elapsed_seconds=%.1f threshold_seconds=%.1f",
                    elapsed,
                    warn_after_seconds,
                )

            logger.info(
                "cycle_complete status=%s sources_attempted=%d sources_succeeded=%d "
                "signals_stored=%d elapsed_seconds=%.2f",
                status,
                len(sources),
                succeeded,
                stored,
                elapsed,
            )

            return run

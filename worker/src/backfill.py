"""
One-shot historical backfill.

Run from inside the worker container:

    python -m src.backfill --days 30

Uses the same scraping + classification pipeline as the scheduled cycle,
but overrides the ``since`` cutoff and bumps the per-source limit to
Reddit's ceiling (~1000). Writes a single CollectionRun with status
``success`` or ``partial`` and inserts all resulting signals.

Reddit's ``/r/{sub}/new/.json`` endpoint only serves the ~1000 most
recent items per subreddit, so the practical window is
source-dependent: busy subs cover days, quiet subs cover months.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .classifiers import get_classifier
from .config import get_settings
from .logging_config import configure_logging
from .pipeline.runner import TargetAwareClassifier
from .scrapers.base import ScraperRateLimitError, ScraperUnavailableError
from .scrapers.json_endpoint import JsonEndpointScraper
from .storage.runs import RunStore
from .storage.signals import SignalStore
from .storage.sources import SourceStore
from .topics import StorefrontDisambiguator, StorefrontExtractor

logger = logging.getLogger(__name__)

_REDDIT_MAX_PER_SOURCE = 1000

_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) "
        "Gecko/20100101 Firefox/136.0"
    ),
]


async def run_backfill(days: int) -> None:
    """Scrape up to ``days`` days of history from every enabled source."""
    settings = get_settings()
    since = datetime.now(tz=UTC) - timedelta(days=days)

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    classifier = get_classifier()
    if not classifier.is_ready():
        raise RuntimeError("Classifier failed to initialise.")

    scraper = JsonEndpointScraper(
        user_agents=_USER_AGENTS, request_delay_seconds=1.0
    )
    extractor = StorefrontExtractor()
    disambiguator = StorefrontDisambiguator()

    async with session_factory() as session:
        run_store = RunStore(session)
        signal_store = SignalStore(session)
        source_store = SourceStore(session)

        run = await run_store.create_run()
        await session.flush()
        logger.info("backfill_starting days=%d run_id=%s since=%s", days, run.id, since.isoformat())

        sources = await source_store.get_active_sources()
        signals_batch: list[dict[str, Any]] = []
        succeeded = 0
        comments_processed = 0
        failed_sources: list[str] = []

        for source in sources:
            logger.info("backfill_source_start subreddit=%s", source.subreddit_name)
            source_comments = 0
            source_signals = 0
            try:
                async for comment in scraper.fetch_comments(
                    source.subreddit_name, since, limit=_REDDIT_MAX_PER_SOURCE
                ):
                    source_comments += 1
                    comments_processed += 1
                    candidates = extractor.extract(comment.text)
                    tickers = disambiguator.filter(candidates)
                    for ticker in tickers:
                        if isinstance(classifier, TargetAwareClassifier):
                            result = classifier.classify_for_target(ticker, comment.text)
                        else:
                            result = classifier.classify(comment.text)
                        if not result.discarded:
                            signals_batch.append(
                                {
                                    "collection_run_id": run.id,
                                    "ticker_symbol": ticker,
                                    "sentiment_polarity": result.polarity,
                                    "upvote_weight": comment.upvotes,
                                    "reply_count": comment.reply_count,
                                    "collected_at": comment.created_utc,
                                    "source_subreddit": source.subreddit_name,
                                    "source_thread_url": comment.source_thread_url,
                                    "source_content_type": comment.content_type,
                                }
                            )
                            source_signals += 1
                succeeded += 1
                logger.info(
                    "backfill_source_done subreddit=%s comments=%d signals=%d",
                    source.subreddit_name,
                    source_comments,
                    source_signals,
                )
            except ScraperRateLimitError:
                failed_sources.append(source.subreddit_name)
                logger.warning("backfill_rate_limited subreddit=%s", source.subreddit_name)
            except ScraperUnavailableError:
                failed_sources.append(source.subreddit_name)
                logger.warning("backfill_source_unavailable subreddit=%s", source.subreddit_name)
            except Exception as exc:  # noqa: BLE001
                failed_sources.append(source.subreddit_name)
                logger.error(
                    "backfill_source_failed subreddit=%s error=%s",
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

        error_summary = f"Failed sources: {failed_sources}" if failed_sources else None

        await run_store.update_run_status(
            run,
            status=status,
            sources_attempted=len(sources),
            sources_succeeded=succeeded,
            signals_stored=stored,
            comments_processed=comments_processed,
            error_summary=error_summary,
        )
        await session.commit()

        logger.info(
            "backfill_complete status=%s sources_attempted=%d sources_succeeded=%d "
            "comments_processed=%d signals_stored=%d failed_sources=%s",
            status,
            len(sources),
            succeeded,
            comments_processed,
            stored,
            failed_sources,
        )

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical backfill for SentiX worker.")
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of history to attempt (default: 30).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(run_backfill(args.days))


if __name__ == "__main__":
    main()

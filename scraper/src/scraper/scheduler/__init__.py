"""Scraper scheduler — runs scraping cycles at a fixed interval."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from dataclasses import replace

from scraper.config import ScraperSettings
from scraper.reddit.client import RedditClient, RedditComment, _fingerprint, _mentions_ticker
from scraper.storage.db import store_comments, store_posts
from sse_common.channels import CHANNEL_SCRAPER_DONE

logger = logging.getLogger(__name__)

_TICKERS_QUERY = "SELECT symbol FROM tickers WHERE is_active = true"


async def run_scrape_cycle(
    pool: asyncpg.Pool,
    settings: ScraperSettings,
    redis_client: Optional[object] = None,
) -> None:
    """Run one complete scrape cycle for all active tickers."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    logger.info("Scrape cycle starting run_id=%s", run_id)

    # Fetch active tickers from DB
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TICKERS_QUERY)
    tickers = [r["symbol"] for r in rows]

    if not tickers:
        logger.warning("No active tickers configured")
        return

    # Scrape Reddit
    async with RedditClient(
        user_agent=settings.reddit_user_agent,
        proxies=settings.proxy_list or None,
    ) as client:
        posts = await client.fetch_new_posts(tickers, posts_per_subreddit=settings.posts_per_ticker)

    # Store in DB
    inserted, duplicates = await store_posts(pool, posts)

    # Fetch comments for top-10 posts by num_comments
    comment_posts = sorted(
        [p for p in posts if p.num_comments > 0],
        key=lambda p: p.num_comments,
        reverse=True,
    )[:10]

    total_comments_inserted = 0
    if comment_posts:
        async with RedditClient(
            user_agent=settings.reddit_user_agent,
            proxies=settings.proxy_list or None,
            bot_usernames=settings.bot_username_set,
            min_content_length=settings.min_content_length,
        ) as client:
            for post in comment_posts:
                try:
                    raw_comments = await client.fetch_comments(post.reddit_id, limit=50)
                    # Check every active ticker for each comment, not just
                    # the parent post's ticker.  A comment under an AAPL post
                    # might mention TSLA — we want to capture that.
                    ticker_comments: list[RedditComment] = []
                    for c in raw_comments:
                        for tkr in tickers:
                            if _mentions_ticker(c.content, tkr):
                                tc = replace(
                                    c,
                                    ticker_mentioned=tkr,
                                    content_fingerprint=_fingerprint(
                                        c.reddit_id, tkr, c.content
                                    ),
                                )
                                ticker_comments.append(tc)
                    if ticker_comments:
                        c_inserted, _ = await store_comments(pool, ticker_comments)
                        total_comments_inserted += c_inserted
                    # 1-second delay between comment fetches to avoid rate limiting
                    await asyncio.sleep(1.0)
                except Exception:
                    logger.warning(
                        "Failed to fetch comments for post %s", post.reddit_id, exc_info=True
                    )

        if total_comments_inserted > 0:
            logger.info(
                "Inserted %d comments from %d posts", total_comments_inserted, len(comment_posts)
            )

    duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    logger.info(
        "Scrape cycle complete run_id=%s tickers=%d posts=%d inserted=%d duplicates=%d comments=%d duration_ms=%d",
        run_id, len(tickers), len(posts), inserted, duplicates, total_comments_inserted, duration_ms,
    )

    # Publish completion event (only when new posts or comments were inserted)
    if redis_client is not None and (inserted > 0 or total_comments_inserted > 0):
        payload = {
            "run_id": run_id,
            "tickers_scraped": tickers,
            "posts_count": inserted,
            "comments_count": total_comments_inserted,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await redis_client.publish(CHANNEL_SCRAPER_DONE, json.dumps(payload))  # type: ignore[union-attr]
            logger.info("Published scraper run_complete event")
        except Exception:
            logger.warning("Failed to publish scraper event", exc_info=True)

    # Write staleness timestamp on every successful run (regardless of inserted count)
    if redis_client is not None:
        try:
            await redis_client.set(  # type: ignore[union-attr]
                "sse:staleness:last_scrape",
                datetime.now(timezone.utc).isoformat(),
                ex=86400,
            )
        except Exception:
            logger.warning("Failed to write staleness key", exc_info=True)


async def run_scheduler(
    pool: asyncpg.Pool,
    settings: ScraperSettings,
    redis_client: Optional[object],
    shutdown_event: asyncio.Event,
    health: Optional[object] = None,
) -> None:
    """Run scrape cycles at a fixed interval until shutdown."""
    logger.info("Scraper scheduler starting (interval=%ds)", settings.scrape_interval_seconds)

    while not shutdown_event.is_set():
        try:
            await run_scrape_cycle(pool, settings, redis_client)
            if health is not None:
                health.record_success()  # type: ignore[union-attr]
        except Exception:
            logger.error("Scrape cycle failed", exc_info=True)

        # Wait for next interval or shutdown
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=settings.scrape_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass  # Normal — interval elapsed, run next cycle

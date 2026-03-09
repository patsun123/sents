"""Scraper database storage — writes to reddit_raw table."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg

from scraper.reddit.client import RedditPost

logger = logging.getLogger(__name__)


async def store_posts(pool: asyncpg.Pool, posts: list[RedditPost]) -> tuple[int, int]:
    """Insert posts into reddit_raw. Returns (inserted, duplicates).

    H-7 fix: replaced N individual SELECT+INSERT round-trips (up to 1500 per
    scraper cycle) with a single executemany call using INSERT … ON CONFLICT
    DO NOTHING.  Duplicate count is derived as len(posts) - inserted.
    """
    if not posts:
        return 0, 0

    now = datetime.now(timezone.utc)

    rows = [
        (
            post.reddit_id,
            post.ticker_mentioned,
            post.title,
            post.content,
            post.author,
            post.score,
            post.upvote_ratio,
            post.num_comments,
            post.subreddit,
            post.post_url,
            post.created_utc,
            now,                       # scraped_at
            post.content_fingerprint,
            False,                     # is_duplicate — new rows are not duplicates
            now,                       # created_at (hypertable partition key)
        )
        for post in posts
    ]

    async with pool.acquire() as conn:
        # executemany issues a single round-trip per batch rather than N
        # individual queries.  ON CONFLICT DO NOTHING silently skips rows
        # whose (reddit_id, ticker_mentioned) pair already exists.
        status = await conn.execute(
            """
            INSERT INTO reddit_raw (
                reddit_id, ticker_mentioned, title, content,
                author, score, upvote_ratio, num_comments,
                subreddit, post_url, created_utc, scraped_at,
                content_fingerprint, is_duplicate, created_at
            )
            SELECT
                unnest($1::text[]),
                unnest($2::text[]),
                unnest($3::text[]),
                unnest($4::text[]),
                unnest($5::text[]),
                unnest($6::integer[]),
                unnest($7::double precision[]),
                unnest($8::integer[]),
                unnest($9::text[]),
                unnest($10::text[]),
                unnest($11::timestamptz[]),
                unnest($12::timestamptz[]),
                unnest($13::text[]),
                unnest($14::boolean[]),
                unnest($15::timestamptz[])
            ON CONFLICT (reddit_id, ticker_mentioned) DO NOTHING
            """,
            [r[0] for r in rows],   # reddit_id
            [r[1] for r in rows],   # ticker_mentioned
            [r[2] for r in rows],   # title
            [r[3] for r in rows],   # content
            [r[4] for r in rows],   # author
            [r[5] for r in rows],   # score
            [r[6] for r in rows],   # upvote_ratio
            [r[7] for r in rows],   # num_comments
            [r[8] for r in rows],   # subreddit
            [r[9] for r in rows],   # post_url
            [r[10] for r in rows],  # created_utc
            [r[11] for r in rows],  # scraped_at
            [r[12] for r in rows],  # content_fingerprint
            [r[13] for r in rows],  # is_duplicate
            [r[14] for r in rows],  # created_at
        )

    # asyncpg returns a status string like "INSERT 0 42"; parse the row count.
    try:
        inserted = int(status.split()[-1])
    except (AttributeError, ValueError, IndexError):
        inserted = len(posts)

    duplicates = len(posts) - inserted
    logger.info("Stored %d new posts, %d duplicates", inserted, duplicates)
    return inserted, duplicates

"""Sentiment processing pipeline — orchestrates NLP backends and DB writes."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from processor.text.preprocessor import preprocess

logger = logging.getLogger(__name__)


async def get_unprocessed_posts(
    conn: asyncpg.Connection,
    backend: str,
    limit: int = 500,
) -> list[asyncpg.Record]:
    """Get reddit_raw rows that haven't been analyzed by this backend yet."""
    return await conn.fetch(
        """
        SELECT r.id, r.reddit_id, r.ticker_mentioned, r.title, r.content,
               r.score, r.upvote_ratio, r.created_utc
        FROM reddit_raw r
        WHERE NOT EXISTS (
            SELECT 1 FROM comment_sentiment cs
            WHERE cs.reddit_comment_id = r.id
              AND cs.backend = $1
        )
        AND r.is_duplicate = false
        AND r.content NOT IN ('[deleted]', '[removed]')
        AND r.author NOT IN ('[deleted]', '[removed]', 'AutoModerator')
        AND LENGTH(COALESCE(r.title, '') || ' ' || COALESCE(r.content, '')) >= 20
        ORDER BY r.created_utc DESC
        LIMIT $2
        """,
        backend,
        limit,
    )


async def store_sentiment_scores(
    conn: asyncpg.Connection,
    reddit_comment_id: int,
    backend: str,
    compound: float,
    positive: float,
    negative: float,
    neutral: float,
    raw_scores: dict,
) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO comment_sentiment (
            reddit_comment_id, backend,
            compound_score, positive_score, negative_score, neutral_score,
            raw_scores, analyzed_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (reddit_comment_id, backend) DO NOTHING
        """,
        reddit_comment_id,
        backend,
        compound,
        positive,
        negative,
        neutral,
        json.dumps(raw_scores),
        now,
    )


async def aggregate_sentiment_snapshot(
    conn: asyncpg.Connection,
    ticker: str,
    backend: str,
    window_hours: int = 1,
    decay_halflife_hours: float = 12.0,
    upvote_weight_min: float = 0.1,
    upvote_weight_max: float = 10.0,
) -> Optional[asyncpg.Record]:
    """Aggregate comment_sentiment scores for a ticker over the last window_hours.

    Uses weighted aggregation:
    - Upvote magnitude weight: GREATEST(min, LEAST(max, LN(1 + score)))
    - Temporal decay: EXP(-0.693 / halflife_hours * age_hours)
    The final weight is the product of both factors.
    """
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(hours=window_hours)

    row = await conn.fetchrow(
        """
        SELECT
            SUM(cs.compound_score * w.weight) / NULLIF(SUM(w.weight), 0)
                AS avg_compound,
            SUM(w.weight) AS weighted_mention_count,
            AVG(r.score) AS avg_upvote_score
        FROM comment_sentiment cs
        JOIN reddit_raw r ON r.id = cs.reddit_comment_id
        CROSS JOIN LATERAL (
            SELECT
                GREATEST($5, LEAST($6, LN(1 + GREATEST(r.score, 0)))) *
                EXP(-0.693 / $7 * EXTRACT(EPOCH FROM (NOW() - r.created_utc)) / 3600)
            AS weight
        ) w
        WHERE r.ticker_mentioned = $1
          AND cs.backend = $2
          AND r.created_utc BETWEEN $3 AND $4
        """,
        ticker,
        backend,
        window_start,
        window_end,
        upvote_weight_min,
        upvote_weight_max,
        decay_halflife_hours,
    )

    if not row or not row["weighted_mention_count"] or row["weighted_mention_count"] == 0:
        return None

    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO ticker_sentiment_snapshot (
            ticker, window_start, window_end, backend,
            avg_sentiment_compound, weighted_mention_count, avg_upvote_score,
            created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (ticker, window_start, window_end, backend) DO UPDATE
            SET avg_sentiment_compound = EXCLUDED.avg_sentiment_compound,
                weighted_mention_count = EXCLUDED.weighted_mention_count,
                avg_upvote_score = EXCLUDED.avg_upvote_score
        """,
        ticker,
        window_start,
        window_end,
        backend,
        float(row["avg_compound"] or 0),
        float(row["weighted_mention_count"]),
        float(row["avg_upvote_score"] or 0),
        now,
    )
    return row


async def run_pipeline(
    pool: asyncpg.Pool,
    backends: list[str],
    finbert_batch_size: int,
    window_hours: int,
) -> dict:
    """Run the full NLP pipeline. Returns summary stats."""
    run_id = str(uuid.uuid4())
    logger.info("Starting NLP pipeline run_id=%s backends=%s", run_id, backends)

    total_analyzed = 0
    tickers_processed: set[str] = set()

    for backend in backends:
        try:
            backend_tickers: set[str] = set()

            async with pool.acquire() as conn:
                posts = await get_unprocessed_posts(conn, backend)

            if not posts:
                logger.info("No unprocessed posts for backend=%s", backend)
                continue

            logger.info("Processing %d posts with backend=%s", len(posts), backend)
            texts = [preprocess(f"{p['title'] or ''}\n{p['content'] or ''}".strip()) for p in posts]

            # Run sentiment analysis
            if backend == "vader":
                from processor.sentiment.vader_backend import analyze_batch
                results = analyze_batch(texts)
            elif backend == "textblob":
                from processor.sentiment.textblob_backend import analyze_batch
                results = analyze_batch(texts)
            elif backend == "finbert":
                from processor.sentiment.finbert_backend import analyze_batch
                results = analyze_batch(texts, batch_size=finbert_batch_size)
            else:
                logger.warning("Unknown backend: %s", backend)
                continue

            # Store scores
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for post, result in zip(posts, results):
                        await store_sentiment_scores(
                            conn,
                            reddit_comment_id=post["id"],
                            backend=backend,
                            compound=result.compound,
                            positive=result.positive,
                            negative=result.negative,
                            neutral=result.neutral,
                            raw_scores=result.raw_scores,
                        )
                        backend_tickers.add(post["ticker_mentioned"])
                    total_analyzed += len(posts)

            # Aggregate snapshots per ticker
            async with pool.acquire() as conn:
                for ticker in backend_tickers:
                    await aggregate_sentiment_snapshot(conn, ticker, backend, window_hours)
            tickers_processed |= backend_tickers

        except Exception:
            logger.error("Pipeline failed for backend=%s", backend, exc_info=True)

    logger.info(
        "Pipeline complete run_id=%s analyzed=%d tickers=%d",
        run_id, total_analyzed, len(tickers_processed),
    )
    return {
        "run_id": run_id,
        "tickers_processed": list(tickers_processed),
        "comments_analyzed": total_analyzed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

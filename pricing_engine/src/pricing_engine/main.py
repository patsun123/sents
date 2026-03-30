"""Pricing engine entrypoint.

Listens for sse:sentiment:run_complete on Redis pub/sub and also polls on a
fixed interval. Each cycle:
  1. Fetches active tickers from DB
  2. Reads latest sentiment snapshots per ticker
  3. Fetches real market prices via yfinance (with DB fallback)
  4. Applies the formula to compute sentiment_price
  5. Writes results to sentiment_prices
  6. Publishes sse:pricing:run_complete
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis

from pricing_engine.config import get_settings
from pricing_engine.fetcher.real_prices import fetch_and_store_real_prices
from pricing_engine.formula.engine import FormulaEngine, FormulaParams, SentimentSnapshot
from pricing_engine.publisher import publish_pricing_complete
from sse_common.channels import CHANNEL_PROCESSOR_DONE as _SUBSCRIBE_CHANNEL

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
_cycle_lock = asyncio.Lock()

_TICKERS_QUERY = "SELECT symbol FROM tickers WHERE is_active = true"
_SNAPSHOT_QUERY = """
    SELECT ticker, window_end, avg_sentiment_compound, weighted_mention_count, avg_upvote_score
    FROM ticker_sentiment_snapshot
    WHERE (ticker, window_end) IN (
        SELECT ticker, MAX(window_end)
        FROM ticker_sentiment_snapshot
        GROUP BY ticker
    )
"""
_INSERT_PRICES = """
    INSERT INTO sentiment_prices (time, ticker, sentiment_price, real_price_at_calc, sentiment_delta, parameters_version, created_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (time, ticker) DO NOTHING
"""


async def run_pricing_cycle(pool: asyncpg.Pool, redis_client: aioredis.Redis | None) -> None:
    """One full pricing cycle: fetch → compute → store → publish."""
    async with pool.acquire() as conn:
        ticker_rows = await conn.fetch(_TICKERS_QUERY)
    tickers = [r["symbol"] for r in ticker_rows]
    if not tickers:
        logger.warning("No active tickers")
        return

    # Fetch real prices
    real_prices = await fetch_and_store_real_prices(pool, redis_client, tickers)
    if not real_prices:
        logger.warning("No real prices available — skipping cycle")
        return

    # Load latest sentiment snapshots
    async with pool.acquire() as conn:
        snap_rows = await conn.fetch(_SNAPSHOT_QUERY)

    if not snap_rows:
        logger.info("No sentiment snapshots yet — skipping pricing")
        return

    snapshots = [
        SentimentSnapshot(
            ticker=r["ticker"],
            window_end=r["window_end"],
            agg_score=float(r["avg_sentiment_compound"]),
            mention_count=int(r["weighted_mention_count"]),
            avg_upvote_score=float(r["avg_upvote_score"]),
        )
        for r in snap_rows
    ]

    # Load previous snapshots for delta calculation
    snap_tickers = [s.ticker for s in snapshots]
    async with pool.acquire() as conn:
        prev_rows = await conn.fetch(
            """
            SELECT ticker, window_end,
                avg_sentiment_compound, weighted_mention_count, avg_upvote_score
            FROM (
                SELECT ticker, window_end,
                    avg_sentiment_compound, weighted_mention_count, avg_upvote_score,
                    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY window_end DESC) AS rn
                FROM ticker_sentiment_snapshot
                WHERE ticker = ANY($1)
            ) sub
            WHERE rn = 2
            """,
            snap_tickers,
        )
    prev_snapshots = {
        r["ticker"]: SentimentSnapshot(
            ticker=r["ticker"],
            window_end=r["window_end"],
            agg_score=float(r["avg_sentiment_compound"]),
            mention_count=int(r["weighted_mention_count"]),
            avg_upvote_score=float(r["avg_upvote_score"]),
        )
        for r in prev_rows
    }

    # Load formula params from DB
    async with pool.acquire() as conn:
        params_row = await conn.fetchrow(
            "SELECT * FROM pricing_parameters ORDER BY id DESC LIMIT 1"
        )
    params = FormulaParams.from_dict(dict(params_row) if params_row else {})
    engine = FormulaEngine(params, parameters_version="default")

    results = engine.compute_batch(snapshots, prev_snapshots, real_prices)
    if not results:
        logger.info("No pricing results computed")
        return

    # Store results
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.executemany(
            _INSERT_PRICES,
            [
                (
                    now,
                    r.ticker,
                    float(r.sentiment_price),
                    float(r.real_price),
                    float(r.sentiment_delta),
                    r.parameters_version,
                    now,
                )
                for r in results
            ],
        )

    logger.info("Priced %d tickers", len(results))
    await publish_pricing_complete(redis_client, [r.ticker for r in results])


async def subscriber_loop(
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis,
    interval: int,
    shutdown: asyncio.Event,
    health: object | None = None,
) -> None:
    """Listen for sentiment run_complete events and run pricing after each."""
    pubsub = None
    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(_SUBSCRIBE_CHANNEL)
        logger.info("Subscribed to %s", _SUBSCRIBE_CHANNEL)

        while not shutdown.is_set():
            try:
                msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if msg and msg.get("type") == "message":
                logger.info("Received sentiment:run_complete — triggering pricing cycle")
                if _cycle_lock.locked():
                    logger.debug("Pricing cycle already running, skipping")
                    continue
                try:
                    async with _cycle_lock:
                        await run_pricing_cycle(pool, redis_client)
                        if health:
                            health.record_success()  # type: ignore[union-attr]
                except Exception:
                    logger.error("Pricing cycle failed", exc_info=True)
    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
            except Exception:
                pass


async def poll_loop(
    pool: asyncpg.Pool,
    redis_client: aioredis.Redis | None,
    interval: int,
    shutdown: asyncio.Event,
    health: object | None = None,
) -> None:
    """Fallback timer-based pricing in case Redis pub/sub events are missed."""
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass
        if shutdown.is_set():
            break
        if _cycle_lock.locked():
            logger.debug("Pricing cycle already running, skipping")
            continue
        try:
            async with _cycle_lock:
                await run_pricing_cycle(pool, redis_client)
                if health:
                    health.record_success()  # type: ignore[union-attr]
        except Exception:
            logger.error("Poll-based pricing cycle failed", exc_info=True)


async def main() -> None:
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level.upper())

    # Health server
    from pricing_engine.health import HealthServer
    health = HealthServer("pricing_engine", 8003)
    health.start()
    logger.info("Health server listening on :8003")

    pool = await asyncpg.create_pool(settings.postgres_url_pricing, min_size=2, max_size=5)

    # Attempt Redis connection — degrade to poll-only if unavailable
    redis_client: aioredis.Redis | None = None
    redis_pool: aioredis.ConnectionPool | None = None
    try:
        redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url, max_connections=settings.redis_max_connections
        )
        redis_client = aioredis.Redis(connection_pool=redis_pool)
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception:
        logger.warning("Redis unavailable — degrading to poll-only mode (no pub/sub, no publish)")
        redis_client = None
        if redis_pool:
            await redis_pool.aclose()
            redis_pool = None

    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown.set)
    else:
        def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
            shutdown.set()
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Pricing engine starting (interval=%ds)", settings.poll_interval_seconds)

    # Run one cycle immediately on startup
    try:
        await run_pricing_cycle(pool, redis_client)
        health.record_success()
    except Exception:
        logger.warning("Initial pricing cycle failed (no data yet?)", exc_info=True)

    try:
        tasks = [poll_loop(pool, redis_client, settings.poll_interval_seconds, shutdown, health)]
        if redis_client is not None:
            tasks.append(
                subscriber_loop(pool, redis_client, settings.poll_interval_seconds, shutdown, health)
            )
        else:
            logger.info("Subscriber loop disabled — Redis not available")
        await asyncio.gather(*tasks)
    finally:
        await pool.close()
        if redis_client:
            await redis_client.aclose()
        logger.info("Pricing engine stopped")


if __name__ == "__main__":
    asyncio.run(main())

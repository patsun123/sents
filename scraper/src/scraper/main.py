"""Scraper service entry point."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import asyncpg

from scraper.config import get_settings

logger = logging.getLogger(__name__)

_shutdown_event = asyncio.Event()


def _handle_signal(sig: int, frame: object) -> None:  # noqa: ARG001
    logger.info("Signal %d received — shutting down scraper", sig)
    _shutdown_event.set()


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Scraper service starting")

    # DB pool
    pool = await asyncpg.create_pool(
        dsn=settings.postgres_url_scraper,
        min_size=2,
        max_size=5,
        command_timeout=30,
    )
    if pool is None:
        logger.critical("Failed to create DB pool — exiting")
        sys.exit(1)

    # Redis (optional — scraper degrades gracefully without it)
    redis_client = None
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url, max_connections=5, decode_responses=True
        )
        redis_client = aioredis.Redis(connection_pool=redis_pool)
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception:
        logger.warning("Redis unavailable — scraper will run without event publishing", exc_info=True)

    # Run scheduler
    from scraper.scheduler import run_scheduler
    try:
        await run_scheduler(pool, settings, redis_client, _shutdown_event)
    finally:
        await pool.close()
        if redis_client is not None:
            await redis_client.aclose()
    logger.info("Scraper stopped")


if __name__ == "__main__":
    asyncio.run(main())

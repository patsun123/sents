"""Processor service entry point."""
from __future__ import annotations

import asyncio
import json as _json
import logging
import signal
import sys
from datetime import datetime, timezone

import asyncpg

from processor.config import get_settings
from sse_common.channels import CHANNEL_SCRAPER_DONE as _SCRAPER_CHANNEL
from sse_common.channels import CHANNEL_PROCESSOR_DONE as _SENTIMENT_CHANNEL

logger = logging.getLogger(__name__)
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0

_shutdown_event = asyncio.Event()


def _handle_signal(sig: int, frame: object) -> None:  # noqa: ARG001
    logger.info("Signal %d received — shutting down processor", sig)
    _shutdown_event.set()


async def subscriber_loop(
    pool: asyncpg.Pool,
    redis_pool: object,
    settings: object,
    active_backends: list[str],
) -> None:
    """Subscribe to scraper events and trigger sentiment pipeline."""
    import redis.asyncio as aioredis  # type: ignore[import]
    backoff = _BACKOFF_BASE

    while not _shutdown_event.is_set():
        pubsub = None
        try:
            client = aioredis.Redis(connection_pool=redis_pool)  # type: ignore[arg-type]
            pubsub = client.pubsub()
            await pubsub.subscribe(_SCRAPER_CHANNEL)
            logger.info("Subscribed to %s", _SCRAPER_CHANNEL)
            backoff = _BACKOFF_BASE

            async for message in pubsub.listen():
                if _shutdown_event.is_set():
                    break
                if message["type"] != "message":
                    continue

                logger.info("Received scraper run_complete — starting NLP pipeline")
                try:
                    from processor.pipeline.pipeline import run_pipeline
                    result = await run_pipeline(
                        pool,
                        backends=active_backends,
                        finbert_batch_size=settings.finbert_batch_size,  # type: ignore[attr-defined]
                        window_hours=settings.sentiment_window_hours,  # type: ignore[attr-defined]
                    )
                    # Publish completion
                    payload = _json.dumps(result)
                    await client.publish(_SENTIMENT_CHANNEL, payload)
                    logger.info("Published sentiment run_complete")
                    # Write staleness key to Redis for health endpoint
                    await client.set(
                        "sse:staleness:last_sentiment_calc",
                        datetime.now(timezone.utc).isoformat(),
                        ex=86400,
                    )
                except Exception:
                    logger.error("NLP pipeline failed", exc_info=True)

        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning(
                "Subscriber error; retrying in %.0fs", backoff, exc_info=True
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Processor service starting (backends=%s)", settings.backends_list)

    # Pre-load FinBERT if configured (heavy download)
    active_backends = settings.backends_list  # start with configured list
    if "finbert" in active_backends:
        try:
            from processor.sentiment.finbert_backend import load_model
            load_model(settings.finbert_model)
        except Exception:
            logger.error("Failed to load FinBERT — removing from backends", exc_info=True)
            active_backends = [b for b in active_backends if b != "finbert"]

    async def _init_conn(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            'jsonb',
            encoder=_json.dumps,
            decoder=_json.loads,
            schema='pg_catalog',
        )

    # DB pool
    pool = await asyncpg.create_pool(
        dsn=settings.postgres_url_processor,
        min_size=2,
        max_size=5,
        command_timeout=60,
        init=_init_conn,
    )
    if pool is None:
        logger.critical("Failed to create DB pool")
        sys.exit(1)

    # Redis
    redis_pool = None
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=5,
            decode_responses=True,
        )
        client = aioredis.Redis(connection_pool=redis_pool)
        await client.ping()
        logger.info("Redis connected")
    except Exception:
        logger.critical("Redis unavailable — processor requires Redis for event subscription")
        sys.exit(1)

    task = asyncio.create_task(subscriber_loop(pool, redis_pool, settings, active_backends))

    try:
        await _shutdown_event.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        await pool.close()
        await redis_pool.aclose()  # type: ignore[union-attr]
        logger.info("Processor stopped")


if __name__ == "__main__":
    asyncio.run(main())

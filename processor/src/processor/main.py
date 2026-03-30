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
from processor.health import HealthServer
from sse_common.channels import CHANNEL_SCRAPER_DONE as _SCRAPER_CHANNEL
from sse_common.channels import CHANNEL_PROCESSOR_DONE as _SENTIMENT_CHANNEL

logger = logging.getLogger(__name__)
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_POLL_INTERVAL = 60.0
_REDIS_RECONNECT_INTERVAL = 30.0

_shutdown_event = asyncio.Event()
_pipeline_lock = asyncio.Lock()

# Mutable container so reconnect_loop and main() share the same pool reference.
_redis_pool_ref: list[object | None] = [None]


async def subscriber_loop(
    pool: asyncpg.Pool,
    redis_pool: object,
    settings: object,
    active_backends: list[str],
    health: HealthServer | None = None,
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
                if _pipeline_lock.locked():
                    logger.debug("Pipeline already running, skipping")
                    continue
                try:
                    async with _pipeline_lock:
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
                        if health:
                            health.record_success()
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


async def poll_loop(
    pool: asyncpg.Pool,
    settings: object,
    active_backends: list[str],
    health: HealthServer | None = None,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Fallback: poll for unprocessed posts every 60 seconds."""
    _evt = shutdown_event or _shutdown_event
    while not _evt.is_set():
        try:
            await asyncio.wait_for(_evt.wait(), timeout=_POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass
        if _evt.is_set():
            break
        if _pipeline_lock.locked():
            logger.debug("Pipeline already running, skipping")
            continue
        try:
            async with _pipeline_lock:
                from processor.pipeline.pipeline import run_pipeline
                result = await run_pipeline(
                    pool,
                    backends=active_backends,
                    finbert_batch_size=settings.finbert_batch_size,  # type: ignore[attr-defined]
                    window_hours=settings.sentiment_window_hours,  # type: ignore[attr-defined]
                )
                if health:
                    health.record_success()
                logger.info("Poll-based pipeline completed: %s", result)
        except Exception:
            logger.error("Poll-based pipeline failed", exc_info=True)


async def redis_reconnect_loop(
    pool: asyncpg.Pool,
    settings: object,
    active_backends: list[str],
    health: HealthServer | None = None,
    tasks_list: list[asyncio.Task] | None = None,  # type: ignore[type-arg]
) -> None:
    """Try to reconnect to Redis every 30 seconds if initially unavailable."""
    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=_REDIS_RECONNECT_INTERVAL)
        except asyncio.TimeoutError:
            pass
        if _shutdown_event.is_set():
            break
        try:
            import redis.asyncio as aioredis  # type: ignore[import]

            # Close the old pool (if any) before creating a new one
            old_pool = _redis_pool_ref[0]
            if old_pool is not None:
                try:
                    await old_pool.aclose()  # type: ignore[union-attr]
                except Exception:
                    pass
                _redis_pool_ref[0] = None

            redis_pool = aioredis.ConnectionPool.from_url(
                settings.redis_url,  # type: ignore[attr-defined]
                max_connections=5,
                decode_responses=True,
            )
            client = aioredis.Redis(connection_pool=redis_pool)
            await client.ping()
            # Store for shutdown cleanup
            _redis_pool_ref[0] = redis_pool
            logger.info("Redis reconnected — starting subscriber loop")
            sub_task = asyncio.create_task(
                subscriber_loop(pool, redis_pool, settings, active_backends, health)
            )
            if tasks_list is not None:
                tasks_list.append(sub_task)
            return  # stop reconnect loop once connected
        except Exception:
            logger.debug("Redis still unavailable, retrying in %.0fs", _REDIS_RECONNECT_INTERVAL)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _shutdown_event.set)
    else:
        # Windows: use signal.signal as fallback
        def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
            _shutdown_event.set()
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    # Health server
    health = HealthServer("processor", 8002)
    health.start()
    logger.info("Health server listening on :8002")

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

    # Redis — graceful degradation if unavailable
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
        _redis_pool_ref[0] = redis_pool
        logger.info("Redis connected")
    except Exception:
        logger.warning("Redis unavailable — running in poll-only mode")
        redis_pool = None

    tasks: list[asyncio.Task] = []  # type: ignore[type-arg]

    # Always run poll loop as fallback
    tasks.append(asyncio.create_task(
        poll_loop(pool, settings, active_backends, health, _shutdown_event)
    ))

    if redis_pool is not None:
        tasks.append(asyncio.create_task(
            subscriber_loop(pool, redis_pool, settings, active_backends, health)
        ))
    else:
        # Try to reconnect to Redis in the background
        tasks.append(asyncio.create_task(
            redis_reconnect_loop(pool, settings, active_backends, health, tasks)
        ))

    try:
        await _shutdown_event.wait()
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        await pool.close()
        current_redis_pool = _redis_pool_ref[0]
        if current_redis_pool is not None:
            try:
                await current_redis_pool.aclose()  # type: ignore[union-attr]
            except Exception:
                pass
            _redis_pool_ref[0] = None
        logger.info("Processor stopped")


if __name__ == "__main__":
    asyncio.run(main())

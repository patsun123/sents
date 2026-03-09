"""Redis subscriber for sse:pricing:run_complete — triggers SSE broadcasts."""
from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.services.sse_manager import SSEManager

logger = logging.getLogger(__name__)

_CHANNEL = "sse:pricing:run_complete"
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0


class PricingEventSubscriber:
    """Subscribes to Redis pricing events and broadcasts via SSEManager."""

    def __init__(self, redis_pool: aioredis.ConnectionPool, sse_manager: SSEManager) -> None:
        self._pool = redis_pool
        self._sse = sse_manager
        self._running = True

    async def run(self) -> None:
        backoff = _BACKOFF_BASE
        while self._running:
            pubsub = None
            try:
                client = aioredis.Redis(connection_pool=self._pool)
                pubsub = client.pubsub()
                await pubsub.subscribe(_CHANNEL)
                logger.info("PricingEventSubscriber subscribed to %s", _CHANNEL)
                backoff = _BACKOFF_BASE
                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue
                    await self._handle_message(message["data"])
            except asyncio.CancelledError:
                logger.info("PricingEventSubscriber cancelled")
                return
            except Exception:
                logger.warning(
                    "PricingEventSubscriber Redis disconnect; retrying in %.0fs", backoff,
                    exc_info=True,
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

    async def _handle_message(self, data: str) -> None:
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            logger.error("PricingEventSubscriber: invalid JSON payload: %r", data)
            return

        tickers_priced: list[str] = payload.get("tickers_priced", [])
        event_json = json.dumps({"event": "price_update", "data": payload})

        for ticker in tickers_priced:
            try:
                await self._sse.broadcast(ticker, f"event: price_update\ndata: {event_json}\n\n")
            except Exception:
                logger.warning("SSE broadcast failed for ticker=%s", ticker, exc_info=True)

        await self._sse.broadcast_all(f"event: data_refresh\ndata: {event_json}\n\n")

    def stop(self) -> None:
        self._running = False

"""Redis connection pool and cache utilities."""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import Settings


def create_redis_pool(settings: Settings) -> aioredis.ConnectionPool:
    return aioredis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
    )


def get_redis_client(pool: aioredis.ConnectionPool) -> aioredis.Redis:
    return aioredis.Redis(connection_pool=pool)


async def cache_get(client: aioredis.Redis, key: str) -> Any | None:
    raw = await client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(client: aioredis.Redis, key: str, value: Any, ttl: int = 60) -> None:
    await client.set(key, json.dumps(value), ex=ttl)


async def cache_get_or_set(
    client: aioredis.Redis,
    key: str,
    ttl: int,
    factory_fn: Any,
) -> Any:
    raw = await client.get(key)
    if raw is not None:
        return json.loads(raw)
    fresh = await factory_fn()
    await cache_set(client, key, fresh, ttl)
    return fresh

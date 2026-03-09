"""asyncpg connection pool management."""
from __future__ import annotations

import asyncpg
from app.core.config import Settings


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool."""
    pool = await asyncpg.create_pool(
        dsn=settings.asyncpg_dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,  # required for PgBouncer compatibility
    )
    if pool is None:
        raise RuntimeError("Failed to create asyncpg pool")
    return pool

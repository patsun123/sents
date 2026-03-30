"""GET /api/v1/pricing/configs"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Request
from app.core.limiter import limiter
from app.db.redis_client import cache_get_or_set, get_redis_client
from app.schemas import PricingConfig, PricingConfigsResponse

router = APIRouter()


@router.get("/configs", response_model=PricingConfigsResponse, summary="List pricing configurations")
@limiter.limit("60/minute")
async def list_pricing_configs(request: Request) -> PricingConfigsResponse:
    """Returns all active pricing configuration presets. Cached for 5 minutes."""
    redis_client = get_redis_client(request.app.state.redis_pool)

    async def _fetch() -> dict:
        pool: asyncpg.Pool = request.app.state.db_pool
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text, slug, name, description, params
                FROM pricing_configurations
                WHERE is_active = true
                ORDER BY created_at
                """
            )
        return {
            "configs": [
                {
                    "id": row["id"],
                    "slug": row["slug"],
                    "name": row["name"],
                    "description": row["description"],
                    "params": dict(row["params"]),
                }
                for row in rows
            ]
        }

    data = await cache_get_or_set(redis_client, "sse:pricing:configs", 300, _fetch)
    return PricingConfigsResponse.model_validate(data)

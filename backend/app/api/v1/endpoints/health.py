"""GET /api/v1/health"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.db.redis_client import get_redis_client
from app.schemas import HealthResponse, TickerStaleness
from app.utils import staleness_level

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=HealthResponse, summary="Service health check")
async def health_check(request: Request) -> HealthResponse:
    """Returns composite health including DB, Redis, and data freshness."""
    db_ok = False
    redis_ok = False
    ticker_staleness: list[TickerStaleness] = []

    # DB check
    try:
        pool: asyncpg.Pool = request.app.state.db_pool
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        logger.warning("Health check: DB unavailable", exc_info=True)

    # Redis check
    try:
        redis_client = get_redis_client(request.app.state.redis_pool)
        await redis_client.ping()
        redis_ok = True

        # Fetch staleness timestamps
        last_scrape_raw = await redis_client.get("sse:staleness:last_scrape")
        last_sentiment_raw = await redis_client.get("sse:staleness:last_sentiment_calc")

        def _parse_dt(raw: str | None) -> datetime | None:
            if not raw:
                return None
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                logger.warning("Unparseable timestamp from Redis: %r", raw)
                return None

        last_scrape = _parse_dt(last_scrape_raw)
        last_sentiment = _parse_dt(last_sentiment_raw)
    except Exception:
        logger.warning("Health check: Redis unavailable", exc_info=True)
        last_scrape = None
        last_sentiment = None

    # Per-ticker staleness from DB
    if db_ok:
        try:
            pool = request.app.state.db_pool
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT sp.ticker,
                           EXTRACT(EPOCH FROM (now() - MAX(sp.time))) / 60 AS minutes_ago
                    FROM sentiment_prices sp
                    JOIN tickers t ON t.symbol = sp.ticker AND t.is_active = true
                    GROUP BY sp.ticker
                    """
                )
            for row in rows:
                mins = float(row["minutes_ago"]) if row["minutes_ago"] else None
                ticker_staleness.append(
                    TickerStaleness(
                        ticker=row["ticker"],
                        staleness=staleness_level(mins),
                        minutes_since_update=mins,
                    )
                )
        except Exception:
            logger.warning("Health check: failed to fetch ticker staleness", exc_info=True)

    # Determine overall status
    if not db_ok:
        status = "unhealthy"
    elif not redis_ok or any(t.staleness in ("critical", "unavailable") for t in ticker_staleness):
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(
        status=status,
        db_connected=db_ok,
        redis_connected=redis_ok,
        tickers=ticker_staleness,
        last_scrape_time=last_scrape,
        last_sentiment_calc_time=last_sentiment,
        checked_at=datetime.now(timezone.utc),
    )

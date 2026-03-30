"""GET /api/v1/market/overview"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Request
from app.core.limiter import limiter
from app.db.redis_client import get_redis_client, cache_get_or_set
from app.schemas import MarketOverviewResponse, TickerSummary
from app.utils import staleness_level

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/overview", response_model=MarketOverviewResponse, summary="Market overview")
@limiter.limit("60/minute")
async def market_overview(request: Request) -> MarketOverviewResponse:
    """Returns current sentiment and real prices for all active tickers."""
    redis_client = get_redis_client(request.app.state.redis_pool)
    cache_key = "sse:tickers:overview"

    async def _fetch() -> dict:
        pool: asyncpg.Pool = request.app.state.db_pool
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    t.symbol AS ticker,
                    sp.sentiment_price,
                    sp.real_price_at_calc AS real_price,
                    sp.sentiment_delta,
                    EXTRACT(EPOCH FROM (now() - sp.time)) / 60 AS minutes_ago,
                    sp.time AS last_updated,
                    COALESCE(m.cnt, 0) AS mention_count_24h,
                    spark.sparkline
                FROM tickers t
                LEFT JOIN LATERAL (
                    SELECT sentiment_price, real_price_at_calc, sentiment_delta, time
                    FROM sentiment_prices
                    WHERE ticker = t.symbol
                    ORDER BY time DESC
                    LIMIT 1
                ) sp ON true
                LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS cnt
                    FROM reddit_raw
                    WHERE ticker_mentioned = t.symbol
                      AND created_utc >= now() - INTERVAL '24 hours'
                ) m ON true
                LEFT JOIN LATERAL (
                    SELECT array_agg(sub.sentiment_price ORDER BY sub.time) AS sparkline
                    FROM (
                        SELECT sentiment_price, time
                        FROM sentiment_prices
                        WHERE ticker = t.symbol
                        ORDER BY time DESC
                        LIMIT 24
                    ) sub
                ) spark ON true
                WHERE t.is_active = true
                ORDER BY t.symbol
                """
            )

        tickers = []
        for row in rows:
            mins = float(row["minutes_ago"]) if row["minutes_ago"] is not None else None
            lu = row["last_updated"]
            tickers.append(
                {
                    "ticker": row["ticker"],
                    "sentiment_price": float(row["sentiment_price"]) if row["sentiment_price"] is not None else None,
                    "real_price": float(row["real_price"]) if row["real_price"] is not None else None,
                    "sentiment_delta": float(row["sentiment_delta"]) if row["sentiment_delta"] is not None else 0.0,
                    "staleness": staleness_level(mins),
                    "last_updated": lu.isoformat() if lu else None,
                    "mention_count_24h": int(row["mention_count_24h"]),
                    "sparkline": [float(v) for v in row["sparkline"]] if row["sparkline"] else [],
                }
            )
        return {
            "tickers": tickers,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    data = await cache_get_or_set(redis_client, cache_key, 30, _fetch)
    return MarketOverviewResponse.model_validate(data)

"""Fetches real market prices and writes to real_prices table + Redis cache."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_TICKERS_QUERY = "SELECT symbol FROM tickers WHERE is_active = true"


async def fetch_and_store_real_prices(
    pool: asyncpg.Pool,
    redis_client: Optional[object],
    tickers: list[str],
) -> dict[str, Decimal]:
    """Fetch current prices via yfinance and store in DB + Redis.

    Returns dict of ticker -> price for successfully fetched tickers.
    Falls back to last DB price if yfinance fails.
    """
    prices: dict[str, Decimal] = {}
    # Track which tickers were fetched from yfinance vs DB fallback
    yfinance_tickers: set[str] = set()

    # Try yfinance (import here to avoid heavy import at module load)
    try:
        import yfinance as yf  # type: ignore[import]

        symbols = " ".join(tickers)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            lambda: yf.download(symbols, period="1d", interval="1m", progress=False, auto_adjust=True),
        )
        if data.empty:
            raise ValueError("yfinance returned empty data")

        # Extract last close for each ticker
        close_col = "Close"
        if hasattr(data.columns, "levels"):
            # Multi-ticker: columns are MultiIndex (field, ticker)
            for t in tickers:
                try:
                    val = data[close_col][t].dropna().iloc[-1]
                    prices[t] = Decimal(str(round(float(val), 4)))
                    yfinance_tickers.add(t)
                except (KeyError, IndexError):
                    pass
        else:
            # Single ticker
            try:
                val = data[close_col].dropna().iloc[-1]
                prices[tickers[0]] = Decimal(str(round(float(val), 4)))
                yfinance_tickers.add(tickers[0])
            except (KeyError, IndexError):
                pass

    except Exception:
        logger.warning("yfinance fetch failed; falling back to last DB prices", exc_info=True)

    # Fall back to DB for any missing tickers
    missing = [t for t in tickers if t not in prices]
    if missing:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (ticker) ticker, price
                FROM real_prices
                WHERE ticker = ANY($1)
                ORDER BY ticker, time DESC
                """,
                missing,
            )
        for row in rows:
            prices[row["ticker"]] = Decimal(str(row["price"]))
            # DB-fallback tickers are NOT added to yfinance_tickers

    if not prices:
        logger.warning("No real prices available for any tickers")
        return {}

    # Write to DB
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO real_prices (time, ticker, price, source, market_status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (time, ticker) DO NOTHING
            """,
            [
                (
                    now,
                    ticker,
                    float(price),
                    "yfinance" if ticker in yfinance_tickers else "db_fallback",
                    "unknown",
                    now,
                )
                for ticker, price in prices.items()
            ],
        )

    # Update Redis cache
    if redis_client is not None:
        try:
            import redis.asyncio as aioredis  # type: ignore[import]
            rc = redis_client  # type: ignore[assignment]
            cache_value = {t: str(p) for t, p in prices.items()}
            await rc.set("sse:prices:current", json.dumps(cache_value), ex=120)
        except Exception:
            logger.warning("Failed to update Redis price cache", exc_info=True)

    logger.info("Fetched real prices for %d tickers", len(prices))
    return prices

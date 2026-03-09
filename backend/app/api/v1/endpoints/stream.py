"""SSE streaming endpoints.

Route registration order matters:
  /tickers/stream       — registered FIRST (global feed)
  /tickers/{ticker}/stream — registered SECOND (per-ticker)
FastAPI matches routes top-down so "stream" is never treated as a ticker symbol.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()
logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 30  # seconds


async def _event_generator(
    queue: asyncio.Queue[str],
    keepalive_interval: int = _KEEPALIVE_INTERVAL,
) -> AsyncGenerator[str, None]:
    """Yield SSE events from queue, with periodic keepalives."""
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=keepalive_interval)
            if event == "CLOSE":
                return
            yield event
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"


@router.get(
    "/stream",
    summary="Global SSE stream — all active tickers",
    response_class=StreamingResponse,
)
async def global_stream(request: Request) -> StreamingResponse:
    """SSE endpoint streaming price updates for all active tickers."""
    sse_manager = request.app.state.sse_manager
    pool: asyncpg.Pool = request.app.state.db_pool
    queue = await sse_manager.connect_global()

    # Send initial snapshot of all current prices
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.symbol AS ticker,
                       sp.sentiment_price, sp.real_price_at_calc AS real_price,
                       sp.sentiment_delta
                FROM tickers t
                LEFT JOIN LATERAL (
                    SELECT sentiment_price, real_price_at_calc, sentiment_delta
                    FROM sentiment_prices
                    WHERE ticker = t.symbol
                    ORDER BY time DESC
                    LIMIT 1
                ) sp ON true
                WHERE t.is_active = true
                ORDER BY t.symbol
                """
            )
    except Exception:
        await sse_manager.disconnect_global(queue)
        raise HTTPException(status_code=503, detail="Database unavailable")

    snapshot = {
        "tickers": [
            {
                "ticker": r["ticker"],
                "sentiment_price": float(r["sentiment_price"]) if r["sentiment_price"] is not None else None,
                "real_price": float(r["real_price"]) if r["real_price"] is not None else None,
                "sentiment_delta": float(r["sentiment_delta"]) if r["sentiment_delta"] is not None else 0.0,
            }
            for r in rows
        ],
    }
    await queue.put(f"event: all_tickers_snapshot\ndata: {json.dumps(snapshot)}\n\n")

    async def _gen() -> AsyncGenerator[str, None]:
        try:
            async for event in _event_generator(queue):
                yield event
        finally:
            await sse_manager.disconnect_global(queue)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{ticker}/stream",
    summary="Per-ticker SSE stream",
    response_class=StreamingResponse,
)
async def ticker_stream(ticker: str, request: Request) -> StreamingResponse:
    """SSE endpoint streaming price updates for a single ticker."""
    ticker = ticker.upper()
    pool: asyncpg.Pool = request.app.state.db_pool

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM tickers WHERE symbol = $1 AND is_active = true", ticker
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")

    sse_manager = request.app.state.sse_manager
    queue = await sse_manager.connect_ticker(ticker)

    # Send current price as first event
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT sentiment_price, real_price_at_calc AS real_price, sentiment_delta
                FROM sentiment_prices
                WHERE ticker = $1
                ORDER BY time DESC
                LIMIT 1
                """,
                ticker,
            )
    except Exception:
        await sse_manager.disconnect_ticker(ticker, queue)
        raise HTTPException(status_code=503, detail="Database unavailable")

    if row:
        initial = {
            "ticker": ticker,
            "sentiment_price": float(row["sentiment_price"]) if row["sentiment_price"] is not None else None,
            "real_price": float(row["real_price"]) if row["real_price"] is not None else None,
            "sentiment_delta": float(row["sentiment_delta"]) if row["sentiment_delta"] is not None else 0.0,
        }
        await queue.put(f"event: price_update\ndata: {json.dumps(initial)}\n\n")

    async def _gen() -> AsyncGenerator[str, None]:
        try:
            async for event in _event_generator(queue):
                yield event
        finally:
            await sse_manager.disconnect_ticker(ticker, queue)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

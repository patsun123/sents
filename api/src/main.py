"""SentiX Dashboard API — serves signal data and the frontend dashboard."""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://sentix:sentix@postgres:5432/sentix")

engine = create_async_engine(DATABASE_URL, echo=False)
session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

_DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text()

# In-memory TTL caches: key -> (fetched_at, payload)
_PRICE_CACHE: dict[str, tuple[float, Any]] = {}
_INFO_CACHE: dict[str, tuple[float, Any]] = {}
_PRICE_CACHE_TTL = 300  # seconds
_INFO_CACHE_TTL = 3600  # 1 hour — metadata rarely changes

# Module-level httpx client, created in lifespan
_http_client: httpx.AsyncClient | None = None

_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SentiX-Dashboard/1.0; "
        "+https://github.com/patsun123/sents)"
    )
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _http_client
    _http_client = httpx.AsyncClient(timeout=10.0, headers=_YAHOO_HEADERS)
    try:
        yield
    finally:
        await _http_client.aclose()
        await engine.dispose()


app = FastAPI(title="SentiX Dashboard", lifespan=lifespan)


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(_DASHBOARD_HTML)


@app.get("/api/tickers")
async def get_tickers() -> JSONResponse:
    try:
        async with session_factory() as session:
            result = await session.execute(text("""
                SELECT
                    ticker_symbol,
                    COUNT(*) AS mention_count,
                    SUM(sentiment_polarity * (upvote_weight + 1)) AS net_score,
                    COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                    COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                    MAX(collected_at) AS last_seen,
                    string_agg(DISTINCT source_subreddit, ' · '
                        ORDER BY source_subreddit) AS subreddits
                FROM sentiment_signals
                WHERE collected_at >= NOW() - INTERVAL '24 hours'
                GROUP BY ticker_symbol
                ORDER BY COUNT(*) DESC
                LIMIT 100
            """))
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse([
        {
            "ticker": r["ticker_symbol"],
            "mention_count": int(r["mention_count"]),
            "net_score": int(r["net_score"] or 0),
            "positive_count": int(r["positive_count"]),
            "negative_count": int(r["negative_count"]),
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            "subreddits": r["subreddits"] or "",
        }
        for r in rows
    ])


@app.get("/api/tickers/search")
async def search_tickers(q: str = "") -> JSONResponse:
    """Search all tickers ever seen in the system.

    Returns tickers matching the query (prefix match), ordered by total
    mention count all-time. If no query, returns the top 50 most-mentioned.
    """
    q = q.strip().upper()
    try:
        async with session_factory() as session:
            if q:
                result = await session.execute(
                    text("""
                        SELECT
                            ticker_symbol,
                            COUNT(*) AS total_mentions,
                            MAX(collected_at) AS last_seen
                        FROM sentiment_signals
                        WHERE ticker_symbol LIKE :prefix
                        GROUP BY ticker_symbol
                        ORDER BY COUNT(*) DESC
                        LIMIT 30
                    """),
                    {"prefix": q + "%"},
                )
            else:
                result = await session.execute(text("""
                    SELECT
                        ticker_symbol,
                        COUNT(*) AS total_mentions,
                        MAX(collected_at) AS last_seen
                    FROM sentiment_signals
                    GROUP BY ticker_symbol
                    ORDER BY COUNT(*) DESC
                    LIMIT 50
                """))
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse([
        {
            "ticker": r["ticker_symbol"],
            "total_mentions": int(r["total_mentions"]),
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
        }
        for r in rows
    ])


@app.get("/api/runs")
async def get_runs() -> JSONResponse:
    try:
        async with session_factory() as session:
            result = await session.execute(text("""
                SELECT id, started_at, completed_at, status,
                       signals_stored, comments_processed,
                       sources_attempted, sources_succeeded,
                       error_summary
                FROM collection_runs
                ORDER BY started_at DESC
                LIMIT 12
            """))
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse([
        {
            "id": str(r["id"]),
            "started_at": r["started_at"].isoformat(),
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "status": r["status"],
            "signals_stored": int(r["signals_stored"]),
            "comments_processed": int(r["comments_processed"]),
            "sources_attempted": int(r["sources_attempted"]),
            "sources_succeeded": int(r["sources_succeeded"]),
            "error_summary": r["error_summary"],
        }
        for r in rows
    ])


@app.get("/api/subreddits")
async def get_subreddits() -> JSONResponse:
    """Per-subreddit signal breakdown for the last 24 hours.

    Uses a CTE with ROW_NUMBER() to pull the top-5 tickers per subreddit
    without a separate round-trip.  'threads_parsed' is not stored by the
    worker (zero-PII policy means no post/thread IDs), so signal_count is
    the closest meaningful proxy.
    """
    try:
        async with session_factory() as session:
            result = await session.execute(text("""
                WITH stats AS (
                    SELECT
                        source_subreddit,
                        COUNT(*) AS signal_count,
                        COUNT(DISTINCT ticker_symbol) AS tickers_found,
                        COUNT(*) FILTER (WHERE sentiment_polarity =  1) AS positive_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                        MAX(collected_at) AS last_active
                    FROM sentiment_signals
                    WHERE collected_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY source_subreddit
                ),
                ranked_tickers AS (
                    SELECT
                        source_subreddit,
                        ticker_symbol,
                        COUNT(*) AS cnt,
                        ROW_NUMBER() OVER (
                            PARTITION BY source_subreddit
                            ORDER BY COUNT(*) DESC
                        ) AS rn
                    FROM sentiment_signals
                    WHERE collected_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY source_subreddit, ticker_symbol
                ),
                top_tickers AS (
                    SELECT source_subreddit,
                           string_agg(ticker_symbol, ' · ' ORDER BY cnt DESC) AS top_tickers
                    FROM ranked_tickers
                    WHERE rn <= 5
                    GROUP BY source_subreddit
                )
                SELECT s.*, t.top_tickers
                FROM stats s
                LEFT JOIN top_tickers t USING (source_subreddit)
                ORDER BY s.signal_count DESC
            """))
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse([
        {
            "subreddit": r["source_subreddit"],
            "signal_count": int(r["signal_count"]),
            "tickers_found": int(r["tickers_found"]),
            "positive_count": int(r["positive_count"]),
            "negative_count": int(r["negative_count"]),
            "last_active": r["last_active"].isoformat() if r["last_active"] else None,
            "top_tickers": r["top_tickers"] or "",
        }
        for r in rows
    ])


@app.get("/api/signals/recent")
async def get_recent_signals() -> JSONResponse:
    try:
        async with session_factory() as session:
            result = await session.execute(text("""
                SELECT ticker_symbol, sentiment_polarity, upvote_weight,
                       collected_at, source_subreddit
                FROM sentiment_signals
                ORDER BY collected_at DESC
                LIMIT 60
            """))
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse([
        {
            "ticker": r["ticker_symbol"],
            "polarity": int(r["sentiment_polarity"]),
            "upvotes": int(r["upvote_weight"]),
            "collected_at": r["collected_at"].isoformat(),
            "subreddit": r["source_subreddit"],
        }
        for r in rows
    ])


_VALID_RANGES = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}
_VALID_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h", "1d", "5d", "1wk", "1mo"}


@app.get("/api/tickers/{symbol}/price")
async def get_ticker_price(
    symbol: str,
    range: str = "1mo",
    interval: str = "1d",
) -> JSONResponse:
    """Proxy Yahoo Finance chart data for a single ticker.

    Accepts range (1d,5d,1mo,3mo,6mo,1y,2y,5y,ytd,max) and
    interval (1m,5m,15m,30m,60m,1h,1d,1wk,1mo) query params.
    Results are cached in-memory for 5 minutes per symbol+range+interval.
    """
    symbol = symbol.upper()
    if range not in _VALID_RANGES:
        raise HTTPException(status_code=400, detail=f"Invalid range: {range}")
    if interval not in _VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval: {interval}")

    cache_key = f"{symbol}:{range}:{interval}"

    # Serve from cache if still fresh
    cached = _PRICE_CACHE.get(cache_key)
    if cached is not None:
        fetched_at, payload = cached
        if time.monotonic() - fetched_at < _PRICE_CACHE_TTL:
            return JSONResponse(payload)

    assert _http_client is not None, "httpx client not initialised"

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={range}&interval={interval}"
    )
    try:
        response = await _http_client.get(url)
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Yahoo Finance returned {exc.response.status_code} for {symbol}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Yahoo Finance: {exc}",
        ) from exc

    try:
        result0 = raw["chart"]["result"][0]
        meta = result0.get("meta", {})
        currency = meta.get("currency", "USD")
        timestamps: list[int] = result0["timestamp"]
        quote = result0["indicators"]["quote"][0]
        opens: list[float | None] = quote.get("open", [])
        highs: list[float | None] = quote.get("high", [])
        lows: list[float | None] = quote.get("low", [])
        closes: list[float | None] = quote.get("close", [])
        volumes: list[int | None] = quote.get("volume", [])
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected Yahoo Finance response shape for {symbol}: {exc}",
        ) from exc

    # For intraday intervals, include time in the timestamp
    intraday = interval in {"1m", "2m", "5m", "15m", "30m", "60m", "1h"}
    ts_fmt = "%Y-%m-%dT%H:%M:%S" if intraday else "%Y-%m-%d"

    data = [
        {
            "timestamp": time.strftime(ts_fmt, time.gmtime(ts)),
            "open": opens[i],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
            "volume": volumes[i],
        }
        for i, ts in enumerate(timestamps)
        if closes[i] is not None
    ]

    payload = {"symbol": symbol, "currency": currency, "range": range,
               "interval": interval, "data": data}
    _PRICE_CACHE[cache_key] = (time.monotonic(), payload)
    return JSONResponse(payload)


_VALID_LOOKBACKS = {"1d", "7d", "1mo", "3mo", "6mo", "1y"}
_LOOKBACK_SQL: dict[str, tuple[str, str]] = {
    # lookback -> (interval expression, date_trunc bucket)
    "1d":  ("1 day",    "hour"),
    "7d":  ("7 days",   "hour"),
    "1mo": ("30 days",  "day"),
    "3mo": ("90 days",  "day"),
    "6mo": ("180 days", "week"),
    "1y":  ("365 days", "week"),
}


@app.get("/api/tickers/{symbol}/sentiment-history")
async def get_ticker_sentiment_history(
    symbol: str,
    lookback: str = "7d",
) -> JSONResponse:
    """Sentiment aggregates for a ticker, bucketed by time.

    The lookback param controls the time window and bucket granularity:
    1d/7d → hourly, 1mo/3mo → daily, 6mo/1y → weekly.
    """
    symbol = symbol.upper()
    if lookback not in _LOOKBACK_SQL:
        raise HTTPException(status_code=400, detail=f"Invalid lookback: {lookback}")

    interval_expr, bucket_fn = _LOOKBACK_SQL[lookback]

    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    SELECT
                        date_trunc(:bucket, collected_at) AS bucket,
                        COUNT(*) AS mention_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1)  AS positive,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative,
                        SUM(sentiment_polarity * (upvote_weight + 1))   AS net_score
                    FROM sentiment_signals
                    WHERE ticker_symbol = :symbol
                      AND collected_at >= NOW() - INTERVAL '{interval_expr}'
                    GROUP BY bucket
                    ORDER BY bucket
                """),
                {"symbol": symbol, "bucket": bucket_fn},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse({
        "symbol": symbol,
        "lookback": lookback,
        "data": [
            {
                "timestamp": r["bucket"].isoformat(),
                "positive": int(r["positive"]),
                "negative": int(r["negative"]),
                "net_score": int(r["net_score"] or 0),
                "mention_count": int(r["mention_count"]),
            }
            for r in rows
        ],
    })


@app.get("/api/tickers/{symbol}/info")
async def get_ticker_info(symbol: str) -> JSONResponse:
    """Basic stock metadata from Yahoo Finance chart endpoint.

    Uses the chart API's meta field (no auth required). Cached for 1 hour.
    """
    symbol = symbol.upper()

    cached = _INFO_CACHE.get(symbol)
    if cached is not None:
        fetched_at, payload = cached
        if time.monotonic() - fetched_at < _INFO_CACHE_TTL:
            return JSONResponse(payload)

    assert _http_client is not None, "httpx client not initialised"

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=1d&interval=1d"
    )
    try:
        response = await _http_client.get(url)
        response.raise_for_status()
        raw = response.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Yahoo Finance lookup failed for {symbol}: {exc}",
        ) from exc

    try:
        meta = raw["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected Yahoo Finance response for {symbol}: {exc}",
        ) from exc

    def _fmt_vol(val: int | None) -> str | None:
        if val is None:
            return None
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"{val / 1_000:.0f}K"
        return str(val)

    payload = {
        "symbol": symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "—",
        "type": meta.get("instrumentType", "—"),
        "currency": meta.get("currency", "USD"),
        "timezone": meta.get("timezone", "—"),
        "regular_market_price": meta.get("regularMarketPrice"),
        "previous_close": meta.get("chartPreviousClose"),
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
        "volume": meta.get("regularMarketVolume"),
        "volume_fmt": _fmt_vol(meta.get("regularMarketVolume")),
    }

    _INFO_CACHE[symbol] = (time.monotonic(), payload)
    return JSONResponse(payload)


@app.get("/api/tickers/{symbol}")
async def get_ticker(symbol: str) -> JSONResponse:
    """Detail stats for a single ticker over the last 24 hours."""
    symbol = symbol.upper()
    try:
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT
                        ticker_symbol,
                        COUNT(*) AS mention_count,
                        SUM(sentiment_polarity * (upvote_weight + 1)) AS net_score,
                        COUNT(*) FILTER (WHERE sentiment_polarity =  1) AS positive_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                        MAX(collected_at) AS last_seen,
                        string_agg(DISTINCT source_subreddit, ' · '
                            ORDER BY source_subreddit) AS subreddits
                    FROM sentiment_signals
                    WHERE ticker_symbol = :symbol
                      AND collected_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY ticker_symbol
                """),
                {"symbol": symbol},
            )
            row = result.mappings().first()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    return JSONResponse({
        "ticker": row["ticker_symbol"],
        "mention_count": int(row["mention_count"]),
        "net_score": int(row["net_score"] or 0),
        "positive_count": int(row["positive_count"]),
        "negative_count": int(row["negative_count"]),
        "subreddits": row["subreddits"] or "",
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
    })

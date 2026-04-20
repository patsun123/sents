"""SentiX Dashboard API — serves signal data and the frontend dashboard."""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
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

_DASHBOARD_TEMPLATE = (Path(__file__).parent / "dashboard.html").read_text()
_EPIC_DASHBOARD_TEMPLATE = (Path(__file__).parent / "epic_dashboard.html").read_text()

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

@dataclass(frozen=True)
class StorefrontConfig:
    slug: str
    entity_key: str
    display_name: str
    short_name: str
    api_base: str
    summary_copy: str
    community_note: str
    signals_note: str
    formula_note: str
    empty_history: str
    empty_communities: str
    empty_signals: str
    community_weight_note: str
    community_weights: dict[str, float]


_STOREFRONTS: dict[str, StorefrontConfig] = {
    "epic": StorefrontConfig(
        slug="epic",
        entity_key="EGS_STORE",
        display_name="Epic Games Store",
        short_name="Epic",
        api_base="/api/epic",
        summary_copy="Weighted sentiment built from Reddit posts and comments about the Epic Games Store.",
        community_note="Where Epic sentiment is forming and how much each subreddit is contributing.",
        signals_note="Thread-grouped Epic store signals so posts and comment clusters stay together.",
        formula_note="How Epic sentiment scores are currently derived from raw post and comment signals.",
        empty_history="No Epic sentiment history yet for this window.",
        empty_communities="No matching Epic community signals yet.",
        empty_signals="No recent Epic signals yet.",
        community_weight_note="Community weights currently favor Epic/deal-focused communities and discount adversarial ones like `fuckepic`.",
        community_weights={
            "EpicGamesPC": 1.25,
            "pcgaming": 1.0,
            "pcmasterrace": 1.0,
            "Steam": 0.9,
            "GamingLeaksAndRumours": 1.0,
            "truegaming": 1.0,
            "patientgamers": 0.95,
            "GameDeals": 1.15,
            "FreeGameFindings": 1.1,
            "ShouldIbuythisgame": 0.9,
            "fuckepic": 0.75,
        },
    ),
    "steam": StorefrontConfig(
        slug="steam",
        entity_key="STEAM_STOR",
        display_name="Steam Store",
        short_name="Steam",
        api_base="/api/steam",
        summary_copy="Weighted sentiment built from Reddit posts and comments about the Steam store and client.",
        community_note="Where Steam store sentiment is forming and how much each subreddit is contributing.",
        signals_note="Thread-grouped Steam store signals so comparative discussions stay attached to the source thread.",
        formula_note="How Steam sentiment scores are currently derived from raw post and comment signals.",
        empty_history="No Steam sentiment history yet for this window.",
        empty_communities="No matching Steam community signals yet.",
        empty_signals="No recent Steam signals yet.",
        community_weight_note="Community weights currently favor Steam-focused and broader PC gaming communities while keeping explicitly adversarial pockets lower.",
        community_weights={
            "Steam": 1.25,
            "pcgaming": 1.05,
            "pcmasterrace": 1.05,
            "GamingLeaksAndRumours": 1.0,
            "truegaming": 1.0,
            "patientgamers": 1.0,
            "GameDeals": 1.1,
            "FreeGameFindings": 0.9,
            "ShouldIbuythisgame": 0.95,
            "EpicGamesPC": 0.85,
            "fuckepic": 0.9,
        },
    ),
}


def _get_storefront(slug: str) -> StorefrontConfig:
    storefront = _STOREFRONTS.get(slug.lower())
    if storefront is None:
        raise HTTPException(status_code=404, detail=f"Unknown storefront: {slug}")
    return storefront


def _render_dashboard_html(storefront: StorefrontConfig) -> str:
    config = {
        "slug": storefront.slug,
        "entityKey": storefront.entity_key,
        "displayName": storefront.display_name,
        "shortName": storefront.short_name,
        "apiBase": storefront.api_base,
        "summaryCopy": storefront.summary_copy,
        "communityNote": storefront.community_note,
        "signalsNote": storefront.signals_note,
        "formulaNote": storefront.formula_note,
        "emptyHistory": storefront.empty_history,
        "emptyCommunities": storefront.empty_communities,
        "emptySignals": storefront.empty_signals,
        "communityWeightNote": storefront.community_weight_note,
    }
    return (
        _DASHBOARD_TEMPLATE.replace(
            "__PAGE_HEAD_TITLE__",
            f"SentiX | {storefront.display_name} Sentiment",
        )
        .replace(
            "__PAGE_HERO_TITLE__",
            f"{storefront.display_name} Sentiment",
        )
        .replace(
        "__DASHBOARD_CONFIG__",
        json.dumps(config),
        )
    )


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(_EPIC_DASHBOARD_TEMPLATE)


@app.get("/epic")
async def epic_dashboard() -> HTMLResponse:
    return HTMLResponse(_EPIC_DASHBOARD_TEMPLATE)


@app.get("/steam")
async def steam_dashboard() -> HTMLResponse:
    return HTMLResponse(_render_dashboard_html(_STOREFRONTS["steam"]))


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
                    string_agg(DISTINCT source_subreddit, ' | '
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
                SELECT ticker_symbol, sentiment_polarity, upvote_weight, reply_count,
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
            "reply_count": int(r["reply_count"]),
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

def _storefront_subreddit_weight_sql(
    storefront: StorefrontConfig,
    column: str = "source_subreddit",
) -> str:
    cases = " ".join(
        f"WHEN '{community}' THEN {weight}"
        for community, weight in storefront.community_weights.items()
    )
    return f"CASE {column} {cases} ELSE 0.85 END"


def _storefront_weighted_score_sql(
    storefront: StorefrontConfig,
    polarity_col: str = "sentiment_polarity",
    upvotes_col: str = "upvote_weight",
    reply_count_col: str = "reply_count",
    subreddit_col: str = "source_subreddit",
    content_type_col: str = "source_content_type",
) -> str:
    subreddit_weight = _storefront_subreddit_weight_sql(storefront, subreddit_col)
    # Posts keep the stronger headline-level bonus. Comments get only a mild,
    # capped engagement lift from replies so long discussions matter slightly
    # more without letting massive threads dominate the aggregate.
    return (
        f"({polarity_col} * LN({upvotes_col} + 2) * "
        f"(CASE {content_type_col} "
        f"WHEN 'post' THEN 1.35 "
        f"ELSE (1.0 + LEAST(LN({reply_count_col} + 1), 1.5) * 0.1) "
        f"END) * "
        f"({subreddit_weight}))"
    )


_EPIC_ENTITY = _STOREFRONTS["epic"].entity_key
_STEAM_ENTITY = _STOREFRONTS["steam"].entity_key


def _epic_subreddit_weight_sql(column: str = "source_subreddit") -> str:
    return _storefront_subreddit_weight_sql(_STOREFRONTS["epic"], column)


def _steam_subreddit_weight_sql(column: str = "source_subreddit") -> str:
    return _storefront_subreddit_weight_sql(_STOREFRONTS["steam"], column)


def _epic_weighted_score_sql(
    polarity_col: str = "sentiment_polarity",
    upvotes_col: str = "upvote_weight",
    reply_count_col: str = "reply_count",
    subreddit_col: str = "source_subreddit",
    content_type_col: str = "source_content_type",
) -> str:
    return _storefront_weighted_score_sql(
        _STOREFRONTS["epic"],
        polarity_col,
        upvotes_col,
        reply_count_col,
        subreddit_col,
        content_type_col,
    )


def _steam_weighted_score_sql(
    polarity_col: str = "sentiment_polarity",
    upvotes_col: str = "upvote_weight",
    reply_count_col: str = "reply_count",
    subreddit_col: str = "source_subreddit",
    content_type_col: str = "source_content_type",
) -> str:
    return _storefront_weighted_score_sql(
        _STOREFRONTS["steam"],
        polarity_col,
        upvotes_col,
        reply_count_col,
        subreddit_col,
        content_type_col,
    )


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


@app.get("/api/epic/overview")
async def get_epic_overview(lookback: str = "1d") -> JSONResponse:
    """Summary for the Epic Games Store sentiment tracker over the given window.

    ``lookback`` accepts the same values as ``/api/epic/sentiment-history``:
    ``1d``, ``7d``, ``1mo``, ``3mo``, ``6mo``, ``1y``. Defaults to ``1d`` so
    existing callers that don't pass the param still get 24-hour summaries.
    """
    if lookback not in _LOOKBACK_SQL:
        raise HTTPException(status_code=400, detail=f"Invalid lookback: {lookback}")
    interval_expr, _ = _LOOKBACK_SQL[lookback]

    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    SELECT
                        COUNT(*) AS mention_count,
                        ROUND(SUM({_epic_weighted_score_sql()})::numeric, 2) AS weighted_score,
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                        MAX(collected_at) AS last_seen,
                        string_agg(DISTINCT source_subreddit, ' | '
                            ORDER BY source_subreddit) AS communities
                    FROM sentiment_signals
                    WHERE ticker_symbol = :entity
                      AND collected_at >= NOW() - INTERVAL '{interval_expr}'
                """),
                {"entity": _EPIC_ENTITY},
            )
            row = result.mappings().one()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        {
            "entity": _EPIC_ENTITY,
            "display_name": "Epic Games Store",
            "lookback": lookback,
            "mention_count": int(row["mention_count"] or 0),
            "weighted_score": float(row["weighted_score"] or 0),
            "positive_count": int(row["positive_count"] or 0),
            "negative_count": int(row["negative_count"] or 0),
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            "communities": row["communities"] or "",
        }
    )


@app.get("/api/epic/sentiment-history")
async def get_epic_sentiment_history(lookback: str = "7d") -> JSONResponse:
    """Time-bucketed sentiment history for the Epic Games Store."""
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
                        ROUND(SUM({_epic_weighted_score_sql()})::numeric, 2) AS weighted_score
                    FROM sentiment_signals
                    WHERE ticker_symbol = :entity
                      AND collected_at >= NOW() - INTERVAL '{interval_expr}'
                    GROUP BY bucket
                    ORDER BY bucket
                """),
                {"entity": _EPIC_ENTITY, "bucket": bucket_fn},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        {
            "entity": _EPIC_ENTITY,
            "display_name": "Epic Games Store",
            "lookback": lookback,
            "data": [
                {
                    "timestamp": r["bucket"].isoformat(),
                    "positive": int(r["positive"]),
                    "negative": int(r["negative"]),
                    "weighted_score": float(r["weighted_score"] or 0),
                    "mention_count": int(r["mention_count"]),
                }
                for r in rows
            ],
        }
    )


@app.get("/api/epic/communities")
async def get_epic_communities(lookback: str = "1d") -> JSONResponse:
    """Per-community Epic Games Store sentiment breakdown over the given window.

    ``lookback`` accepts the same values as ``/api/epic/sentiment-history``.
    Defaults to ``1d`` to preserve the previous 24-hour behavior for any
    callers that don't pass the param.
    """
    if lookback not in _LOOKBACK_SQL:
        raise HTTPException(status_code=400, detail=f"Invalid lookback: {lookback}")
    interval_expr, _ = _LOOKBACK_SQL[lookback]

    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    SELECT
                        source_subreddit,
                        COUNT(*) AS mention_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                        ROUND(SUM({_epic_weighted_score_sql(subreddit_col='source_subreddit')})::numeric, 2) AS weighted_score,
                        COUNT(*) FILTER (WHERE source_content_type = 'post') AS post_count,
                        COUNT(*) FILTER (WHERE source_content_type = 'comment') AS comment_count,
                        MAX(collected_at) AS last_seen
                    FROM sentiment_signals
                    WHERE ticker_symbol = :entity
                      AND collected_at >= NOW() - INTERVAL '{interval_expr}'
                    GROUP BY source_subreddit
                    ORDER BY mention_count DESC, source_subreddit
                """),
                {"entity": _EPIC_ENTITY},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        [
            {
                "community": row["source_subreddit"],
                "mention_count": int(row["mention_count"]),
                "positive_count": int(row["positive_count"]),
                "negative_count": int(row["negative_count"]),
                "weighted_score": float(row["weighted_score"] or 0),
                "post_count": int(row["post_count"]),
                "comment_count": int(row["comment_count"]),
                "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            }
            for row in rows
        ]
    )


@app.get("/api/epic/recent-signals")
async def get_epic_recent_signals() -> JSONResponse:
    """Recent Epic Games Store sentiment grouped by thread."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    WITH recent AS (
                        SELECT
                            sentiment_polarity,
                            upvote_weight,
                            reply_count,
                            collected_at,
                            source_subreddit,
                            source_thread_url,
                            source_content_type,
                            ({_epic_weighted_score_sql()}) AS weighted_score
                        FROM sentiment_signals
                        WHERE ticker_symbol = :entity
                        ORDER BY collected_at DESC
                        LIMIT 200
                    ),
                    grouped AS (
                        SELECT
                            COALESCE(
                                NULLIF(source_thread_url, ''),
                                CONCAT(
                                    'ungrouped:',
                                    source_subreddit,
                                    ':',
                                    EXTRACT(EPOCH FROM collected_at)::bigint,
                                    ':',
                                    source_content_type,
                                    ':',
                                    upvote_weight
                                )
                            ) AS thread_group,
                            MAX(NULLIF(source_thread_url, '')) AS thread_url,
                            MAX(collected_at) AS latest_collected_at,
                            MIN(collected_at) AS first_collected_at,
                            string_agg(DISTINCT source_subreddit, ' | ' ORDER BY source_subreddit) AS communities,
                            COUNT(*) AS signal_count,
                            COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                            COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                            COUNT(*) FILTER (WHERE source_content_type = 'post') AS post_count,
                            COUNT(*) FILTER (WHERE source_content_type = 'comment') AS comment_count,
                            MAX(upvote_weight) AS max_upvotes,
                            MAX(reply_count) AS max_reply_count,
                            ROUND(SUM(weighted_score)::numeric, 2) AS weighted_score
                        FROM recent
                        GROUP BY thread_group
                    )
                    SELECT
                        thread_url,
                        latest_collected_at,
                        first_collected_at,
                        communities,
                        signal_count,
                        positive_count,
                        negative_count,
                        post_count,
                        comment_count,
                        max_upvotes,
                        max_reply_count,
                        weighted_score
                    FROM grouped
                    ORDER BY latest_collected_at DESC
                    LIMIT 20
                """),
                {"entity": _EPIC_ENTITY},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        [
            {
                "entity": _EPIC_ENTITY,
                "weighted_score": float(row["weighted_score"] or 0),
                "signal_count": int(row["signal_count"] or 0),
                "positive_count": int(row["positive_count"] or 0),
                "negative_count": int(row["negative_count"] or 0),
                "post_count": int(row["post_count"] or 0),
                "comment_count": int(row["comment_count"] or 0),
                "upvotes": int(row["max_upvotes"] or 0),
                "reply_count": int(row["max_reply_count"] or 0),
                "collected_at": row["latest_collected_at"].isoformat(),
                "first_collected_at": row["first_collected_at"].isoformat(),
                "community": row["communities"] or "",
                "thread_url": row["thread_url"] or None,
            }
            for row in rows
        ]
    )


@app.get("/api/steam/overview")
async def get_steam_overview() -> JSONResponse:
    """24h summary for the Steam Store sentiment tracker."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    SELECT
                        COUNT(*) AS mention_count,
                        ROUND(SUM({_steam_weighted_score_sql()})::numeric, 2) AS weighted_score,
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                        MAX(collected_at) AS last_seen,
                        string_agg(DISTINCT source_subreddit, ' | '
                            ORDER BY source_subreddit) AS communities
                    FROM sentiment_signals
                    WHERE ticker_symbol = :entity
                      AND collected_at >= NOW() - INTERVAL '24 hours'
                """),
                {"entity": _STEAM_ENTITY},
            )
            row = result.mappings().one()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        {
            "entity": _STEAM_ENTITY,
            "display_name": "Steam Store",
            "mention_count": int(row["mention_count"] or 0),
            "weighted_score": float(row["weighted_score"] or 0),
            "positive_count": int(row["positive_count"] or 0),
            "negative_count": int(row["negative_count"] or 0),
            "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            "communities": row["communities"] or "",
        }
    )


@app.get("/api/steam/sentiment-history")
async def get_steam_sentiment_history(lookback: str = "7d") -> JSONResponse:
    """Time-bucketed sentiment history for the Steam Store."""
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
                        ROUND(SUM({_steam_weighted_score_sql()})::numeric, 2) AS weighted_score
                    FROM sentiment_signals
                    WHERE ticker_symbol = :entity
                      AND collected_at >= NOW() - INTERVAL '{interval_expr}'
                    GROUP BY bucket
                    ORDER BY bucket
                """),
                {"entity": _STEAM_ENTITY, "bucket": bucket_fn},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        {
            "entity": _STEAM_ENTITY,
            "display_name": "Steam Store",
            "lookback": lookback,
            "data": [
                {
                    "timestamp": r["bucket"].isoformat(),
                    "positive": int(r["positive"]),
                    "negative": int(r["negative"]),
                    "weighted_score": float(r["weighted_score"] or 0),
                    "mention_count": int(r["mention_count"]),
                }
                for r in rows
            ],
        }
    )


@app.get("/api/steam/communities")
async def get_steam_communities() -> JSONResponse:
    """Per-community Steam Store sentiment breakdown for the last 24 hours."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    SELECT
                        source_subreddit,
                        COUNT(*) AS mention_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                        COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                        ROUND(SUM({_steam_weighted_score_sql(subreddit_col='source_subreddit')})::numeric, 2) AS weighted_score,
                        COUNT(*) FILTER (WHERE source_content_type = 'post') AS post_count,
                        COUNT(*) FILTER (WHERE source_content_type = 'comment') AS comment_count,
                        MAX(collected_at) AS last_seen
                    FROM sentiment_signals
                    WHERE ticker_symbol = :entity
                      AND collected_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY source_subreddit
                    ORDER BY mention_count DESC, source_subreddit
                """),
                {"entity": _STEAM_ENTITY},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        [
            {
                "community": row["source_subreddit"],
                "mention_count": int(row["mention_count"]),
                "positive_count": int(row["positive_count"]),
                "negative_count": int(row["negative_count"]),
                "weighted_score": float(row["weighted_score"] or 0),
                "post_count": int(row["post_count"]),
                "comment_count": int(row["comment_count"]),
                "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
            }
            for row in rows
        ]
    )


@app.get("/api/steam/recent-signals")
async def get_steam_recent_signals() -> JSONResponse:
    """Recent Steam Store sentiment grouped by thread."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                text(f"""
                    WITH recent AS (
                        SELECT
                            sentiment_polarity,
                            upvote_weight,
                            reply_count,
                            collected_at,
                            source_subreddit,
                            source_thread_url,
                            source_content_type,
                            ({_steam_weighted_score_sql()}) AS weighted_score
                        FROM sentiment_signals
                        WHERE ticker_symbol = :entity
                        ORDER BY collected_at DESC
                        LIMIT 200
                    ),
                    grouped AS (
                        SELECT
                            COALESCE(
                                NULLIF(source_thread_url, ''),
                                CONCAT(
                                    'ungrouped:',
                                    source_subreddit,
                                    ':',
                                    EXTRACT(EPOCH FROM collected_at)::bigint,
                                    ':',
                                    source_content_type,
                                    ':',
                                    upvote_weight
                                )
                            ) AS thread_group,
                            MAX(NULLIF(source_thread_url, '')) AS thread_url,
                            MAX(collected_at) AS latest_collected_at,
                            MIN(collected_at) AS first_collected_at,
                            string_agg(DISTINCT source_subreddit, ' | ' ORDER BY source_subreddit) AS communities,
                            COUNT(*) AS signal_count,
                            COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive_count,
                            COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative_count,
                            COUNT(*) FILTER (WHERE source_content_type = 'post') AS post_count,
                            COUNT(*) FILTER (WHERE source_content_type = 'comment') AS comment_count,
                            MAX(upvote_weight) AS max_upvotes,
                            MAX(reply_count) AS max_reply_count,
                            ROUND(SUM(weighted_score)::numeric, 2) AS weighted_score
                        FROM recent
                        GROUP BY thread_group
                    )
                    SELECT
                        thread_url,
                        latest_collected_at,
                        first_collected_at,
                        communities,
                        signal_count,
                        positive_count,
                        negative_count,
                        post_count,
                        comment_count,
                        max_upvotes,
                        max_reply_count,
                        weighted_score
                    FROM grouped
                    ORDER BY latest_collected_at DESC
                    LIMIT 20
                """),
                {"entity": _STEAM_ENTITY},
            )
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        [
            {
                "entity": _STEAM_ENTITY,
                "weighted_score": float(row["weighted_score"] or 0),
                "signal_count": int(row["signal_count"] or 0),
                "positive_count": int(row["positive_count"] or 0),
                "negative_count": int(row["negative_count"] or 0),
                "post_count": int(row["post_count"] or 0),
                "comment_count": int(row["comment_count"] or 0),
                "upvotes": int(row["max_upvotes"] or 0),
                "reply_count": int(row["max_reply_count"] or 0),
                "collected_at": row["latest_collected_at"].isoformat(),
                "first_collected_at": row["first_collected_at"].isoformat(),
                "community": row["communities"] or "",
                "thread_url": row["thread_url"] or None,
            }
            for row in rows
        ]
    )


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


# ---------------------------------------------------------------------------
# Meme Stock Radar
# ---------------------------------------------------------------------------

_VALID_RADAR_WINDOWS = {"1h", "2h", "4h", "8h", "12h", "24h"}
_RADAR_WINDOW_SQL: dict[str, tuple[str, str]] = {
    "1h":  ("1 hour",   "2 hours"),
    "2h":  ("2 hours",  "4 hours"),
    "4h":  ("4 hours",  "8 hours"),
    "8h":  ("8 hours",  "16 hours"),
    "12h": ("12 hours", "24 hours"),
    "24h": ("24 hours", "48 hours"),
}


@app.get("/api/radar")
async def get_radar(window: str = "4h") -> JSONResponse:
    """Meme Stock Radar — detect mention velocity spikes and cross-subreddit spread.

    Compares mention counts in the recent window against the preceding equal
    window.  Tickers with a 3x+ velocity increase or 4+ subreddit spread are
    flagged.  Results are merged into a composite radar_score.
    """
    if window not in _RADAR_WINDOW_SQL:
        raise HTTPException(status_code=400, detail=f"Invalid window: {window}")

    recent_interval, full_interval = _RADAR_WINDOW_SQL[window]

    try:
        async with session_factory() as session:
            # Query 1: velocity spike
            velocity_result = await session.execute(text(f"""
                WITH recent AS (
                    SELECT ticker_symbol, COUNT(*) AS recent_count
                    FROM sentiment_signals
                    WHERE collected_at >= NOW() - INTERVAL '{recent_interval}'
                    GROUP BY ticker_symbol
                ),
                previous AS (
                    SELECT ticker_symbol, COUNT(*) AS prev_count
                    FROM sentiment_signals
                    WHERE collected_at >= NOW() - INTERVAL '{full_interval}'
                      AND collected_at < NOW() - INTERVAL '{recent_interval}'
                    GROUP BY ticker_symbol
                )
                SELECT
                    r.ticker_symbol,
                    r.recent_count,
                    COALESCE(p.prev_count, 0) AS prev_count,
                    CASE WHEN COALESCE(p.prev_count, 0) > 0
                         THEN ROUND(r.recent_count::numeric / p.prev_count, 1)
                         ELSE r.recent_count::numeric
                    END AS velocity_ratio
                FROM recent r
                LEFT JOIN previous p USING (ticker_symbol)
                WHERE r.recent_count >= 5
                ORDER BY velocity_ratio DESC
                LIMIT 30
            """))
            velocity_rows = {
                r["ticker_symbol"]: {
                    "recent_count": int(r["recent_count"]),
                    "prev_count": int(r["prev_count"]),
                    "velocity_ratio": float(r["velocity_ratio"]),
                }
                for r in velocity_result.mappings().all()
            }

            # Query 2: cross-subreddit spread
            spread_result = await session.execute(text(f"""
                SELECT
                    ticker_symbol,
                    COUNT(DISTINCT source_subreddit) AS sub_count,
                    COUNT(*) AS mention_count,
                    string_agg(DISTINCT source_subreddit, ' | '
                        ORDER BY source_subreddit) AS subreddits,
                    COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive,
                    COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative
                FROM sentiment_signals
                WHERE collected_at >= NOW() - INTERVAL '{recent_interval}'
                GROUP BY ticker_symbol
                HAVING COUNT(*) >= 5
                ORDER BY COUNT(DISTINCT source_subreddit) DESC, COUNT(*) DESC
                LIMIT 30
            """))
            spread_rows = {
                r["ticker_symbol"]: {
                    "sub_count": int(r["sub_count"]),
                    "mention_count": int(r["mention_count"]),
                    "subreddits": r["subreddits"] or "",
                    "positive": int(r["positive"]),
                    "negative": int(r["negative"]),
                }
                for r in spread_result.mappings().all()
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Merge and score
    all_tickers = set(velocity_rows) | set(spread_rows)
    radar_items = []
    for ticker in all_tickers:
        vel = velocity_rows.get(ticker, {})
        spr = spread_rows.get(ticker, {})
        velocity_ratio = vel.get("velocity_ratio", 1.0)
        sub_count = spr.get("sub_count", 1)
        mention_count = spr.get("mention_count", vel.get("recent_count", 0))
        positive = spr.get("positive", 0)
        negative = spr.get("negative", 0)

        # Only include if velocity >= 3x OR spread >= 4 subreddits
        if velocity_ratio < 3.0 and sub_count < 4:
            continue

        radar_score = min(100, velocity_ratio * 5 + sub_count * 10)
        bull_ratio = round(positive / (positive + negative), 3) if (positive + negative) > 0 else 0.5

        radar_items.append({
            "ticker": ticker,
            "mention_count": mention_count,
            "velocity_ratio": velocity_ratio,
            "prev_count": vel.get("prev_count", 0),
            "subreddit_spread": sub_count,
            "subreddits": spr.get("subreddits", ""),
            "radar_score": round(radar_score, 1),
            "bull_ratio": bull_ratio,
        })

    radar_items.sort(key=lambda x: x["radar_score"], reverse=True)
    return JSONResponse(radar_items[:20])


# ---------------------------------------------------------------------------
# Community Lens
# ---------------------------------------------------------------------------

_VALID_COMMUNITY_LOOKBACKS = {"1h", "4h", "12h", "24h", "7d", "30d"}
_COMMUNITY_LOOKBACK_SQL: dict[str, str] = {
    "1h": "1 hour", "4h": "4 hours", "12h": "12 hours",
    "24h": "24 hours", "7d": "7 days", "30d": "30 days",
}


@app.get("/api/tickers/{symbol}/community")
async def get_ticker_community(
    symbol: str,
    lookback: str = "24h",
) -> JSONResponse:
    """Per-subreddit sentiment breakdown for a single ticker.

    Shows how different Reddit communities feel about the same stock.
    """
    symbol = symbol.upper()
    if lookback not in _COMMUNITY_LOOKBACK_SQL:
        raise HTTPException(status_code=400, detail=f"Invalid lookback: {lookback}")

    interval_expr = _COMMUNITY_LOOKBACK_SQL[lookback]

    try:
        async with session_factory() as session:
            result = await session.execute(text(f"""
                SELECT
                    source_subreddit,
                    COUNT(*) AS mention_count,
                    COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive,
                    COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative,
                    SUM(sentiment_polarity * (upvote_weight + 1)) AS net_score,
                    ROUND(
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1)::numeric
                        / COUNT(*)::numeric, 3
                    ) AS bull_ratio
                FROM sentiment_signals
                WHERE ticker_symbol = :symbol
                  AND collected_at >= NOW() - INTERVAL '{interval_expr}'
                GROUP BY source_subreddit
                HAVING COUNT(*) >= 3
                ORDER BY COUNT(*) DESC
            """), {"symbol": symbol})
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    communities = [
        {
            "subreddit": r["source_subreddit"],
            "mention_count": int(r["mention_count"]),
            "positive": int(r["positive"]),
            "negative": int(r["negative"]),
            "net_score": int(r["net_score"] or 0),
            "bull_ratio": float(r["bull_ratio"]),
        }
        for r in rows
    ]

    bull_ratios = [c["bull_ratio"] for c in communities]
    if len(bull_ratios) >= 2:
        spread = round(max(bull_ratios) - min(bull_ratios), 3)
        all_bullish = all(br > 0.6 for br in bull_ratios)
        all_bearish = all(br < 0.4 for br in bull_ratios)
        consensus = all_bullish or all_bearish
    else:
        spread = 0.0
        consensus = True

    return JSONResponse({
        "symbol": symbol,
        "lookback": lookback,
        "communities": communities,
        "consensus": consensus,
        "spread": spread,
    })


# ---------------------------------------------------------------------------
# Divergence Alerts
# ---------------------------------------------------------------------------

_DIVERGENCE_MIN_MENTIONS = 10
_DIVERGENCE_PRICE_THRESHOLD = 0.05  # 5%
_DIVERGENCE_BULL_HIGH = 0.7
_DIVERGENCE_BULL_LOW = 0.3


async def _fetch_price_change(symbol: str) -> float | None:
    """Fetch recent price change % for a symbol from Yahoo Finance.

    Returns percentage change (e.g. -0.05 for -5%) or None on failure.
    Reuses the existing _http_client and _PRICE_CACHE.
    """
    assert _http_client is not None
    cache_key = f"{symbol}:5d:1d"

    cached = _PRICE_CACHE.get(cache_key)
    if cached is not None:
        fetched_at, payload = cached
        if time.monotonic() - fetched_at < _PRICE_CACHE_TTL:
            data = payload.get("data", [])
            if len(data) >= 2:
                prev_close = data[-2]["close"]
                last_close = data[-1]["close"]
                if prev_close and last_close:
                    return (last_close - prev_close) / prev_close
            return None

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        "?range=5d&interval=1d"
    )
    try:
        response = await _http_client.get(url)
        response.raise_for_status()
        raw = response.json()
        result0 = raw["chart"]["result"][0]
        closes = result0["indicators"]["quote"][0].get("close", [])
        valid_closes = [c for c in closes if c is not None]
        if len(valid_closes) >= 2:
            return (valid_closes[-1] - valid_closes[-2]) / valid_closes[-2]
    except Exception:
        pass
    return None


@app.get("/api/divergences")
async def get_divergences() -> JSONResponse:
    """Detect sentiment-price divergences with confidence scores.

    Flags tickers where Reddit sentiment strongly disagrees with recent
    price movement.  Confidence reflects data depth and sentiment strength.
    """
    try:
        async with session_factory() as session:
            result = await session.execute(text("""
                SELECT
                    ticker_symbol,
                    COUNT(*) AS mention_count,
                    COUNT(*) FILTER (WHERE sentiment_polarity = 1) AS positive,
                    COUNT(*) FILTER (WHERE sentiment_polarity = -1) AS negative,
                    ROUND(
                        COUNT(*) FILTER (WHERE sentiment_polarity = 1)::numeric
                        / COUNT(*)::numeric, 3
                    ) AS bull_ratio
                FROM sentiment_signals
                WHERE collected_at >= NOW() - INTERVAL '24 hours'
                GROUP BY ticker_symbol
                HAVING COUNT(*) >= :min_mentions
                ORDER BY COUNT(*) DESC
                LIMIT 50
            """), {"min_mentions": _DIVERGENCE_MIN_MENTIONS})
            rows = result.mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Fetch price changes for top 20 tickers concurrently
    tickers_to_check = rows[:20]
    price_changes = await asyncio.gather(
        *[_fetch_price_change(r["ticker_symbol"]) for r in tickers_to_check],
    )

    divergences = []
    for row, price_change in zip(tickers_to_check, price_changes):
        if price_change is None:
            continue

        bull_ratio = float(row["bull_ratio"])
        mention_count = int(row["mention_count"])

        # Check for divergence
        bullish_sent_bearish_price = (
            bull_ratio > _DIVERGENCE_BULL_HIGH
            and price_change < -_DIVERGENCE_PRICE_THRESHOLD
        )
        bearish_sent_bullish_price = (
            bull_ratio < _DIVERGENCE_BULL_LOW
            and price_change > _DIVERGENCE_PRICE_THRESHOLD
        )

        if not (bullish_sent_bearish_price or bearish_sent_bullish_price):
            continue

        # Confidence calculation
        # data_depth: 10 mentions = 20%, 50 = 60%, 100+ = 80%
        data_depth = min(80, max(20, (mention_count / 100) * 80))
        # sentiment_strength: how extreme the bull_ratio is (0-20% bonus)
        extremity = abs(bull_ratio - 0.5) * 2  # 0..1 scale
        sentiment_strength = extremity * 20
        confidence = min(95, round(data_depth + sentiment_strength))

        divergence_type = (
            "bullish_sentiment_bearish_price"
            if bullish_sent_bearish_price
            else "bearish_sentiment_bullish_price"
        )

        divergences.append({
            "ticker": row["ticker_symbol"],
            "bull_ratio": bull_ratio,
            "mention_count": mention_count,
            "positive": int(row["positive"]),
            "negative": int(row["negative"]),
            "price_change_pct": round(price_change * 100, 2),
            "divergence_type": divergence_type,
            "confidence": confidence,
        })

    divergences.sort(key=lambda x: x["confidence"], reverse=True)
    return JSONResponse(divergences)


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
                        string_agg(DISTINCT source_subreddit, ' | '
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

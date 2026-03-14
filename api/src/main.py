"""SSE Dashboard API — serves signal data and the frontend dashboard."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://sse:sse@postgres:5432/sse")

engine = create_async_engine(DATABASE_URL, echo=False)
session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

_DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="SSE Dashboard", lifespan=lifespan)


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
                LIMIT 30
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


@app.get("/api/runs")
async def get_runs() -> JSONResponse:
    try:
        async with session_factory() as session:
            result = await session.execute(text("""
                SELECT id, started_at, completed_at, status,
                       signals_stored, sources_attempted, sources_succeeded,
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
            "sources_attempted": int(r["sources_attempted"]),
            "sources_succeeded": int(r["sources_succeeded"]),
            "error_summary": r["error_summary"],
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

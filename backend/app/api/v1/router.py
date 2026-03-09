"""API v1 router — aggregates all sub-routers."""
from fastapi import APIRouter

from app.api.v1.endpoints import health, market, tickers, pricing, stream

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(market.router, prefix="/market", tags=["Market"])
# IMPORTANT: /tickers/stream must be registered BEFORE /tickers/{ticker}/stream
api_router.include_router(stream.router, prefix="/tickers", tags=["Streaming"])
api_router.include_router(tickers.router, prefix="/tickers", tags=["Tickers"])
api_router.include_router(pricing.router, prefix="/pricing", tags=["Pricing"])


@api_router.get("/", tags=["Meta"])
async def api_root() -> dict[str, str]:
    return {"version": "1.0"}

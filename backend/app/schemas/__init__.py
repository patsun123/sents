"""Pydantic v2 response schemas for all API endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Shared ──────────────────────────────────────────────────────────────────

StalenessLevel = Literal["fresh", "warning", "critical", "unavailable"]


# ── Market overview ──────────────────────────────────────────────────────────

class TickerSummary(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "ticker": "TSLA",
                "sentiment_price": 253.20,
                "real_price": 248.50,
                "sentiment_delta": 4.70,
                "staleness": "fresh",
                "last_updated": "2026-03-01T12:00:00Z",
                "mention_count_24h": 142,
            }
        },
    )

    ticker: str
    sentiment_price: Optional[float] = None
    real_price: Optional[float] = None
    sentiment_delta: float = 0.0
    staleness: StalenessLevel = "unavailable"
    last_updated: Optional[datetime] = None
    mention_count_24h: int = 0


class MarketOverviewResponse(BaseModel):
    tickers: list[TickerSummary]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Ticker history ────────────────────────────────────────────────────────────

class PricePoint(BaseModel):
    time: datetime
    sentiment_price: Optional[float] = None
    real_price: Optional[float] = None
    sentiment_delta: float = 0.0


class ScenarioDataPoint(BaseModel):
    time: datetime
    sentiment_price: float


class HistoryResponse(BaseModel):
    ticker: str
    interval: str
    series: list[PricePoint]
    scenario_series: Optional[dict[str, list[ScenarioDataPoint]]] = None
    shift_applied: int = 0
    shift_unit: str = "hours"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Pricing configurations ────────────────────────────────────────────────────

class PricingConfig(BaseModel):
    id: str
    slug: str
    name: str
    description: Optional[str] = None
    params: dict[str, float | str | int]

    model_config = ConfigDict(from_attributes=True)


class PricingConfigsResponse(BaseModel):
    configs: list[PricingConfig]


# ── SSE events ────────────────────────────────────────────────────────────────

class SSEPriceUpdate(BaseModel):
    ticker: str
    sentiment_price: Optional[float] = None
    real_price: Optional[float] = None
    sentiment_delta: float = 0.0
    staleness: StalenessLevel = "fresh"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Health ────────────────────────────────────────────────────────────────────

class TickerStaleness(BaseModel):
    ticker: str
    staleness: StalenessLevel
    minutes_since_update: Optional[float] = None


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    db_connected: bool
    redis_connected: bool
    tickers: list[TickerStaleness] = []
    last_scrape_time: Optional[datetime] = None
    last_sentiment_calc_time: Optional[datetime] = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "db_connected": True,
                "redis_connected": True,
                "tickers": [{"ticker": "TSLA", "staleness": "fresh", "minutes_since_update": 5.2}],
                "checked_at": "2026-03-01T12:00:00Z",
            }
        }
    )

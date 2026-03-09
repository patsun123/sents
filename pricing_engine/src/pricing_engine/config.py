"""Pricing engine configuration via pydantic-settings."""
from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class PricingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database (pricing user has SELECT on sentiment/tickers/params, INSERT on sentiment_prices)
    postgres_url_pricing: str = Field(
        default="postgresql://sse_pricing:changeme_pricing@localhost:5432/sse"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_max_connections: int = Field(default=10)

    # Market data provider
    market_data_provider: str = Field(default="yfinance")
    finnhub_api_key: str = Field(default="")

    # Intervals
    poll_interval_seconds: int = Field(default=300)
    market_hours_fetch_interval_seconds: int = Field(default=300)

    # Health check HTTP port
    health_port: int = Field(default=8082)

    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> PricingSettings:
    return PricingSettings()

"""Scraper service configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_url_scraper: str = Field(
        default="postgresql://sse_scraper:changeme_scraper@localhost:5432/sse"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Reddit credentials (optional — improves rate limits)
    reddit_client_id: str = Field(default="")
    reddit_client_secret: str = Field(default="")
    reddit_user_agent: str = Field(default="SSE-Scraper/1.0")

    # Proxy pool (comma-separated URLs, empty = no proxies)
    proxy_pool_urls: str = Field(default="")

    # Scraping intervals
    scrape_interval_seconds: int = Field(default=300)
    posts_per_ticker: int = Field(default=25)

    log_level: str = Field(default="INFO")

    @property
    def proxy_list(self) -> list[str]:
        return [p.strip() for p in self.proxy_pool_urls.split(",") if p.strip()]


@lru_cache
def get_settings() -> ScraperSettings:
    return ScraperSettings()

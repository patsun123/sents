"""Processor service configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProcessorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    postgres_url_processor: str = Field(
        default="postgresql://sse_processor:changeme_processor@localhost:5432/sse"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Which backends to run (comma-separated)
    sentiment_backends: str = Field(default="vader,textblob")

    # FinBERT model name (only used if 'finbert' in sentiment_backends)
    finbert_model: str = Field(default="ProsusAI/finbert")

    # Batch size for FinBERT inference
    finbert_batch_size: int = Field(default=16)

    # Aggregation window size in hours
    sentiment_window_hours: int = Field(default=1)

    log_level: str = Field(default="INFO")

    @property
    def backends_list(self) -> list[str]:
        return [b.strip() for b in self.sentiment_backends.split(",") if b.strip()]


@lru_cache
def get_settings() -> ProcessorSettings:
    return ProcessorSettings()

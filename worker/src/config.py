"""
SSE Worker configuration.

All settings come from environment variables.
No default should expose production credentials.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Worker configuration loaded from environment variables.

    All fields have safe defaults for local development.
    Production deployments must set DATABASE_URL, REDIS_URL, and
    REDDIT_* credentials explicitly.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://sse:sse@localhost:5432/sse"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Reddit credentials (PRAW fallback lane)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""

    # Classifier
    classifier_backend: str = "vader"
    vader_neutral_threshold: float = 0.05

    # Pipeline
    cycle_interval_minutes: int = 15
    alert_threshold: int = 3  # consecutive failures before alerting

    # Sentry
    sentry_dsn: str = ""

    # Logging
    log_level: str = "INFO"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

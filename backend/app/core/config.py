from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    postgres_url_api: str = Field(
        default="postgresql+asyncpg://sse_api:changeme_api@localhost:5432/sse",
        description="asyncpg DSN for sse_api user",
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_max_connections: int = Field(default=50)

    # CORS
    api_cors_origins: str = Field(default="http://localhost:5173")

    # Market data
    market_data_provider: str = Field(default="yfinance")
    finnhub_api_key: str = Field(default="")

    # App
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    api_version: str = Field(default="1.0.0")

    # Rate limiting
    rate_limit_per_minute: int = Field(default=60)

    @field_validator("market_data_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in ("yfinance", "finnhub"):
            raise ValueError(f"market_data_provider must be 'yfinance' or 'finnhub', got '{v}'")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def asyncpg_dsn(self) -> str:
        # asyncpg uses postgresql:// not postgresql+asyncpg://
        return self.postgres_url_api.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()

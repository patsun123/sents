"""Tests for pricing engine configuration."""
from pricing_engine.config import get_settings


def test_default_settings():
    """Verify default config values are sensible."""
    # Clear cached settings if any
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.poll_interval_seconds > 0
    assert settings.redis_max_connections > 0
    get_settings.cache_clear()

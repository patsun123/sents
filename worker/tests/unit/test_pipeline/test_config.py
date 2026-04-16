"""
Unit tests for config.py Settings and get_settings().
"""
from __future__ import annotations

import pytest

from src.config import Settings, get_settings


class TestSettings:
    """Tests for Settings model."""

    def test_default_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default DATABASE_URL points to localhost sentix database."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = Settings()
        assert "localhost" in settings.database_url
        assert "sentix" in settings.database_url

    def test_default_classifier_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default classifier is epic_rules."""
        monkeypatch.delenv("CLASSIFIER_BACKEND", raising=False)
        settings = Settings()
        assert settings.classifier_backend == "epic_rules"

    def test_default_cycle_interval_minutes(self) -> None:
        """Default cycle interval is 15 minutes."""
        settings = Settings()
        assert settings.cycle_interval_minutes == 15

    def test_default_alert_threshold(self) -> None:
        """Default alert threshold is 3."""
        settings = Settings()
        assert settings.alert_threshold == 3

    def test_default_sentry_dsn_empty(self) -> None:
        """Default Sentry DSN is empty (no alerting by default)."""
        settings = Settings()
        assert settings.sentry_dsn == ""

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable overrides Settings field."""
        monkeypatch.setenv("CYCLE_INTERVAL_MINUTES", "30")
        settings = Settings()
        assert settings.cycle_interval_minutes == 30

    def test_reddit_credentials_default_empty(self) -> None:
        """Reddit OAuth credentials default to empty strings."""
        settings = Settings()
        assert settings.reddit_client_id == ""
        assert settings.reddit_client_secret == ""
        assert settings.reddit_username == ""
        assert settings.reddit_password == ""


class TestGetSettings:
    """Tests for get_settings() caching."""

    def test_get_settings_returns_settings(self) -> None:
        """get_settings() returns a Settings instance."""
        import src.config as cfg  # noqa: PLC0415

        cfg._settings = None  # reset cache
        result = get_settings()
        assert isinstance(result, Settings)

    def test_get_settings_caches(self) -> None:
        """get_settings() returns the same instance on repeated calls."""
        import src.config as cfg  # noqa: PLC0415

        cfg._settings = None  # reset cache
        first = get_settings()
        second = get_settings()
        assert first is second
        cfg._settings = None  # cleanup

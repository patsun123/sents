"""Tests for GET /api/v1/pricing/configs endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


_SEED_CONFIGS = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "slug": "balanced",
        "name": "Balanced",
        "description": "Default balanced weights",
        "params": {"sensitivity": 1.0, "upvote_weight_multiplier": 1.0},
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "slug": "upvote-heavy",
        "name": "Upvote-Heavy",
        "description": "Karma-driven signal",
        "params": {"sensitivity": 1.0, "upvote_weight_multiplier": 2.0},
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "slug": "volume-heavy",
        "name": "Volume-Heavy",
        "description": "Mention-volume amplified",
        "params": {"sensitivity": 1.0, "volume_weight_multiplier": 2.0},
    },
]


@pytest.mark.asyncio
async def test_pricing_configs_returns_list(client: AsyncClient) -> None:
    """GET /api/v1/pricing/configs returns a list of configs."""
    with (
        patch("app.api.v1.endpoints.pricing.get_redis_client") as mock_rc,
        patch("app.api.v1.endpoints.pricing.cache_get_or_set") as mock_cache,
    ):
        mock_cache.return_value = {"configs": _SEED_CONFIGS}

        resp = await client.get("/api/v1/pricing/configs")

    assert resp.status_code == 200
    data = resp.json()
    assert "configs" in data
    assert len(data["configs"]) == 3


@pytest.mark.asyncio
async def test_pricing_configs_schema(client: AsyncClient) -> None:
    """Each config has required fields: id, slug, name, params."""
    with (
        patch("app.api.v1.endpoints.pricing.get_redis_client"),
        patch("app.api.v1.endpoints.pricing.cache_get_or_set") as mock_cache,
    ):
        mock_cache.return_value = {"configs": _SEED_CONFIGS}

        resp = await client.get("/api/v1/pricing/configs")

    configs = resp.json()["configs"]
    for cfg in configs:
        assert "id" in cfg
        assert "slug" in cfg
        assert "name" in cfg
        assert "params" in cfg
        assert isinstance(cfg["params"], dict)


@pytest.mark.asyncio
async def test_pricing_configs_slugs(client: AsyncClient) -> None:
    """The three seed config slugs are present."""
    with (
        patch("app.api.v1.endpoints.pricing.get_redis_client"),
        patch("app.api.v1.endpoints.pricing.cache_get_or_set") as mock_cache,
    ):
        mock_cache.return_value = {"configs": _SEED_CONFIGS}

        resp = await client.get("/api/v1/pricing/configs")

    slugs = {c["slug"] for c in resp.json()["configs"]}
    assert "balanced" in slugs
    assert "upvote-heavy" in slugs
    assert "volume-heavy" in slugs

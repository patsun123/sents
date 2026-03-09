"""Tests for GET /api/v1/health endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    """Health endpoint always returns 200 with a valid schema."""
    with (
        patch("app.api.v1.endpoints.health.get_redis_client") as mock_rc,
    ):
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        mock_rc.return_value = redis

        # Patch DB pool to return a working connection
        client.app.state.db_pool.acquire.return_value.__aenter__.return_value.fetchval = AsyncMock(
            return_value=1
        )
        client.app.state.db_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
            return_value=[]
        )

        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "db_connected" in data
    assert "redis_connected" in data
    assert "checked_at" in data


@pytest.mark.asyncio
async def test_health_unhealthy_when_db_down(client: AsyncClient) -> None:
    """Health returns 'unhealthy' when DB is unavailable."""
    with patch("app.api.v1.endpoints.health.get_redis_client") as mock_rc:
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        mock_rc.return_value = redis

        # DB raises an exception
        client.app.state.db_pool.acquire.return_value.__aenter__.return_value.fetchval = AsyncMock(
            side_effect=Exception("DB down")
        )

        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["db_connected"] is False


@pytest.mark.asyncio
async def test_health_schema_fields(client: AsyncClient) -> None:
    """Health response contains all required schema fields."""
    with patch("app.api.v1.endpoints.health.get_redis_client") as mock_rc:
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        mock_rc.return_value = redis

        client.app.state.db_pool.acquire.return_value.__aenter__.return_value.fetchval = AsyncMock(
            return_value=1
        )
        client.app.state.db_pool.acquire.return_value.__aenter__.return_value.fetch = AsyncMock(
            return_value=[]
        )

        resp = await client.get("/api/v1/health")

    required_fields = {"status", "db_connected", "redis_connected", "tickers", "checked_at"}
    assert required_fields.issubset(resp.json().keys())

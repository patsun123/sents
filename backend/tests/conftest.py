"""Pytest fixtures for backend API tests.

Integration tests (marked @pytest.mark.integration) require:
  RUN_INTEGRATION_TESTS=true
  A running TimescaleDB and Redis (use docker-compose up postgres redis).
"""
from __future__ import annotations

import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


# ── Skip integration tests unless opted in ──────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: marks tests that require live DB/Redis (deselect with -m 'not integration')"
    )


@pytest.fixture(autouse=True)
def skip_integration(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration"):
        if not os.getenv("RUN_INTEGRATION_TESTS"):
            pytest.skip("Set RUN_INTEGRATION_TESTS=true to run integration tests")


# ── Mock app state ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db_pool() -> MagicMock:
    """Mock asyncpg connection pool."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def mock_redis_pool() -> MagicMock:
    """Mock Redis connection pool."""
    pool = MagicMock()
    return pool


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """Mock Redis client."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.ping = AsyncMock(return_value=True)
    client.publish = AsyncMock(return_value=1)
    return client


@pytest.fixture
def mock_sse_manager() -> MagicMock:
    """Mock SSEManager."""
    manager = AsyncMock()
    manager.broadcast = AsyncMock()
    manager.broadcast_all = AsyncMock()
    return manager


# ── Test app factory ──────────────────────────────────────────────────────────

@pytest.fixture
def app(mock_db_pool: tuple, mock_redis_pool: MagicMock, mock_sse_manager: MagicMock) -> FastAPI:
    """FastAPI app with mocked state (no real DB or Redis connections)."""
    from app.main import create_app

    pool, _ = mock_db_pool
    test_app = create_app()
    test_app.state.db_pool = pool
    test_app.state.redis_pool = mock_redis_pool
    test_app.state.sse_manager = mock_sse_manager
    return test_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

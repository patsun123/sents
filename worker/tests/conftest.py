"""
Shared pytest fixtures for the SentiX worker test suite.

Database fixtures use mocked SQLAlchemy async sessions for unit tests.
Integration tests use a real PostgreSQL instance via the ``db_session``
fixture (requires ``DATABASE_URL`` env var or a local ``sse_test`` database).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Unit test fixtures: mocked AsyncSession
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    """Return a fully mocked :class:`AsyncSession` for unit tests.

    The session's ``execute`` method returns an :class:`~unittest.mock.AsyncMock`
    whose ``scalars().all()`` and ``scalar_one_or_none()`` are pre-configured.
    """
    session = AsyncMock(spec=AsyncSession)
    return session


# ---------------------------------------------------------------------------
# Integration test fixtures: real PostgreSQL
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture  # type: ignore[misc]
async def db_session() -> AsyncSession:  # type: ignore[return]
    """Create a fresh schema, yield a session, then drop the schema.

    Requires a running PostgreSQL instance.  The URL defaults to::

        postgresql+asyncpg://sse:sse@localhost:5432/sse_test

    Override by setting the ``DATABASE_URL`` environment variable.
    """
    # Defer import so unit tests don't require asyncpg to be installed.
    from sqlalchemy.ext.asyncio import (  # noqa: PLC0415
        create_async_engine,
    )
    from sqlalchemy.orm import sessionmaker  # noqa: PLC0415

    from src.storage.models import Base  # noqa: PLC0415

    url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://sse:sse@localhost:5432/sse_test"
    )
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(  # type: ignore[call-overload]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

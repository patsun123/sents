"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.db.pool import create_pool
from app.db.redis_client import create_redis_pool
from app.api.v1.router import api_router
from app.services.sse_manager import SSEManager
from app.subscriber import PricingEventSubscriber

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(
        "Starting SSE backend | provider=%s debug=%s",
        settings.market_data_provider,
        settings.debug,
    )

    # Database pool
    app.state.db_pool = await create_pool(settings)
    logger.info("Database pool created")

    # Redis pool
    app.state.redis_pool = create_redis_pool(settings)
    logger.info("Redis pool created")

    # SSE manager
    app.state.sse_manager = SSEManager()

    # Pricing event subscriber (background task)
    subscriber = PricingEventSubscriber(app.state.redis_pool, app.state.sse_manager)
    task = asyncio.create_task(subscriber.run(), name="pricing_subscriber")
    app.state.pricing_subscriber_task = task
    app.state.pricing_subscriber = subscriber

    def _on_task_done(t: asyncio.Task[None]) -> None:
        if not t.cancelled() and t.exception():
            logger.critical(
                "PricingEventSubscriber task exited unexpectedly: %s", t.exception()
            )

    task.add_done_callback(_on_task_done)

    yield

    # Shutdown
    logger.info("Shutting down SSE backend")
    subscriber.stop()
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    await app.state.sse_manager.close_all()
    await app.state.db_pool.close()
    await app.state.redis_pool.aclose()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Sentiment Stock Exchange API",
        description="Real-time sentiment-driven stock price simulation",
        version=settings.api_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    from app.core.limiter import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    app.include_router(api_router, prefix="/api/v1")

    return app


app = create_app()

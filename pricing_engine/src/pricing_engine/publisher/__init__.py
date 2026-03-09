"""Redis publisher for pricing run completion events."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sse_common.channels import CHANNEL_PRICING_DONE as _CHANNEL

logger = logging.getLogger(__name__)


async def publish_pricing_complete(
    redis_client: Any,
    tickers_priced: list[str],
) -> None:
    """Publish sse:pricing:run_complete to Redis after a successful pricing cycle.

    Resilient — logs a warning and returns if Redis is unavailable.
    Payload: {"run_id": "<uuid4>", "tickers_priced": [...], "timestamp": "<iso>"}
    """
    if redis_client is None:
        logger.warning("Redis unavailable — skipping pricing:run_complete publish")
        return

    payload = {
        "run_id": str(uuid.uuid4()),
        "tickers_priced": tickers_priced,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await redis_client.publish(_CHANNEL, json.dumps(payload))
        logger.info(
            "Published %s: %d tickers priced", _CHANNEL, len(tickers_priced)
        )
    except Exception:
        logger.warning(
            "Failed to publish %s — backend will not receive SSE trigger",
            _CHANNEL,
            exc_info=True,
        )

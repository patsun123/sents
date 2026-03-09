"""SSE connection manager — manages asyncio.Queue per ticker for connected clients."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class SSEManager:
    """Thread-safe asyncio.Queue management for SSE clients."""

    def __init__(self) -> None:
        # ticker -> set of queues for connected clients
        self._ticker_queues: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)
        # queues subscribed to all tickers
        self._global_queues: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def connect_ticker(self, ticker: str) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        async with self._lock:
            self._ticker_queues[ticker].add(q)
        logger.debug("SSE client connected for ticker=%s", ticker)
        return q

    async def connect_global(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._global_queues.add(q)
        logger.debug("SSE global client connected")
        return q

    async def disconnect_ticker(self, ticker: str, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._ticker_queues[ticker].discard(q)
        logger.debug("SSE client disconnected for ticker=%s", ticker)

    async def disconnect_global(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._global_queues.discard(q)

    async def broadcast(self, ticker: str, data: str) -> None:
        """Send SSE data to all clients subscribed to a specific ticker."""
        async with self._lock:
            queues = set(self._ticker_queues.get(ticker, set()))
        for q in queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for ticker=%s, dropping event", ticker)

    async def broadcast_all(self, data: str) -> None:
        """Send SSE data to all globally connected clients."""
        async with self._lock:
            queues = set(self._global_queues)
        for q in queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning("SSE global queue full, dropping event")

    async def close_all(self) -> None:
        async with self._lock:
            for queues in self._ticker_queues.values():
                for q in queues:
                    try:
                        q.put_nowait("CLOSE")
                    except asyncio.QueueFull:
                        pass
            for q in self._global_queues:
                try:
                    q.put_nowait("CLOSE")
                except asyncio.QueueFull:
                    pass
            self._ticker_queues.clear()
            self._global_queues.clear()

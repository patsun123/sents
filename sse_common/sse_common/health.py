"""Lightweight health endpoint for SSE services.

Uses only stdlib (http.server + threading) — no extra dependencies required.
Shared across scraper, processor, and pricing_engine to eliminate triplication.

Usage:
    from sse_common.health import HealthServer

    health = HealthServer("my_service", port=8001)
    health.start()
    # ... after a successful work cycle:
    health.record_success()
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class _HealthHandler(BaseHTTPRequestHandler):
    server_instance: HealthServer | None = None

    def do_GET(self) -> None:
        if self.path == "/health":
            hs = _HealthHandler.server_instance
            if hs is None:
                raise RuntimeError("HealthServer not initialized")
            data = {
                "service": hs.service_name,
                "status": hs.status,
                "uptime_seconds": int(time.time() - hs.start_time),
                "last_successful_run": hs.last_success,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # suppress access logs


class HealthServer:
    """Minimal HTTP health check server running on a daemon thread.

    Exposes GET /health returning JSON with service name, status, uptime,
    and last successful run timestamp.
    """

    def __init__(self, service_name: str, port: int) -> None:
        self.service_name = service_name
        self.port = port
        self.start_time = time.time()
        self.last_success: float | None = None
        self.status = "healthy"

    def start(self) -> None:
        _HealthHandler.server_instance = self
        server = HTTPServer(("0.0.0.0", self.port), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

    def record_success(self) -> None:
        self.last_success = time.time()

    def set_status(self, status: str) -> None:
        self.status = status

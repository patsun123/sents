"""Shared rate limiter instance for all API endpoints.

slowapi requires that the SAME Limiter instance used in @limiter.limit()
decorators is also attached to app.state.limiter.  This module provides
a single shared instance that both main.py and endpoint modules import.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

"""Auth-readiness stub — replace get_current_user implementation to add JWT/session auth.
No route changes needed when auth is added later."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request


@dataclass
class User:
    id: Optional[str] = None


async def get_current_user(request: Request) -> Optional[User]:  # noqa: ARG001
    # V1: auth-free. Return None for all requests.
    # To add auth: implement token validation here, raise HTTP 401 on failure.
    return None

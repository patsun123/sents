"""
RedditScraper Protocol and shared data types.

All scraper implementations must satisfy this Protocol.
No implementation details live here — only the contract.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawComment:
    """
    Minimal in-memory representation of a Reddit comment.

    PRIVACY GUARANTEE: This dataclass intentionally excludes
    username, comment_id, post_id, author, and subreddit fields.
    It must never be persisted or logged.
    """

    text: str  # Comment body — in-memory only, never persisted
    upvotes: int  # Upvote count at time of fetch (>= 0)
    created_utc: datetime  # UTC creation time


class ScraperError(Exception):
    """Base class for all scraper errors."""


class ScraperRateLimitError(ScraperError):
    """
    Raised when the source is rate-limiting requests.

    Caller should back off and retry after a delay.
    """

    def __init__(self, retry_after_seconds: int = 60) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limited. Retry after {retry_after_seconds}s.")


class ScraperUnavailableError(ScraperError):
    """
    Raised when a subreddit is private, banned, or unreachable.

    Caller should skip this source for the remainder of the cycle.
    """


@runtime_checkable
class RedditScraper(Protocol):
    """
    Interface for Reddit comment data sources.

    Each implementation handles its own auth, rate limiting,
    and pagination. The pipeline runner handles lane switching.
    """

    def fetch_comments(
        self,
        subreddit: str,
        since: datetime,
        limit: int = 500,
    ) -> AsyncIterator[RawComment]:
        """
        Fetch comments from a subreddit newer than ``since``.

        Implementations are async generators — call with ``async for``.

        Args:
            subreddit: Subreddit name without r/ prefix.
            since: Only yield comments with created_utc > since.
            limit: Maximum comments to yield.

        Yields:
            RawComment instances, newest first.

        Raises:
            ScraperRateLimitError: Source is rate-limiting.
            ScraperUnavailableError: Subreddit is unavailable.
            ScraperError: Any other unrecoverable error.
        """
        ...

    def is_available(self) -> bool:
        """Return True if this scraper lane is operational."""
        ...

"""
PRAWOAuthScraper — OAuth fallback Reddit scraping lane.

Uses PRAW for authenticated requests, which provide higher rate limits
(~60 req/min) than the unauthenticated ``.json`` endpoint (~1 req/sec).
Activated by the pipeline runner after repeated rate-limit failures on
the primary lane.

PRAW is synchronous; all blocking calls run via ``asyncio.to_thread()``
to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .base import (
    RawComment,
    ScraperError,
    ScraperRateLimitError,
    ScraperUnavailableError,
)

if TYPE_CHECKING:
    import praw as _praw


class PRAWOAuthScraper:
    """
    Fetches Reddit comments via PRAW OAuth.

    Credentials are read from environment variables at construction time.
    The PRAW client is initialised lazily on first use so that
    ``is_available()`` can be called without triggering a network check.

    Required env vars (when ``is_available()`` is True):
        REDDIT_CLIENT_ID: OAuth app client ID.
        REDDIT_CLIENT_SECRET: OAuth app client secret.
        REDDIT_USERNAME: Reddit account username.
        REDDIT_PASSWORD: Reddit account password.
    """

    def __init__(self) -> None:
        self._client_id = os.environ.get("REDDIT_CLIENT_ID", "")
        self._client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
        self._username = os.environ.get("REDDIT_USERNAME", "")
        self._password = os.environ.get("REDDIT_PASSWORD", "")
        self._reddit: _praw.Reddit | None = None

    def is_available(self) -> bool:
        """Return True if REDDIT_CLIENT_ID is set (credentials configured)."""
        return bool(self._client_id)

    def _get_reddit(self) -> _praw.Reddit:
        """Lazily initialise and return the PRAW Reddit client."""
        if self._reddit is None:
            import praw

            self._reddit = praw.Reddit(
                client_id=self._client_id,
                client_secret=self._client_secret,
                username=self._username,
                password=self._password,
                user_agent=f"SSE Worker/1.0 by /u/{self._username}",
            )
        return self._reddit

    async def fetch_comments(
        self,
        subreddit: str,
        since: datetime,
        limit: int = 500,
    ) -> AsyncIterator[RawComment]:
        """
        Fetch comments from a subreddit newer than ``since`` via PRAW.

        Runs PRAW calls in a thread pool to avoid blocking the event loop.
        Returns only comments created after ``since``; stops as soon as an
        older comment is encountered (submissions are ordered newest-first).

        Args:
            subreddit: Subreddit name without r/ prefix.
            since: Only yield comments with created_utc > since (UTC-aware).
            limit: Maximum number of comments to yield.

        Yields:
            RawComment instances in reverse-chronological order.

        Raises:
            ScraperRateLimitError: When PRAW reports rate limiting.
            ScraperUnavailableError: When subreddit is private or not found.
            ScraperError: For all other PRAW errors.
        """
        comments = await asyncio.to_thread(
            self._fetch_sync, subreddit, since, limit
        )
        for comment in comments:
            yield comment

    def _fetch_sync(
        self, subreddit: str, since: datetime, limit: int
    ) -> list[RawComment]:
        """
        Synchronous PRAW fetch — intended to run via ``asyncio.to_thread()``.

        Collects comments into a list so that all PRAW calls stay within
        a single thread boundary. Stops iterating as soon as a comment
        older than ``since`` is encountered.

        Args:
            subreddit: Subreddit name without r/ prefix.
            since: UTC-aware cutoff datetime.
            limit: Maximum number of comments to return.

        Returns:
            List of ``RawComment`` instances, newest first.

        Raises:
            ScraperRateLimitError: On PRAW rate-limit exception.
            ScraperUnavailableError: On forbidden or not-found subreddit.
            ScraperError: On any other PRAW exception.
        """
        import prawcore.exceptions

        results: list[RawComment] = []
        try:
            reddit = self._get_reddit()
            subreddit_obj = reddit.subreddit(subreddit)
            for submission in subreddit_obj.new(limit=limit):
                submission.comments.replace_more(limit=0)
                for comment in submission.comments.list():
                    created_utc = datetime.fromtimestamp(
                        comment.created_utc, tz=UTC
                    )
                    if created_utc <= since:
                        return results
                    results.append(
                        RawComment(
                            text=comment.body,
                            upvotes=max(0, comment.ups),
                            created_utc=created_utc,
                        )
                    )
                    if len(results) >= limit:
                        return results
        except prawcore.exceptions.Forbidden as exc:
            raise ScraperUnavailableError(
                "Subreddit is private or access is forbidden."
            ) from exc
        except prawcore.exceptions.NotFound as exc:
            raise ScraperUnavailableError("Subreddit not found.") from exc
        except prawcore.exceptions.TooManyRequests as exc:
            raise ScraperRateLimitError() from exc
        except Exception as exc:
            raise ScraperError(f"PRAW error: {exc}") from exc

        return results

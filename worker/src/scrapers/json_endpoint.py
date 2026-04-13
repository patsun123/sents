"""
JsonEndpointScraper — primary Reddit scraping lane.

Fetches comments via Reddit's public ``.json`` endpoint.
No OAuth credentials required. Applies exponential backoff on 429 responses
and rotates User-Agent strings to reduce rate-limit pressure.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from .base import (
    RawComment,
    ScraperError,
    ScraperRateLimitError,
    ScraperUnavailableError,
)

logger = logging.getLogger(__name__)

_MAX_BACKOFF_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 60
_PAGE_SIZE = 100


class JsonEndpointScraper:
    """
    Fetches Reddit comments via the public ``.json`` endpoint.

    Rotates User-Agent strings across requests and applies exponential
    backoff on 429 responses. Falls back to ``ScraperRateLimitError``
    after ``_MAX_BACKOFF_ATTEMPTS`` consecutive failures so the pipeline
    runner can switch to the OAuth lane.

    Args:
        user_agents: Pool of User-Agent strings to rotate through.
            Must contain at least one entry.
        request_delay_seconds: Delay (in seconds) between paginated requests
            to avoid hammering Reddit unnecessarily.
    """

    def __init__(
        self,
        user_agents: list[str],
        request_delay_seconds: float = 1.0,
    ) -> None:
        if not user_agents:
            raise ValueError("user_agents must contain at least one entry.")
        self._user_agents = user_agents
        self._request_delay = request_delay_seconds
        self._backoff_attempts = 0

    def is_available(self) -> bool:
        """Always available — no credentials required."""
        return True

    async def fetch_comments(
        self,
        subreddit: str,
        since: datetime,
        limit: int = 500,
    ) -> AsyncIterator[RawComment]:
        """
        Fetch comments/posts from a subreddit newer than ``since``.

        Paginates through Reddit's ``/r/{subreddit}/new/.json`` until
        the ``since`` cutoff is reached or ``limit`` comments are yielded.

        Args:
            subreddit: Subreddit name without r/ prefix.
            since: Only yield items with created_utc > since (UTC-aware).
            limit: Maximum number of comments to yield.

        Yields:
            RawComment instances, newest first.

        Raises:
            ScraperRateLimitError: After ``_MAX_BACKOFF_ATTEMPTS`` consecutive
                429 responses.
            ScraperUnavailableError: On 403 or 404 response.
            ScraperError: On persistent 5xx server error.
        """
        count = 0
        after: str | None = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while count < limit:
                url = (
                    f"https://www.reddit.com/r/{subreddit}/new/.json"
                    f"?limit={_PAGE_SIZE}"
                )
                if after:
                    url += f"&after={after}"

                response = await self._get_with_backoff(client, url)
                self._backoff_attempts = 0  # reset on success

                payload = response.json()
                listing = payload.get("data", {})
                children = listing.get("children", [])
                after = listing.get("after")

                for child in children:
                    if count >= limit:
                        return

                    item = child.get("data", {})
                    # Accept posts (t3) via selftext and comments (t1) via body.
                    body: str = item.get("body") or item.get("selftext") or ""
                    if not body.strip():
                        continue

                    created_utc = datetime.fromtimestamp(
                        float(item["created_utc"]), tz=UTC
                    )
                    if created_utc <= since:
                        # All remaining items are older; stop paginating.
                        return

                    item_kind = child.get("kind", "t1")
                    content_type = "post" if item_kind == "t3" else "comment"

                    yield RawComment(
                        text=body,
                        upvotes=max(0, int(item.get("ups", 0))),
                        created_utc=created_utc,
                        content_type=content_type,
                    )
                    count += 1

                if not after:
                    break

                await asyncio.sleep(self._request_delay)

    async def _get_with_backoff(
        self, client: httpx.AsyncClient, url: str
    ) -> httpx.Response:
        """
        Perform a GET request with exponential backoff on 429 responses.

        Args:
            client: Active ``httpx.AsyncClient`` to use for the request.
            url: Full URL to fetch.

        Returns:
            Successful ``httpx.Response`` (status 200).

        Raises:
            ScraperRateLimitError: After ``_MAX_BACKOFF_ATTEMPTS`` consecutive
                429 responses.
            ScraperUnavailableError: On 403 or 404.
            ScraperError: On persistent 5xx or unexpected status code.
        """
        retried_5xx = False

        while True:
            headers = {"User-Agent": random.choice(self._user_agents)}  # noqa: S311  # nosec B311
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                self._backoff_attempts += 1
                if self._backoff_attempts >= _MAX_BACKOFF_ATTEMPTS:
                    raise ScraperRateLimitError(retry_after_seconds=_MAX_BACKOFF_SECONDS)

                retry_after_header = response.headers.get("Retry-After", "")
                if retry_after_header.isdigit():
                    delay = int(retry_after_header)
                else:
                    delay = min(2**self._backoff_attempts, _MAX_BACKOFF_SECONDS)

                logger.warning(
                    "Rate limited by Reddit (.json). Backing off %ds (attempt %d/%d).",
                    delay,
                    self._backoff_attempts,
                    _MAX_BACKOFF_ATTEMPTS,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code in (403, 404):
                raise ScraperUnavailableError(
                    f"Subreddit unavailable (HTTP {response.status_code})."
                )

            if response.status_code >= 500:
                if retried_5xx:
                    raise ScraperError(
                        f"Reddit server error after retry (HTTP {response.status_code})."
                    )
                retried_5xx = True
                await asyncio.sleep(self._request_delay)
                continue

            raise ScraperError(
                f"Unexpected HTTP {response.status_code} from Reddit."
            )

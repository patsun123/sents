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
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from .base import (
    RawComment,
    ScraperError,
    ScraperRateLimitError,
    ScraperUnavailableError,
)

logger = logging.getLogger(__name__)

RedditObject = dict[str, Any]

_MAX_BACKOFF_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 60
_PAGE_SIZE = 100
_THREAD_PAGE_SIZE = 500
_ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_ACCEPT_LANGUAGE_OPTIONS = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.8",
    "en-GB,en;q=0.9",
]


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
                    item_kind = child.get("kind", "t1")
                    if item_kind == "t3":
                        title = (item.get("title") or "").strip()
                        selftext = (item.get("selftext") or "").strip()
                        body = " | ".join(part for part in (title, selftext) if part)
                    else:
                        body = item.get("body") or ""
                    if not body.strip():
                        continue

                    created_utc = datetime.fromtimestamp(
                        float(item["created_utc"]), tz=UTC
                    )
                    if created_utc <= since:
                        # All remaining items are older; stop paginating.
                        return

                    content_type = "post" if item_kind == "t3" else "comment"
                    permalink = (item.get("permalink") or "").strip()
                    thread_url = f"https://www.reddit.com{permalink}" if permalink else ""

                    yield RawComment(
                        text=body,
                        upvotes=max(0, int(item.get("ups", 0))),
                        reply_count=self._reply_count_for_item(item, item_kind),
                        created_utc=created_utc,
                        content_type=content_type,
                        source_thread_url=thread_url,
                    )
                    count += 1

                    if item_kind == "t3" and count < limit:
                        if permalink:
                            try:
                                async for thread_comment in self._fetch_thread_comments(
                                    client=client,
                                    permalink=permalink,
                                    since=since,
                                    remaining=limit - count,
                                ):
                                    yield thread_comment
                                    count += 1
                                    if count >= limit:
                                        return
                            except ScraperUnavailableError:
                                logger.warning(
                                    "thread_fetch_unavailable permalink=%s",
                                    permalink,
                                )
                                continue

                if not after:
                    break

                await asyncio.sleep(self._request_delay)

    async def _fetch_thread_comments(
        self,
        client: httpx.AsyncClient,
        permalink: str,
        since: datetime,
        remaining: int,
    ) -> AsyncIterator[RawComment]:
        """Fetch nested comments for a post via thread ``.json``."""
        if remaining <= 0:
            return

        thread_url = (
            f"https://www.reddit.com{permalink}.json"
            f"?limit={_THREAD_PAGE_SIZE}&sort=new"
        )
        response = await self._get_with_backoff(client, thread_url)
        canonical_thread_url = f"https://www.reddit.com{permalink}"
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2:
            return

        comments_listing = payload[1].get("data", {}) if isinstance(payload[1], dict) else {}
        yielded = 0
        for raw_comment in self._iter_comment_tree(
            comments_listing.get("children", []), since, canonical_thread_url
        ):
            yield raw_comment
            yielded += 1
            if yielded >= remaining:
                return

        await asyncio.sleep(self._request_delay)

    @classmethod
    def _iter_comment_tree(
        cls,
        children: list[RedditObject],
        since: datetime,
        thread_url: str,
    ) -> Iterator[RawComment]:
        """Yield comments from a Reddit thread tree newer than ``since``."""
        for child in children:
            if child.get("kind") != "t1":
                continue

            item = cast(RedditObject, child.get("data", {}))
            body = (item.get("body") or "").strip()
            if not body:
                continue

            created_utc = datetime.fromtimestamp(float(item["created_utc"]), tz=UTC)
            if created_utc <= since:
                continue

            yield RawComment(
                text=body,
                upvotes=max(0, int(item.get("ups", 0))),
                reply_count=cls._reply_count_for_item(item, "t1"),
                created_utc=created_utc,
                content_type="comment",
                source_thread_url=thread_url,
            )

            replies = item.get("replies")
            if isinstance(replies, dict):
                replies_data = cast(RedditObject, replies.get("data", {}))
                reply_children = cast(list[RedditObject], replies_data.get("children", []))
                yield from cls._iter_comment_tree(reply_children, since, thread_url)

    @classmethod
    def _reply_count_for_item(
        cls,
        item: RedditObject,
        item_kind: str,
    ) -> int:
        """Return a numeric engagement proxy without retaining thread IDs."""
        if item_kind == "t3":
            num_comments = item.get("num_comments", 0)
            if isinstance(num_comments, bool):
                return 0
            if isinstance(num_comments, int | float | str):
                return max(0, int(num_comments))
            return 0

        replies = item.get("replies")
        if not isinstance(replies, dict):
            return 0

        replies_data = cast(RedditObject, replies.get("data", {}))
        reply_children = cast(list[RedditObject], replies_data.get("children", []))
        return cls._count_descendant_comments(reply_children)

    @classmethod
    def _count_descendant_comments(cls, children: list[RedditObject]) -> int:
        """Count all descendant comments under a Reddit comment."""
        total = 0
        for child in children:
            if child.get("kind") != "t1":
                continue

            total += 1
            item = cast(RedditObject, child.get("data", {}))
            replies = item.get("replies")
            if isinstance(replies, dict):
                replies_data = cast(RedditObject, replies.get("data", {}))
                reply_children = cast(list[RedditObject], replies_data.get("children", []))
                total += cls._count_descendant_comments(reply_children)
        return total

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
            headers = self._build_headers(url)
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

    def _build_headers(self, url: str) -> dict[str, str]:
        """Return a browser-like header set for a Reddit request."""
        return {
            "User-Agent": random.choice(self._user_agents),  # noqa: S311  # nosec B311
            "Accept": _ACCEPT_HEADER,
            "Accept-Language": random.choice(_ACCEPT_LANGUAGE_OPTIONS),  # noqa: S311  # nosec B311
            "Referer": "https://www.reddit.com/",
            "DNT": "1",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if "/comments/" in url else "none",
            "Sec-Fetch-User": "?1",
        }

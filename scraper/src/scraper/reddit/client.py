"""Reddit scraping client using httpx.

Scrapes /r/wallstreetbets, /r/stocks, /r/investing for ticker mentions.
Fetches /new.json once per subreddit and matches all tickers locally —
fixed number of requests regardless of how many tickers are tracked.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Subreddits to monitor
SUBREDDITS = ["wallstreetbets", "stocks", "investing", "StockMarket", "options"]

# Reddit JSON endpoint
_BASE_URL = "https://www.reddit.com"
_HEADERS = {
    "User-Agent": "SSE-Scraper/1.0 (research project)",
    "Accept": "application/json",
}

# Default bot usernames to filter
_DEFAULT_BOT_USERNAMES: set[str] = {"automoderator", "snapshillbot", "remindmebot"}
_DEFAULT_MIN_CONTENT_LENGTH = 20


@dataclass
class RedditPost:
    reddit_id: str
    ticker_mentioned: str
    title: str
    content: str
    author: str
    score: int
    upvote_ratio: float
    num_comments: int
    subreddit: str
    post_url: str
    created_utc: datetime
    content_fingerprint: str


@dataclass
class RedditComment:
    """A single top-level Reddit comment."""
    reddit_id: str              # comment's Reddit ID (e.g., "t1_abc123")
    parent_post_id: str         # parent post's reddit_id
    ticker_mentioned: str
    author: str
    content: str                # comment body text
    score: int
    upvote_ratio: float | None  # comments don't have this; set to None
    subreddit: str
    post_url: str               # parent post URL
    created_utc: datetime
    content_fingerprint: str    # SHA-256 of normalized content


def _fingerprint(reddit_id: str, ticker: str, content: str) -> str:
    """SHA-256 fingerprint for deduplication."""
    raw = f"{reddit_id}:{ticker}:{content[:500]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _mentions_ticker(text: str, ticker: str) -> bool:
    """Check if text mentions a ticker (word-boundary match, case-insensitive)."""
    pattern = rf"\b{re.escape(ticker)}\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _parse_post(post_data: dict, ticker: str) -> Optional[RedditPost]:
    """Parse a Reddit post dict into a RedditPost. Returns None if invalid."""
    try:
        d = post_data.get("data", {})
        reddit_id = d.get("id", "")
        if not reddit_id:
            return None
        title = d.get("title", "") or ""
        selftext = d.get("selftext", "") or ""
        content = f"{title}\n{selftext}".strip()

        created = d.get("created_utc", 0)
        return RedditPost(
            reddit_id=reddit_id,
            ticker_mentioned=ticker,
            title=title[:500],
            content=selftext[:2000],
            author=str(d.get("author", "[deleted]"))[:100],
            score=int(d.get("score", 0)),
            upvote_ratio=float(d.get("upvote_ratio", 0.5)),
            num_comments=int(d.get("num_comments", 0)),
            subreddit=str(d.get("subreddit", ""))[:50],
            post_url=f"https://reddit.com{d.get('permalink', '')}",
            created_utc=datetime.fromtimestamp(created, tz=timezone.utc),
            content_fingerprint=_fingerprint(reddit_id, ticker, content),
        )
    except (KeyError, ValueError, TypeError):
        logger.debug("Failed to parse post: %s", post_data.get("data", {}).get("id"))
        return None


class RedditClient:
    """Async Reddit scraper using httpx."""

    def __init__(
        self,
        user_agent: str = "SSE-Scraper/1.0",
        proxies: Optional[list[str]] = None,
        bot_usernames: Optional[set[str]] = None,
        min_content_length: int = _DEFAULT_MIN_CONTENT_LENGTH,
    ) -> None:
        self._user_agent = user_agent
        self._proxies = proxies or []
        self._proxy_idx = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._bot_usernames = bot_usernames or _DEFAULT_BOT_USERNAMES
        self._min_content_length = min_content_length

    def _next_proxy(self) -> Optional[str]:
        if not self._proxies:
            return None
        proxy = self._proxies[self._proxy_idx % len(self._proxies)]
        self._proxy_idx += 1
        return proxy

    def _should_skip(self, item: dict) -> bool:
        """Return True if the post/comment should be filtered out."""
        author = item.get("author") or ""
        # Deleted/removed posts
        if author in ("[deleted]", "[removed]"):
            return True
        selftext = item.get("selftext") or item.get("body") or ""
        if selftext in ("[deleted]", "[removed]"):
            return True
        # Bot accounts (case-insensitive)
        if author.lower() in self._bot_usernames:
            return True
        # Minimum content length
        text = ((item.get("title", "") or "") + " " + selftext).strip()
        if len(text) < self._min_content_length:
            return True
        return False

    async def __aenter__(self) -> "RedditClient":
        proxy = self._next_proxy()
        self._client = httpx.AsyncClient(
            headers={**_HEADERS, "User-Agent": self._user_agent},
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            proxy=proxy,
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    async def fetch_subreddit_new(self, subreddit: str, limit: int = 25) -> list[dict]:
        """Fetch the newest posts from a subreddit as raw post dicts."""
        if self._client is None:
            raise RuntimeError("RedditClient not initialized; use async context manager")
        url = f"{_BASE_URL}/r/{subreddit}/new.json"
        try:
            resp = await self._client.get(url, params={"limit": min(limit, 100)})
            resp.raise_for_status()
            return resp.json().get("data", {}).get("children", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limited on /r/%s — skipping", subreddit)
            else:
                logger.warning("HTTP %d on /r/%s", e.response.status_code, subreddit)
            return []
        except Exception:
            logger.warning("Failed to fetch /r/%s/new", subreddit, exc_info=True)
            return []

    async def fetch_new_posts(
        self, tickers: list[str], posts_per_subreddit: int = 25
    ) -> list[RedditPost]:
        """Fetch recent posts for all tickers.

        Fetches /new.json once per subreddit and matches all tickers locally.
        Number of requests = len(SUBREDDITS), regardless of ticker count.
        """
        results: list[RedditPost] = []
        seen: set[tuple[str, str]] = set()  # (reddit_id, ticker)

        for subreddit in SUBREDDITS:
            children = await self.fetch_subreddit_new(subreddit, limit=posts_per_subreddit)
            for child in children:
                d = child.get("data", {})
                # Quality filter before processing
                if self._should_skip(d):
                    continue
                text = (d.get("title", "") or "") + " " + (d.get("selftext", "") or "")
                for ticker in tickers:
                    if not _mentions_ticker(text, ticker):
                        continue
                    reddit_id = d.get("id", "")
                    if (reddit_id, ticker) in seen:
                        continue
                    seen.add((reddit_id, ticker))
                    post = _parse_post(child, ticker)
                    if post:
                        results.append(post)

        logger.info(
            "Scraped %d subreddits, found %d posts for %d tickers",
            len(SUBREDDITS), len(results), len(tickers),
        )
        return results

    async def fetch_comments(
        self, post_reddit_id: str, limit: int = 50
    ) -> list[RedditComment]:
        """Fetch top-level comments for a Reddit post.

        Uses GET https://www.reddit.com/comments/{post_reddit_id}.json
        Returns top-level comments only (no recursive threading in V1).
        """
        if self._client is None:
            raise RuntimeError("RedditClient not initialized; use async context manager")

        url = f"{_BASE_URL}/comments/{post_reddit_id}.json"
        try:
            resp = await self._client.get(url, params={"limit": limit})
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limited fetching comments for %s", post_reddit_id)
            else:
                logger.warning(
                    "HTTP %d fetching comments for %s", e.response.status_code, post_reddit_id
                )
            return []
        except Exception:
            logger.warning("Failed to fetch comments for %s", post_reddit_id, exc_info=True)
            return []

        # Reddit returns [post_listing, comment_listing]; comments are in index 1
        if not isinstance(data, list) or len(data) < 2:
            return []

        # Extract parent post info from the first listing
        post_children = data[0].get("data", {}).get("children", [])
        parent_data = post_children[0].get("data", {}) if post_children else {}
        subreddit = str(parent_data.get("subreddit", ""))
        post_url = f"https://reddit.com{parent_data.get('permalink', '')}"

        comment_children = data[1].get("data", {}).get("children", [])
        comments: list[RedditComment] = []

        for child in comment_children:
            if child.get("kind") != "t1":
                continue
            cd = child.get("data", {})
            # Apply the same quality filter
            if self._should_skip(cd):
                continue

            comment_id = cd.get("id", "")
            if not comment_id:
                continue

            body = (cd.get("body") or "")[:2000]
            author = str(cd.get("author", "[deleted]"))[:100]
            score = int(cd.get("score", 0))
            created = cd.get("created_utc", 0)
            content_fp = _fingerprint(comment_id, "", body)

            comments.append(
                RedditComment(
                    reddit_id=f"t1_{comment_id}",
                    parent_post_id=post_reddit_id,
                    ticker_mentioned="",  # will be set per-ticker by caller
                    author=author,
                    content=body,
                    score=score,
                    upvote_ratio=None,
                    subreddit=subreddit[:50],
                    post_url=post_url,
                    created_utc=datetime.fromtimestamp(created, tz=timezone.utc),
                    content_fingerprint=content_fp,
                )
            )

        logger.debug(
            "Fetched %d comments for post %s", len(comments), post_reddit_id
        )
        return comments

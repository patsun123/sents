# Contract: RedditScraper Interface

**Type**: Python Protocol (structural subtyping)
**File**: `worker/src/scrapers/base.py`
**Date**: 2026-03-09

---

## Purpose

Defines the interface that all Reddit data source implementations must satisfy. The pipeline runner calls `fetch_comments()` without knowing whether it's talking to the `.json` endpoint or PRAW OAuth. Lane selection (primary vs fallback) is handled by the pipeline runner, not by implementations.

---

## Protocol Definition

```python
from typing import Protocol, AsyncIterator
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawComment:
    """
    Minimal in-memory representation of a Reddit comment.
    Never persisted. Discarded after sentiment classification.
    """
    text: str              # Comment body (in-memory only)
    upvotes: int           # Upvote count at time of fetch
    created_utc: datetime  # Post creation time (UTC)
    # NOTE: No username, comment ID, post ID, or author data


@runtime_checkable
class RedditScraper(Protocol):
    """
    Interface for Reddit comment data sources.

    Implementations handle their own authentication, rate limiting,
    and pagination. The pipeline runner handles lane switching.
    """

    async def fetch_comments(
        self,
        subreddit: str,
        since: datetime,
        limit: int = 500,
    ) -> AsyncIterator[RawComment]:
        """
        Fetch comments from a subreddit newer than `since`.

        Args:
            subreddit: Subreddit name without r/ prefix (e.g., "wallstreetbets")
            since: Only return comments created after this UTC timestamp
            limit: Maximum comments to return per call

        Yields:
            RawComment instances in reverse-chronological order

        Raises:
            ScraperRateLimitError: When rate-limited (caller should back off)
            ScraperUnavailableError: When subreddit is private/banned/unreachable
            ScraperError: For all other unrecoverable errors
        """
        ...

    def is_available(self) -> bool:
        """
        Returns True if this scraper lane is currently operational.
        Used by the pipeline runner to determine lane selection.
        """
        ...
```

---

## Implementations

| Lane | Class | Trigger |
|------|-------|---------|
| Primary | `JsonEndpointScraper` | Default; always tried first |
| Fallback | `PRAWOAuthScraper` | Activated after 3 consecutive `ScraperRateLimitError` from primary in one cycle |

---

## Lane Switching Logic (Pipeline Runner Responsibility)

```
For each subreddit in active sources:
  Try primary scraper
  If ScraperRateLimitError (3rd consecutive):
    Switch to fallback scraper for remainder of cycle
    Log lane switch event
  If ScraperUnavailableError:
    Mark subreddit as unavailable for this cycle
    Log and continue to next subreddit
    (Do NOT switch lanes — this is a source problem, not a lane problem)
  If ScraperError:
    Log, mark subreddit failed, continue
```

---

## Behaviour Rules

- `RawComment` must never include Reddit usernames, user IDs, comment IDs, or post IDs
- `fetch_comments()` must respect the `since` timestamp — no duplicate comments from previous cycles
- Implementations must handle their own User-Agent rotation (`.json` scraper) and credential management (PRAW)
- All errors must be typed (`ScraperRateLimitError`, `ScraperUnavailableError`, `ScraperError`) — no bare exceptions
- `fetch_comments()` is an async generator — it yields as comments are fetched, not after all are collected

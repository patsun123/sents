"""Unit tests for PRAWOAuthScraper.

PRAW is mocked via unittest.mock — no real Reddit OAuth calls are made.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.scrapers.base import (
    RawComment,
    ScraperError,
    ScraperRateLimitError,
    ScraperUnavailableError,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RECENT_TS = 1_770_000_000.0  # ~Mar 2026
_PAST_SINCE = datetime(2025, 1, 1, tzinfo=UTC)
_OLD_TS = 1_580_000_000.0  # Jan 2020

_CREDS = {
    "REDDIT_CLIENT_ID": "test_client_id",
    "REDDIT_CLIENT_SECRET": "test_client_secret",
    "REDDIT_USERNAME": "test_user",
    "REDDIT_PASSWORD": "test_pass",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_comment(body: str, ups: int, created_utc: float) -> MagicMock:
    comment = MagicMock()
    comment.body = body
    comment.ups = ups
    comment.created_utc = created_utc
    return comment


def _make_mock_submission(comments: list[Any]) -> MagicMock:
    submission = MagicMock()
    submission.comments.replace_more.return_value = []
    submission.comments.list.return_value = comments
    return submission


def _make_scraper(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Create a PRAWOAuthScraper with env vars set and praw.Reddit mocked."""
    for key, val in _CREDS.items():
        monkeypatch.setenv(key, val)
    from src.scrapers.praw_oauth import PRAWOAuthScraper

    return PRAWOAuthScraper()


# ---------------------------------------------------------------------------
# is_available() tests
# ---------------------------------------------------------------------------


def test_is_available_true_when_client_id_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_available() returns True when REDDIT_CLIENT_ID is set."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "some_id")
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    from src.scrapers.praw_oauth import PRAWOAuthScraper

    scraper = PRAWOAuthScraper()
    assert scraper.is_available() is True


def test_is_available_false_when_client_id_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_available() returns False when REDDIT_CLIENT_ID is not set."""
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    from src.scrapers.praw_oauth import PRAWOAuthScraper

    scraper = PRAWOAuthScraper()
    assert scraper.is_available() is False


def test_factory_returns_none_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_fallback_scraper() returns None when REDDIT_CLIENT_ID is absent."""
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    from src.scrapers import get_fallback_scraper

    assert get_fallback_scraper() is None


# ---------------------------------------------------------------------------
# fetch_comments() — successful path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_rawcomments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful fetch returns correctly constructed RawComment objects."""
    mock_comment = _make_mock_comment("AAPL to the moon!", 30, _RECENT_TS)
    submission = _make_mock_submission([mock_comment])

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.return_value = [submission]

        scraper = _make_scraper(monkeypatch)
        comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert isinstance(comments[0], RawComment)
    assert comments[0].text == "AAPL to the moon!"
    assert comments[0].upvotes == 30
    assert comments[0].created_utc.tzinfo == UTC
    assert comments[0].content_type == "comment"


@pytest.mark.asyncio
async def test_fetch_excludes_old_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comments older than ``since`` are excluded."""
    new_comment = _make_mock_comment("New comment", 5, _RECENT_TS)
    old_comment = _make_mock_comment("Old comment", 1, _OLD_TS)
    submission = _make_mock_submission([new_comment, old_comment])

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.return_value = [submission]

        scraper = _make_scraper(monkeypatch)
        comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].text == "New comment"


@pytest.mark.asyncio
async def test_negative_upvotes_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative upvote counts are clamped to 0."""
    mock_comment = _make_mock_comment("Downvoted", -10, _RECENT_TS)
    submission = _make_mock_submission([mock_comment])

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.return_value = [submission]

        scraper = _make_scraper(monkeypatch)
        comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert comments[0].upvotes == 0


@pytest.mark.asyncio
async def test_rawcomment_has_no_pii_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """RawComment objects must not expose username, comment_id, or post_id."""
    mock_comment = _make_mock_comment("Some text", 5, _RECENT_TS)
    submission = _make_mock_submission([mock_comment])

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.return_value = [submission]

        scraper = _make_scraper(monkeypatch)
        comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    comment = comments[0]
    assert not hasattr(comment, "username")
    assert not hasattr(comment, "author")
    assert not hasattr(comment, "comment_id")
    assert not hasattr(comment, "post_id")
    assert not hasattr(comment, "subreddit")


# ---------------------------------------------------------------------------
# Error mapping tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forbidden_subreddit_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """prawcore Forbidden maps to ScraperUnavailableError."""
    import prawcore.exceptions  # type: ignore[import-untyped]

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.side_effect = prawcore.exceptions.Forbidden(
            MagicMock()
        )

        scraper = _make_scraper(monkeypatch)
        with pytest.raises(ScraperUnavailableError):
            _ = [c async for c in scraper.fetch_comments("private_sub", _PAST_SINCE)]


@pytest.mark.asyncio
async def test_not_found_subreddit_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """prawcore NotFound maps to ScraperUnavailableError."""
    import prawcore.exceptions  # type: ignore[import-untyped]

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.side_effect = prawcore.exceptions.NotFound(
            MagicMock()
        )

        scraper = _make_scraper(monkeypatch)
        with pytest.raises(ScraperUnavailableError):
            _ = [c async for c in scraper.fetch_comments("no_such_sub", _PAST_SINCE)]


@pytest.mark.asyncio
async def test_too_many_requests_raises_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """prawcore TooManyRequests maps to ScraperRateLimitError."""
    import prawcore.exceptions  # type: ignore[import-untyped]

    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.side_effect = prawcore.exceptions.TooManyRequests(
            MagicMock()
        )

        scraper = _make_scraper(monkeypatch)
        with pytest.raises(ScraperRateLimitError):
            _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]


@pytest.mark.asyncio
async def test_generic_praw_error_raises_scraper_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unexpected PRAW exceptions are wrapped in ScraperError."""
    with patch("praw.Reddit") as mock_reddit_cls:
        mock_reddit = mock_reddit_cls.return_value
        mock_reddit.subreddit.return_value.new.side_effect = RuntimeError("unexpected")

        scraper = _make_scraper(monkeypatch)
        with pytest.raises(ScraperError):
            _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_praw_scraper_satisfies_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRAWOAuthScraper must be an instance of RedditScraper Protocol."""
    from src.scrapers.base import RedditScraper

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    from src.scrapers.praw_oauth import PRAWOAuthScraper

    scraper = PRAWOAuthScraper()
    assert isinstance(scraper, RedditScraper)

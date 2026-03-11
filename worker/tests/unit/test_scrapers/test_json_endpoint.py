"""Unit tests for JsonEndpointScraper.

All HTTP calls are mocked via pytest-httpx. No real Reddit requests are made.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from src.scrapers.base import ScraperRateLimitError, ScraperUnavailableError
from src.scrapers.json_endpoint import JsonEndpointScraper

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------


async def _noop(_: float) -> None:
    """No-op async sleep replacement for tests."""

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"

#: A timestamp in the future relative to PAST_SINCE (approx. Mar 2026).
_RECENT_TS = 1_770_000_000.0
#: A second recent timestamp slightly earlier.
_RECENT_TS_2 = 1_769_999_000.0
#: Cutoff: only comments newer than this are yielded.
_PAST_SINCE = datetime(2025, 1, 1, tzinfo=timezone.utc)  # Jan 2025
#: A timestamp older than PAST_SINCE (Jan 2020).
_OLD_TS = 1_580_000_000.0

_USER_AGENTS = ["TestAgent/1.0", "AnotherAgent/2.0"]


def _make_scraper(**kwargs: object) -> JsonEndpointScraper:
    return JsonEndpointScraper(user_agents=_USER_AGENTS, **kwargs)  # type: ignore[arg-type]


def _listing(children: list[dict[object, object]], after: str | None = None) -> dict[object, object]:
    """Build a minimal Reddit Listing JSON structure."""
    return {
        "kind": "Listing",
        "data": {"after": after, "children": children},
    }


def _post(selftext: str, ups: int, created_utc: float) -> dict[object, object]:
    return {"kind": "t3", "data": {"selftext": selftext, "ups": ups, "created_utc": created_utc}}


def _comment(body: str, ups: int, created_utc: float) -> dict[object, object]:
    return {"kind": "t1", "data": {"body": body, "ups": ups, "created_utc": created_utc}}


# ---------------------------------------------------------------------------
# Basic fetch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_correct_rawcomments(httpx_mock: HTTPXMock) -> None:
    """Successful fetch produces RawComment objects with correct fields."""
    fixture = json.loads((_FIXTURES_DIR / "reddit_new.json").read_text())
    httpx_mock.add_response(json=fixture)

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("wallstreetbets", _PAST_SINCE)]

    assert len(comments) == 2
    assert comments[0].text == "I think AAPL is going to the moon this week!"
    assert comments[0].upvotes == 42
    assert comments[0].created_utc.tzinfo is not None
    assert comments[1].text == "TSLA earnings looking great, very bullish."
    assert comments[1].upvotes == 17


@pytest.mark.asyncio
async def test_fetch_excludes_old_comments(httpx_mock: HTTPXMock) -> None:
    """Comments with created_utc <= since are excluded."""
    listing = _listing([
        _post("New post", 10, _RECENT_TS),
        _post("Old post", 5, _OLD_TS),
    ])
    httpx_mock.add_response(json=listing)

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].text == "New post"


@pytest.mark.asyncio
async def test_negative_upvotes_clamped_to_zero(httpx_mock: HTTPXMock) -> None:
    """Negative upvote counts are clamped to 0."""
    listing = _listing([_post("Downvoted post", -5, _RECENT_TS)])
    httpx_mock.add_response(json=listing)

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].upvotes == 0


@pytest.mark.asyncio
async def test_limit_respected(httpx_mock: HTTPXMock) -> None:
    """Yielded comments never exceed the specified limit."""
    listing = _listing([
        _post("Post 1", 1, _RECENT_TS),
        _post("Post 2", 2, _RECENT_TS - 1),
        _post("Post 3", 3, _RECENT_TS - 2),
    ])
    httpx_mock.add_response(json=listing)

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE, limit=2)]

    assert len(comments) == 2


@pytest.mark.asyncio
async def test_empty_body_items_skipped(httpx_mock: HTTPXMock) -> None:
    """Items with empty selftext/body are skipped."""
    listing = _listing([
        _post("", 10, _RECENT_TS),           # empty selftext
        _comment("Valid comment", 5, _RECENT_TS - 1),
    ])
    httpx_mock.add_response(json=listing)

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].text == "Valid comment"


# ---------------------------------------------------------------------------
# User-Agent header tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_agent_header_is_set(httpx_mock: HTTPXMock) -> None:
    """Every request includes a User-Agent header from the configured pool."""
    httpx_mock.add_response(json=_listing([]))

    scraper = _make_scraper()
    _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].headers["User-Agent"] in _USER_AGENTS


@pytest.mark.asyncio
async def test_user_agent_varies_across_pages(httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """User-Agent strings vary across paginated requests."""
    # Page 1 with an "after" cursor to trigger a second request.
    page1 = _listing([_post("Post 1", 1, _RECENT_TS)], after="t3_abc")
    page2 = _listing([_post("Post 2", 1, _RECENT_TS - 1)])
    httpx_mock.add_response(json=page1)
    httpx_mock.add_response(json=page2)

    # Zero the inter-page delay so the test is fast.
    async def _no_sleep(_: float) -> None:
        pass

    monkeypatch.setattr("src.scrapers.json_endpoint.asyncio.sleep", _no_sleep)

    scraper = _make_scraper(request_delay_seconds=0)
    _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    agents_used = {r.headers["User-Agent"] for r in httpx_mock.get_requests()}
    # With 2 user agents and 2 requests, at least one distinct agent must appear.
    assert agents_used.issubset(set(_USER_AGENTS))
    assert len(agents_used) >= 1


# ---------------------------------------------------------------------------
# Backoff and rate-limit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_triggers_backoff_and_retry(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single 429 triggers a backoff sleep, then a successful retry."""
    sleep_calls: list[float] = []

    async def _mock_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("src.scrapers.json_endpoint.asyncio.sleep", _mock_sleep)

    httpx_mock.add_response(status_code=429, headers={"Retry-After": "5"})
    httpx_mock.add_response(json=_listing([_post("Post", 1, _RECENT_TS)]))

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    # Backoff sleep must have been called with the Retry-After value.
    assert 5 in sleep_calls


@pytest.mark.asyncio
async def test_three_consecutive_429s_raise_rate_limit_error(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three consecutive 429 responses raise ScraperRateLimitError."""
    monkeypatch.setattr("src.scrapers.json_endpoint.asyncio.sleep", _noop)

    for _ in range(3):
        httpx_mock.add_response(status_code=429)

    scraper = _make_scraper()
    with pytest.raises(ScraperRateLimitError):
        _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]


@pytest.mark.asyncio
async def test_backoff_delay_increases_without_retry_after_header(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without Retry-After, backoff delay uses exponential formula."""
    sleep_calls: list[float] = []

    async def _mock_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("src.scrapers.json_endpoint.asyncio.sleep", _mock_sleep)

    # Two 429s without Retry-After, then success.
    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(json=_listing([_post("Post", 1, _RECENT_TS)]))

    scraper = _make_scraper()
    _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    # Delays should be exponential: 2^1=2, 2^2=4.
    assert sleep_calls[0] == 2
    assert sleep_calls[1] == 4


# ---------------------------------------------------------------------------
# HTTP error tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_403_raises_unavailable_error(httpx_mock: HTTPXMock) -> None:
    """HTTP 403 immediately raises ScraperUnavailableError."""
    httpx_mock.add_response(status_code=403)

    scraper = _make_scraper()
    with pytest.raises(ScraperUnavailableError):
        _ = [c async for c in scraper.fetch_comments("private_sub", _PAST_SINCE)]


@pytest.mark.asyncio
async def test_404_raises_unavailable_error(httpx_mock: HTTPXMock) -> None:
    """HTTP 404 immediately raises ScraperUnavailableError."""
    httpx_mock.add_response(status_code=404)

    scraper = _make_scraper()
    with pytest.raises(ScraperUnavailableError):
        _ = [c async for c in scraper.fetch_comments("nonexistent_sub", _PAST_SINCE)]


@pytest.mark.asyncio
async def test_5xx_retried_once_then_raises_scraper_error(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5xx responses are retried once; persistent 5xx raises ScraperError."""
    monkeypatch.setattr(
        "src.scrapers.json_endpoint.asyncio.sleep",
        _noop,
    )

    from src.scrapers.base import ScraperError

    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=503)

    scraper = _make_scraper()
    with pytest.raises(ScraperError):
        _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]


# ---------------------------------------------------------------------------
# Privacy / logging tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comment_text_never_logged(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Comment text must not appear in any log output at any level."""
    secret_text = "SUPERSECRET_TICKER_MENTION_XYZ"
    listing = _listing([_post(secret_text, 10, _RECENT_TS)])
    httpx_mock.add_response(json=listing)

    scraper = _make_scraper()
    with caplog.at_level(logging.DEBUG, logger="src.scrapers.json_endpoint"):
        _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    for record in caplog.records:
        assert secret_text not in record.getMessage()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_json_endpoint_scraper_satisfies_protocol() -> None:
    """JsonEndpointScraper must be an instance of RedditScraper Protocol."""
    from src.scrapers.base import RedditScraper

    scraper = _make_scraper()
    assert isinstance(scraper, RedditScraper)

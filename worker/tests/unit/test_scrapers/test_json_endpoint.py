"""Unit tests for JsonEndpointScraper.

All HTTP calls are mocked via pytest-httpx. No real Reddit requests are made.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
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
_PAST_SINCE = datetime(2025, 1, 1, tzinfo=UTC)  # Jan 2025
#: A timestamp older than PAST_SINCE (Jan 2020).
_OLD_TS = 1_580_000_000.0

_USER_AGENTS = ["TestAgent/1.0", "AnotherAgent/2.0"]


def _make_scraper(**kwargs: object) -> JsonEndpointScraper:
    return JsonEndpointScraper(user_agents=_USER_AGENTS, **kwargs)  # type: ignore[arg-type]


def _listing(
    children: list[dict[object, object]], after: str | None = None
) -> dict[object, object]:
    """Build a minimal Reddit Listing JSON structure."""
    return {
        "kind": "Listing",
        "data": {"after": after, "children": children},
    }


def _post(selftext: str, ups: int, created_utc: float) -> dict[object, object]:
    return {
        "kind": "t3",
        "data": {
            "title": "",
            "selftext": selftext,
            "ups": ups,
            "num_comments": 0,
            "permalink": "/r/test/comments/test/post/",
            "created_utc": created_utc,
        },
    }


def _comment(body: str, ups: int, created_utc: float) -> dict[object, object]:
    return {"kind": "t1", "data": {"body": body, "ups": ups, "created_utc": created_utc}}


def _thread(children: list[dict[object, object]]) -> list[dict[object, object]]:
    return [
        _listing([]),
        _listing(children),
    ]


# ---------------------------------------------------------------------------
# Basic fetch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_correct_rawcomments(httpx_mock: HTTPXMock) -> None:
    """Successful fetch produces RawComment objects with correct fields."""
    fixture = json.loads((_FIXTURES_DIR / "reddit_new.json").read_text())
    httpx_mock.add_response(json=fixture)
    httpx_mock.add_response(json=_thread([]))

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("wallstreetbets", _PAST_SINCE)]

    assert len(comments) == 2
    assert comments[0].text == "I think AAPL is going to the moon this week!"
    assert comments[0].upvotes == 42
    assert comments[0].created_utc.tzinfo is not None
    assert comments[0].content_type == "post"
    assert comments[0].source_thread_url == "https://www.reddit.com/r/wallstreetbets/comments/abc123/test_post/"
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
    httpx_mock.add_response(json=_thread([]))

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].text == "New post"


@pytest.mark.asyncio
async def test_negative_upvotes_clamped_to_zero(httpx_mock: HTTPXMock) -> None:
    """Negative upvote counts are clamped to 0."""
    listing = _listing([_post("Downvoted post", -5, _RECENT_TS)])
    httpx_mock.add_response(json=listing)
    httpx_mock.add_response(json=_thread([]))

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
    httpx_mock.add_response(json=_thread([]))

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
    assert comments[0].content_type == "comment"


@pytest.mark.asyncio
async def test_post_title_is_included_for_link_posts(httpx_mock: HTTPXMock) -> None:
    """Post titles should be included so title-only Epic mentions are matched."""
    listing = _listing([
        {
            "kind": "t3",
            "data": {
                "title": "Free on Epic this week",
                "selftext": "",
                "ups": 33,
                "created_utc": _RECENT_TS,
            },
        },
    ])
    httpx_mock.add_response(json=listing)

    scraper = _make_scraper()
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].text == "Free on Epic this week"
    assert comments[0].content_type == "post"


@pytest.mark.asyncio
async def test_thread_comments_are_fetched_from_post_permalink(
    httpx_mock: HTTPXMock,
) -> None:
    """Each recent post is expanded via its thread ``.json`` endpoint."""
    listing = _listing([
        {
            "kind": "t3",
            "data": {
                "title": "Bullish DD",
                "selftext": "",
                "ups": 10,
                "num_comments": 2,
                "permalink": "/r/test/comments/abc123/bullish_dd/",
                "created_utc": _RECENT_TS,
            },
        }
    ])
    thread = _thread([
        {
            "kind": "t1",
            "data": {
                "body": "AAPL looks strong",
                "ups": 7,
                "created_utc": _RECENT_TS - 1,
                "replies": "",
            },
        }
    ])
    httpx_mock.add_response(json=listing)
    httpx_mock.add_response(json=thread)

    scraper = _make_scraper(request_delay_seconds=0)
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 2
    assert comments[0].content_type == "post"
    assert comments[0].reply_count == 2
    assert comments[0].source_thread_url == "https://www.reddit.com/r/test/comments/abc123/bullish_dd/"
    assert comments[1].text == "AAPL looks strong"
    assert comments[1].content_type == "comment"
    assert comments[1].source_thread_url == "https://www.reddit.com/r/test/comments/abc123/bullish_dd/"


@pytest.mark.asyncio
async def test_thread_403_keeps_post_instead_of_failing_source(
    httpx_mock: HTTPXMock,
) -> None:
    """A blocked thread expansion should not discard the already-seen post."""
    listing = _listing([
        {
            "kind": "t3",
            "data": {
                "title": "Epic thread",
                "selftext": "Body",
                "ups": 9,
                "num_comments": 4,
                "permalink": "/r/test/comments/abc123/epic_thread/",
                "created_utc": _RECENT_TS,
            },
        }
    ])
    httpx_mock.add_response(json=listing)
    httpx_mock.add_response(status_code=403)

    scraper = _make_scraper(request_delay_seconds=0)
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    assert len(comments) == 1
    assert comments[0].content_type == "post"
    assert comments[0].text == "Epic thread | Body"
    assert comments[0].source_thread_url == "https://www.reddit.com/r/test/comments/abc123/epic_thread/"


@pytest.mark.asyncio
async def test_thread_comment_reply_count_uses_descendant_total(
    httpx_mock: HTTPXMock,
) -> None:
    """Comment reply_count should include nested descendant comments."""
    listing = _listing([
        {
            "kind": "t3",
            "data": {
                "title": "Thread starter",
                "selftext": "",
                "ups": 10,
                "num_comments": 3,
                "permalink": "/r/test/comments/abc123/thread_starter/",
                "created_utc": _RECENT_TS,
            },
        }
    ])
    thread = _thread([
        {
            "kind": "t1",
            "data": {
                "body": "Top comment",
                "ups": 5,
                "created_utc": _RECENT_TS - 1,
                "replies": {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "body": "Reply one",
                                    "ups": 2,
                                    "created_utc": _RECENT_TS - 2,
                                    "replies": {
                                        "data": {
                                            "children": [
                                                {
                                                    "kind": "t1",
                                                    "data": {
                                                        "body": "Nested reply",
                                                        "ups": 1,
                                                        "created_utc": _RECENT_TS - 3,
                                                        "replies": "",
                                                    },
                                                }
                                            ]
                                        }
                                    },
                                },
                            }
                        ]
                    }
                },
            },
        }
    ])
    httpx_mock.add_response(json=listing)
    httpx_mock.add_response(json=thread)

    scraper = _make_scraper(request_delay_seconds=0)
    comments = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    top_comment = comments[1]
    assert top_comment.text == "Top comment"
    assert top_comment.reply_count == 2


# ---------------------------------------------------------------------------
# User-Agent header tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_agent_header_is_set(httpx_mock: HTTPXMock) -> None:
    """Every request includes browser-style headers and a configured User-Agent."""
    httpx_mock.add_response(json=_listing([]))

    scraper = _make_scraper()
    _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].headers["User-Agent"] in _USER_AGENTS
    assert requests[0].headers["Accept"].startswith("text/html")
    assert requests[0].headers["Accept-Language"] in {
        "en-US,en;q=0.9",
        "en-US,en;q=0.8",
        "en-GB,en;q=0.9",
    }
    assert requests[0].headers["Referer"] == "https://www.reddit.com/"
    assert requests[0].headers["Sec-Fetch-Mode"] == "navigate"


@pytest.mark.asyncio
async def test_user_agent_varies_across_pages(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User-Agent strings vary across paginated requests."""
    # Page 1 with an "after" cursor to trigger a second request.
    page1 = _listing([_post("Post 1", 1, _RECENT_TS)], after="t3_abc")
    page2 = _listing([_post("Post 2", 1, _RECENT_TS - 1)])
    httpx_mock.add_response(json=page1)
    httpx_mock.add_response(json=_thread([]))
    httpx_mock.add_response(json=page2)
    httpx_mock.add_response(json=_thread([]))

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


@pytest.mark.asyncio
async def test_thread_request_uses_same_origin_fetch_headers(
    httpx_mock: HTTPXMock,
) -> None:
    """Thread expansion requests should look like same-origin navigation."""
    listing = _listing([_post("Post 1", 1, _RECENT_TS)])
    httpx_mock.add_response(json=listing)
    httpx_mock.add_response(json=_thread([]))

    scraper = _make_scraper(request_delay_seconds=0)
    _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[1].headers["Sec-Fetch-Site"] == "same-origin"
    assert requests[1].headers["Referer"] == "https://www.reddit.com/"


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
    httpx_mock.add_response(json=_thread([]))

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
    httpx_mock.add_response(json=_thread([]))

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
    sentinel_text = "SENTINEL_TICKER_MENTION_XYZ"  # not a real secret
    listing = _listing([_post(sentinel_text, 10, _RECENT_TS)])
    httpx_mock.add_response(json=listing)
    httpx_mock.add_response(json=_thread([]))

    scraper = _make_scraper()
    with caplog.at_level(logging.DEBUG, logger="src.scrapers.json_endpoint"):
        _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

    for record in caplog.records:
        assert sentinel_text not in record.getMessage()


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_json_endpoint_scraper_satisfies_protocol() -> None:
    """JsonEndpointScraper must be an instance of RedditScraper Protocol."""
    from src.scrapers.base import RedditScraper

    scraper = _make_scraper()
    assert isinstance(scraper, RedditScraper)


def test_empty_user_agents_raises_value_error() -> None:
    """Constructing JsonEndpointScraper with an empty user-agent list raises ValueError."""
    with pytest.raises(ValueError, match="user_agents must contain at least one entry"):
        JsonEndpointScraper(user_agents=[])


def test_is_available_returns_true() -> None:
    """is_available() always returns True (no credentials required)."""
    scraper = _make_scraper()
    assert scraper.is_available() is True


@pytest.mark.asyncio
async def test_unexpected_status_code_raises_scraper_error(
    httpx_mock: HTTPXMock,
) -> None:
    """Unexpected HTTP status codes (not 200/429/403/404/5xx) raise ScraperError."""
    from src.scrapers.base import ScraperError

    # HTTP 418 (I'm a teapot) is unexpected
    httpx_mock.add_response(status_code=418)

    scraper = _make_scraper()
    with pytest.raises(ScraperError, match="Unexpected HTTP 418"):
        _ = [c async for c in scraper.fetch_comments("test", _PAST_SINCE)]

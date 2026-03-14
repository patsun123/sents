"""
Mock Reddit API responses for integration tests.

All responses are representative of real Reddit .json endpoint
structures but contain no real user data.

Comments include:
- Explicit $GME and $TSLA mentions (strong signals)
- Bare TSLA all-caps mention (weak signal, passes disambiguation)
- "IT" mention (blocklisted — should be filtered out)
- Purely neutral text (no tickers, discarded by classifier)
- Varying upvote counts: 1, 500, 10000
- One post with created_utc in the past (for incremental-fetch tests)

PII guarantee: no username, comment_id, post_id, or author fields in any
response fixture.
"""
from __future__ import annotations

import time

# Current UTC timestamp used as baseline (far future = always "new")
_NOW = time.time() + 3600 * 24 * 365  # one year from now

# ---------------------------------------------------------------------------
# wallstreetbets mock responses
# ---------------------------------------------------------------------------

MOCK_REDDIT_RESPONSE: dict[str, object] = {
    "kind": "Listing",
    "data": {
        "after": None,
        "dist": 5,
        "children": [
            {
                # Explicit $GME mention — positive sentiment
                "kind": "t1",
                "data": {
                    "body": "$GME to the moon! Short squeeze incoming!",
                    "ups": 10000,
                    "created_utc": _NOW - 60,
                },
            },
            {
                # Explicit $TSLA mention — positive sentiment
                "kind": "t3",
                "data": {
                    "selftext": "$TSLA earnings going to crush expectations. Very bullish.",
                    "ups": 500,
                    "created_utc": _NOW - 120,
                },
            },
            {
                # Bare TSLA mention — passes disambiguation as it is in universe
                "kind": "t1",
                "data": {
                    "body": "TSLA looking great this week, loaded up on calls.",
                    "ups": 1,
                    "created_utc": _NOW - 180,
                },
            },
            {
                # "IT" bare mention — blocklisted, should be filtered
                "kind": "t1",
                "data": {
                    "body": "IT is the best sector right now, trust me.",
                    "ups": 5,
                    "created_utc": _NOW - 240,
                },
            },
            {
                # Purely neutral text — no tickers, neutral VADER score
                "kind": "t1",
                "data": {
                    "body": "The weather is nice today.",
                    "ups": 2,
                    "created_utc": _NOW - 300,
                },
            },
        ],
    },
}


# Response with explicitly old comment (created before since cutoff)
# Used for incremental-fetch tests: second cycle sees the same data but
# all created_utc are in the past relative to the last successful run.
MOCK_REDDIT_RESPONSE_OLD: dict[str, object] = {
    "kind": "Listing",
    "data": {
        "after": None,
        "dist": 1,
        "children": [
            {
                "kind": "t1",
                "data": {
                    "body": "$GME to the moon!",
                    "ups": 100,
                    "created_utc": 1000.0,  # very old — year 1970
                },
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# stocks subreddit mock response (for source-isolation tests)
# ---------------------------------------------------------------------------

MOCK_STOCKS_RESPONSE: dict[str, object] = {
    "kind": "Listing",
    "data": {
        "after": None,
        "dist": 2,
        "children": [
            {
                "kind": "t1",
                "data": {
                    "body": "$AAPL is undervalued right now, great long-term buy.",
                    "ups": 42,
                    "created_utc": _NOW - 60,
                },
            },
            {
                "kind": "t1",
                "data": {
                    "body": "TSLA will dominate EVs for a decade.",
                    "ups": 17,
                    "created_utc": _NOW - 120,
                },
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# 429 response (rate-limit) fixture
# ---------------------------------------------------------------------------

# Used to simulate a 429 Too Many Requests on the first call.
# Tests that backoff / rate-limit handling works correctly.
MOCK_429_RESPONSE_THEN_SUCCESS = [
    # First call returns 429
    {"status_code": 429, "headers": {"Retry-After": "1"}},
    # Second call returns valid data
    {"status_code": 200, "json": MOCK_REDDIT_RESPONSE},
]

# ---------------------------------------------------------------------------
# Empty listing (no new comments)
# ---------------------------------------------------------------------------

MOCK_EMPTY_RESPONSE: dict[str, object] = {
    "kind": "Listing",
    "data": {
        "after": None,
        "dist": 0,
        "children": [],
    },
}

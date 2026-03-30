"""Shared fixtures for scraper tests."""
import pytest


@pytest.fixture
def sample_reddit_post_data():
    """Raw Reddit API post data dict."""
    return {
        "kind": "t3",
        "data": {
            "id": "abc123",
            "title": "TSLA is going to the moon!",
            "selftext": "Tesla stock is looking very bullish today, diamond hands everyone.",
            "author": "trader42",
            "score": 150,
            "upvote_ratio": 0.92,
            "num_comments": 45,
            "subreddit": "wallstreetbets",
            "permalink": "/r/wallstreetbets/comments/abc123/tsla_moon/",
            "created_utc": 1711800000.0,
        },
    }


@pytest.fixture
def sample_comment_data():
    """Raw Reddit API comment data dict."""
    return {
        "kind": "t1",
        "data": {
            "id": "xyz789",
            "body": "TSLA calls printing money, this is amazing!",
            "author": "options_trader",
            "score": 42,
            "subreddit": "wallstreetbets",
            "created_utc": 1711800100.0,
        },
    }


@pytest.fixture
def bot_post_data():
    """Post from a bot that should be filtered."""
    return {
        "kind": "t3",
        "data": {
            "id": "bot001",
            "title": "Daily Discussion Thread",
            "selftext": "Post your daily plays here.",
            "author": "AutoModerator",
            "score": 5,
            "upvote_ratio": 0.80,
            "num_comments": 200,
            "subreddit": "wallstreetbets",
            "permalink": "/r/wallstreetbets/comments/bot001/daily/",
            "created_utc": 1711800000.0,
        },
    }


@pytest.fixture
def deleted_post_data():
    """Deleted post that should be filtered."""
    return {
        "kind": "t3",
        "data": {
            "id": "del001",
            "title": "Some title",
            "selftext": "[deleted]",
            "author": "[deleted]",
            "score": 10,
            "upvote_ratio": 0.5,
            "num_comments": 3,
            "subreddit": "stocks",
            "permalink": "/r/stocks/comments/del001/x/",
            "created_utc": 1711800000.0,
        },
    }


@pytest.fixture
def short_post_data():
    """Too-short post that should be filtered."""
    return {
        "kind": "t3",
        "data": {
            "id": "short01",
            "title": "Hi",
            "selftext": "",
            "author": "user1",
            "score": 1,
            "upvote_ratio": 0.5,
            "num_comments": 0,
            "subreddit": "stocks",
            "permalink": "/r/stocks/comments/short01/hi/",
            "created_utc": 1711800000.0,
        },
    }

"""Tests for RedditClient._should_skip() quality filter."""
from scraper.reddit.client import RedditClient


def test_skip_deleted_author():
    client = RedditClient()
    assert client._should_skip({"author": "[deleted]", "selftext": "some text content here"}) is True


def test_skip_removed_content():
    client = RedditClient()
    assert client._should_skip({"author": "user1", "selftext": "[removed]", "title": ""}) is True


def test_skip_bot():
    client = RedditClient()
    assert client._should_skip({"author": "AutoModerator", "selftext": "long enough content here for testing", "title": ""}) is True


def test_skip_short_content():
    client = RedditClient(min_content_length=20)
    assert client._should_skip({"author": "user1", "selftext": "hi", "title": ""}) is True


def test_accept_valid_post():
    client = RedditClient()
    assert client._should_skip({
        "author": "trader42",
        "selftext": "TSLA is going to the moon diamond hands!",
        "title": "TSLA Bull Case",
    }) is False


def test_custom_bot_list():
    client = RedditClient(bot_usernames={"mybot"})
    assert client._should_skip({"author": "mybot", "selftext": "long enough content here", "title": ""}) is True
    assert client._should_skip({"author": "AutoModerator", "selftext": "long enough content here", "title": ""}) is False

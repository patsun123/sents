"""Tests for RedditClient post/comment parsing."""
from scraper.reddit.client import _parse_post, _mentions_ticker, _fingerprint


def test_parse_post_valid(sample_reddit_post_data):
    post = _parse_post(sample_reddit_post_data, "TSLA")
    assert post is not None
    assert post.reddit_id == "abc123"
    assert post.ticker_mentioned == "TSLA"
    assert post.score == 150
    assert post.subreddit == "wallstreetbets"


def test_parse_post_missing_id():
    bad_data = {"data": {"title": "test"}}
    assert _parse_post(bad_data, "TSLA") is None


def test_mentions_ticker_found():
    assert _mentions_ticker("TSLA is going up", "TSLA") is True


def test_mentions_ticker_not_found():
    assert _mentions_ticker("AAPL is going up", "TSLA") is False


def test_mentions_ticker_case_insensitive():
    assert _mentions_ticker("tsla is going up", "TSLA") is True


def test_mentions_ticker_word_boundary():
    assert _mentions_ticker("TSLAQ is not TSLA", "TSLA") is True  # TSLA found in second word


def test_fingerprint_deterministic():
    fp1 = _fingerprint("id1", "TSLA", "some content")
    fp2 = _fingerprint("id1", "TSLA", "some content")
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex


def test_fingerprint_different_for_different_inputs():
    fp1 = _fingerprint("id1", "TSLA", "content a")
    fp2 = _fingerprint("id2", "TSLA", "content b")
    assert fp1 != fp2

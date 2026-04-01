"""Scraper factory and lane selection."""
from __future__ import annotations

import os

from .base import RedditScraper
from .json_endpoint import JsonEndpointScraper

_DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (compatible; SentiXBot/1.0; +https://github.com/patsun123/sents)",
]


def get_primary_scraper() -> RedditScraper:
    """
    Return the primary (no-auth) scraper.

    Always returns a ``JsonEndpointScraper`` with the default User-Agent pool.
    """
    return JsonEndpointScraper(user_agents=_DEFAULT_USER_AGENTS)


def get_fallback_scraper() -> RedditScraper | None:
    """
    Return the OAuth fallback scraper, or ``None`` if credentials are absent.

    Checks ``REDDIT_CLIENT_ID`` before importing PRAW so that the service
    starts cleanly even without Reddit OAuth credentials configured.
    """
    if not os.getenv("REDDIT_CLIENT_ID"):
        return None
    from .praw_oauth import PRAWOAuthScraper

    return PRAWOAuthScraper()

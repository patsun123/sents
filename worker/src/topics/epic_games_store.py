"""
Epic Games Store relevance matching.

This module repurposes the existing extraction/disambiguation pipeline for a
single tracked entity: the Epic Games Store. Unlike stock tickers, matching is
keyword- and context-based so generic uses of the word "epic" do not create
signals unless store-specific context is present.
"""
from __future__ import annotations

import re

from ..tickers.extractor import ExtractedTicker

EPIC_GAMES_STORE_KEY = "EGS_STORE"

_STRONG_PATTERNS = [
    re.compile(r"\bepic games store\b", re.IGNORECASE),
    re.compile(r"\bepic store\b", re.IGNORECASE),
    re.compile(r"\bepic games launcher\b", re.IGNORECASE),
    re.compile(r"\bepic launcher\b", re.IGNORECASE),
    re.compile(r"\bfree on epic\b", re.IGNORECASE),
    re.compile(r"\bon epic\b", re.IGNORECASE),
    re.compile(r"\bepic exclusive\b", re.IGNORECASE),
    re.compile(r"\bepic exclusives\b", re.IGNORECASE),
    re.compile(r"\begs\b", re.IGNORECASE),
]
_EPIC_TOKEN = re.compile(r"\bepic\b", re.IGNORECASE)
_STORE_CONTEXT = re.compile(
    r"\b("
    r"store|launcher|free game|free games|freebie|freebies|"
    r"exclusive|exclusives|coupon|sale|megasale|library|client|"
    r"platform|app|account|giveaway|giveaways|ownership|owned"
    r")\b",
    re.IGNORECASE,
)
_EPIC_PREPOSITIONAL_CONTEXT = re.compile(
    r"\b("
    r"on epic|from epic|via epic|through epic|in epic"
    r")\b",
    re.IGNORECASE,
)


class EpicGamesStoreExtractor:
    """
    Detect text that is actually about the Epic Games Store.

    Matching rules:
    - Strong phrases like ``"Epic Games Store"`` or ``"EGS"`` match directly.
    - Otherwise the text must mention ``"epic"`` plus store-specific context
      like ``"launcher"``, ``"exclusive"``, or ``"free games"``.
    """

    def extract(self, text: str) -> list[ExtractedTicker]:
        """Return a single synthetic entity match when Epic Store relevance is high."""
        if not text.strip():
            return []

        if any(pattern.search(text) for pattern in _STRONG_PATTERNS):
            return [ExtractedTicker(symbol=EPIC_GAMES_STORE_KEY, explicit=True)]

        if _EPIC_PREPOSITIONAL_CONTEXT.search(text):
            return [ExtractedTicker(symbol=EPIC_GAMES_STORE_KEY, explicit=True)]

        if _EPIC_TOKEN.search(text) and _STORE_CONTEXT.search(text):
            return [ExtractedTicker(symbol=EPIC_GAMES_STORE_KEY, explicit=False)]

        return []


class EpicGamesStoreDisambiguator:
    """Pass through only the Epic Games Store synthetic entity key."""

    def filter(self, candidates: list[ExtractedTicker]) -> list[str]:
        """Deduplicate and keep only valid Epic Games Store matches."""
        return list(
            {
                candidate.symbol
                for candidate in candidates
                if candidate.symbol == EPIC_GAMES_STORE_KEY
            }
        )

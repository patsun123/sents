"""
Storefront topic extraction for Epic Games Store and Steam Store.

This module detects whether text is about the Epic Games Store, Steam,
or both. It deliberately avoids broad generic matches so common uses of
"epic" and lower-signal references like "Steam Deck" do not create store
sentiment signals by themselves.
"""
from __future__ import annotations

import re

from ..tickers.extractor import ExtractedTicker

EPIC_GAMES_STORE_KEY = "EGS_STORE"
STEAM_STORE_KEY = "STEAM_STOR"

_EPIC_STRONG_PATTERNS = [
    re.compile(r"\bepic games store\b", re.IGNORECASE),
    re.compile(r"\bepic store\b", re.IGNORECASE),
    re.compile(r"\bepic games launcher\b", re.IGNORECASE),
    re.compile(r"\bepic launcher\b", re.IGNORECASE),
    re.compile(r"\bfree on epic\b", re.IGNORECASE),
    re.compile(r"\bon epic\b", re.IGNORECASE),
    re.compile(r"\bepic exclusive(?:s)?\b", re.IGNORECASE),
    re.compile(r"\begs\b", re.IGNORECASE),
]
_EPIC_TOKEN = re.compile(r"\bepic\b", re.IGNORECASE)
_EPIC_STORE_CONTEXT = re.compile(
    r"\b("
    r"store|launcher|free game|free games|freebie|freebies|"
    r"exclusive|exclusives|coupon|sale|megasale|library|client|"
    r"platform|app|account|giveaway|giveaways|ownership|owned"
    r")\b",
    re.IGNORECASE,
)
_EPIC_PREPOSITIONAL_CONTEXT = re.compile(
    r"\b(on epic|from epic|via epic|through epic|in epic)\b",
    re.IGNORECASE,
)
_EPIC_COMPARATIVE_CONTEXT = re.compile(
    r"\b("
    r"epic can'?t compare|epic can't compare|better than epic|prefer steam|"
    r"back to steam|returned to steam|go to steam because"
    r")\b",
    re.IGNORECASE,
)

_STEAM_STRONG_PATTERNS = [
    re.compile(r"\bsteam store\b", re.IGNORECASE),
    re.compile(r"\bsteam client\b", re.IGNORECASE),
    re.compile(r"\bsteam launcher\b", re.IGNORECASE),
    re.compile(r"\bon steam\b", re.IGNORECASE),
    re.compile(r"\bback to steam\b", re.IGNORECASE),
    re.compile(r"\breturned to steam\b", re.IGNORECASE),
    re.compile(r"\bsteam sale\b", re.IGNORECASE),
    re.compile(r"\bsteam library\b", re.IGNORECASE),
]
_STEAM_TOKEN = re.compile(r"\bsteam\b", re.IGNORECASE)
_STEAM_STORE_CONTEXT = re.compile(
    r"\b("
    r"store|client|launcher|sale|library|wishlist|refund|cart|"
    r"platform|account|overlay|review|reviews|keys|pricing|price|"
    r"buy|bought|purchase|purchased|deck verified"
    r")\b",
    re.IGNORECASE,
)
_STEAM_COMPARATIVE_CONTEXT = re.compile(
    r"\b("
    r"better than epic|prefer steam|go to steam|back to steam|returned to steam|"
    r"buy on steam|buy it on steam|steam is better|compared to steam"
    r")\b",
    re.IGNORECASE,
)
_STEAM_DECK_ONLY = re.compile(r"\bsteam deck\b", re.IGNORECASE)


class StorefrontExtractor:
    """Extract Epic and Steam storefront entities from text."""

    def extract(self, text: str) -> list[ExtractedTicker]:
        """Return storefront entity matches for the given text."""
        if not text.strip():
            return []

        matches: dict[str, ExtractedTicker] = {}
        normalized = text.strip()

        if self._matches_epic(normalized):
            matches[EPIC_GAMES_STORE_KEY] = ExtractedTicker(
                symbol=EPIC_GAMES_STORE_KEY,
                explicit=True,
            )

        if self._matches_steam(normalized):
            matches[STEAM_STORE_KEY] = ExtractedTicker(
                symbol=STEAM_STORE_KEY,
                explicit=True,
            )

        return list(matches.values())

    @staticmethod
    def _matches_epic(text: str) -> bool:
        if any(pattern.search(text) for pattern in _EPIC_STRONG_PATTERNS):
            return True
        if _EPIC_PREPOSITIONAL_CONTEXT.search(text):
            return True
        if _EPIC_TOKEN.search(text) and _EPIC_COMPARATIVE_CONTEXT.search(text):
            return True
        return bool(_EPIC_TOKEN.search(text) and _EPIC_STORE_CONTEXT.search(text))

    @staticmethod
    def _matches_steam(text: str) -> bool:
        if any(pattern.search(text) for pattern in _STEAM_STRONG_PATTERNS):
            return True
        if _STEAM_COMPARATIVE_CONTEXT.search(text):
            return True
        if _STEAM_DECK_ONLY.search(text) and not _STEAM_STORE_CONTEXT.search(text):
            return False
        return bool(_STEAM_TOKEN.search(text) and _STEAM_STORE_CONTEXT.search(text))


class StorefrontDisambiguator:
    """Pass through only supported storefront entity keys."""

    _valid_symbols = {EPIC_GAMES_STORE_KEY, STEAM_STORE_KEY}

    def filter(self, candidates: list[ExtractedTicker]) -> list[str]:
        """Deduplicate and keep only supported storefront entity keys."""
        return list(
            {
                candidate.symbol
                for candidate in candidates
                if candidate.symbol in self._valid_symbols
            }
        )

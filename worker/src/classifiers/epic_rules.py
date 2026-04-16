"""
Rule-first storefront sentiment classifier.

The default backend remains ``epic_rules`` for compatibility, but the
implementation now supports both Epic Games Store and Steam Store scoring.
It can classify the same sentence differently depending on the target entity,
which is necessary for comparative text like "Steam is better than Epic."
"""
from __future__ import annotations

import re

from ..topics import EPIC_GAMES_STORE_KEY, STEAM_STORE_KEY
from .base import ClassificationResult

_EPIC_POSITIVE_PATTERNS = [
    re.compile(r"\bprefer the epic store(?: to steam)?\b", re.IGNORECASE),
    re.compile(r"\bprefer epic\b", re.IGNORECASE),
    re.compile(r"\bcheaper on epic\b", re.IGNORECASE),
    re.compile(r"\bfree on epic\b", re.IGNORECASE),
    re.compile(r"\bnever had an issue with the launcher\b", re.IGNORECASE),
    re.compile(r"\bno issue with the launcher\b", re.IGNORECASE),
    re.compile(r"\blooking forward\b.*\bprefer the epic store\b", re.IGNORECASE),
    re.compile(r"\bgood on epic\b", re.IGNORECASE),
]

_EPIC_NEGATIVE_PATTERNS = [
    re.compile(r"\bdelete your epic account\b", re.IGNORECASE),
    re.compile(r"\bharmful\b", re.IGNORECASE),
    re.compile(r"\bonly came for free games\b", re.IGNORECASE),
    re.compile(r"\breturned to steam\b", re.IGNORECASE),
    re.compile(r"\bback to steam\b", re.IGNORECASE),
    re.compile(r"\bepic can'?t even compare to steam\b", re.IGNORECASE),
    re.compile(r"\bgo to steam because\b", re.IGNORECASE),
    re.compile(r"\bonly reason i buy on steam\b", re.IGNORECASE),
    re.compile(r"\bepic paid for it\b", re.IGNORECASE),
    re.compile(r"\bnever went back to epic\b", re.IGNORECASE),
    re.compile(r"\bepic exclusive(?:s)?\b", re.IGNORECASE),
    re.compile(r"\bexclusives are\b.*\bannoying\b", re.IGNORECASE),
    re.compile(r"\btired of waiting for launcher updates\b", re.IGNORECASE),
    re.compile(r"\bbarely changed\b", re.IGNORECASE),
    re.compile(r"\bneeds to improve\b", re.IGNORECASE),
    re.compile(r"\blaggy\b", re.IGNORECASE),
    re.compile(r"\bnothing but a storefront\b", re.IGNORECASE),
    re.compile(r"\bwhat does epic have to offer\b", re.IGNORECASE),
    re.compile(r"\bmostly shit\b", re.IGNORECASE),
]

_STEAM_POSITIVE_PATTERNS = [
    re.compile(r"\bprefer steam\b", re.IGNORECASE),
    re.compile(r"\breturned to steam\b", re.IGNORECASE),
    re.compile(r"\bback to steam\b", re.IGNORECASE),
    re.compile(r"\bgo to steam because\b", re.IGNORECASE),
    re.compile(r"\bonly reason i buy on steam\b", re.IGNORECASE),
    re.compile(r"\bsteam is better\b", re.IGNORECASE),
    re.compile(r"\bsteam(?: client| ui)? is better\b", re.IGNORECASE),
    re.compile(r"\bepic can'?t even compare to steam\b", re.IGNORECASE),
    re.compile(r"\bcompare to steam\b", re.IGNORECASE),
    re.compile(r"\bbuy on steam\b", re.IGNORECASE),
]

_STEAM_NEGATIVE_PATTERNS = [
    re.compile(r"\bprefer the epic store to steam\b", re.IGNORECASE),
    re.compile(r"\bprefer epic to steam\b", re.IGNORECASE),
    re.compile(r"\bcheaper on epic\b", re.IGNORECASE),
    re.compile(r"\bsteam is worse\b", re.IGNORECASE),
    re.compile(r"\bsteam sucks\b", re.IGNORECASE),
    re.compile(r"\bsteam is bloated\b", re.IGNORECASE),
    re.compile(r"\bsteam can'?t compete\b", re.IGNORECASE),
]

_MIXED_PATTERNS = [
    re.compile(r"\bcheaper, but\b", re.IGNORECASE),
    re.compile(r"\bbut as a platform\b", re.IGNORECASE),
    re.compile(r"\bnever had an issue\b.*\bbut\b", re.IGNORECASE),
    re.compile(r"\bfree games\b.*\bbut\b", re.IGNORECASE),
]


class EpicRulesClassifier:
    """Rule-first classifier for storefront discourse."""

    def classify(self, text: str) -> ClassificationResult:
        """Backward-compatible default: score relative to the Epic store."""
        return self.classify_for_target(EPIC_GAMES_STORE_KEY, text)

    def classify_for_target(self, target: str, text: str) -> ClassificationResult:
        """Classify text relative to a specific storefront target."""
        normalized = text.strip().lower()
        if not normalized:
            return ClassificationResult(polarity=0, confidence=0.0, discarded=True)

        if target == EPIC_GAMES_STORE_KEY:
            return self._classify_epic(normalized)
        if target == STEAM_STORE_KEY:
            return self._classify_steam(normalized)
        return ClassificationResult(polarity=0, confidence=0.0, discarded=True)

    def _classify_epic(self, normalized: str) -> ClassificationResult:
        positive_hits = self._count_hits(normalized, _EPIC_POSITIVE_PATTERNS)
        negative_hits = self._count_hits(normalized, _EPIC_NEGATIVE_PATTERNS)
        mixed = any(pattern.search(normalized) for pattern in _MIXED_PATTERNS)

        if "steam" in normalized and any(
            token in normalized
            for token in (
                "better",
                "prefer steam",
                "go to steam",
                "back to steam",
                "returned to steam",
            )
        ):
            negative_hits += 1

        if "epic" in normalized and "prefer the epic store" in normalized:
            positive_hits += 2

        if "epic" in normalized and "free games" in normalized and (
            "only" in normalized or "came for" in normalized
        ):
            negative_hits += 1

        return self._finalize_hits(
            positive_hits=positive_hits,
            negative_hits=negative_hits,
            mixed=mixed,
        )

    def _classify_steam(self, normalized: str) -> ClassificationResult:
        positive_hits = self._count_hits(normalized, _STEAM_POSITIVE_PATTERNS)
        negative_hits = self._count_hits(normalized, _STEAM_NEGATIVE_PATTERNS)
        mixed = any(pattern.search(normalized) for pattern in _MIXED_PATTERNS)

        if "steam" in normalized and "epic can't even compare to steam" in normalized:
            positive_hits += 2
        if "prefer the epic store to steam" in normalized:
            negative_hits += 2
        if "steam" in normalized and "better than epic" in normalized:
            positive_hits += 1

        return self._finalize_hits(
            positive_hits=positive_hits,
            negative_hits=negative_hits,
            mixed=mixed,
        )

    @staticmethod
    def _count_hits(normalized: str, patterns: list[re.Pattern[str]]) -> int:
        return sum(bool(pattern.search(normalized)) for pattern in patterns)

    @staticmethod
    def _finalize_hits(
        *,
        positive_hits: int,
        negative_hits: int,
        mixed: bool,
    ) -> ClassificationResult:
        if mixed and negative_hits >= positive_hits:
            confidence = min(1.0, 0.65 + 0.08 * negative_hits)
            return ClassificationResult(polarity=-1, confidence=confidence, discarded=False)

        if negative_hits > positive_hits:
            confidence = min(1.0, 0.62 + 0.08 * negative_hits)
            return ClassificationResult(polarity=-1, confidence=confidence, discarded=False)

        if positive_hits > negative_hits and not mixed:
            confidence = min(1.0, 0.6 + 0.08 * positive_hits)
            return ClassificationResult(polarity=1, confidence=confidence, discarded=False)

        return ClassificationResult(polarity=0, confidence=0.2, discarded=True)

    def is_ready(self) -> bool:
        """Rules are ready immediately."""
        return True

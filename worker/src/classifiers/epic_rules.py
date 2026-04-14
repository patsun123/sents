"""
EpicRulesClassifier: Epic Games Store specific sentiment rules.

This classifier is intentionally narrow. It targets the recurring failure
mode in Epic-vs-Steam discourse where generic sentiment tools score comments
as positive because of words like "good", "support", or "free" even when the
overall judgment is anti-Epic.
"""
from __future__ import annotations

import re

from .base import ClassificationResult

_POSITIVE_PATTERNS = [
    re.compile(r"\bprefer the epic store(?: to steam)?\b", re.IGNORECASE),
    re.compile(r"\bprefer epic\b", re.IGNORECASE),
    re.compile(r"\bcheaper on epic\b", re.IGNORECASE),
    re.compile(r"\bfree on epic\b", re.IGNORECASE),
    re.compile(r"\bnever had an issue with the launcher\b", re.IGNORECASE),
    re.compile(r"\bno issue with the launcher\b", re.IGNORECASE),
    re.compile(r"\blooking forward\b.*\bprefer the epic store\b", re.IGNORECASE),
    re.compile(r"\bgood questions with some interesting answers\b", re.IGNORECASE),
    re.compile(r"\bgames end up \d+\-\d+% cheaper on other platforms\b", re.IGNORECASE),
]

_NEGATIVE_PATTERNS = [
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
    re.compile(r"\bepic exclusive\b", re.IGNORECASE),
    re.compile(r"\bexclusives are\b.*\bannoying\b", re.IGNORECASE),
    re.compile(r"\btired of waiting for launcher updates\b", re.IGNORECASE),
    re.compile(r"\bbarely changed\b", re.IGNORECASE),
    re.compile(r"\bneeds to improve\b", re.IGNORECASE),
    re.compile(r"\blaggy\b", re.IGNORECASE),
    re.compile(r"\bnothing but a store front\b", re.IGNORECASE),
    re.compile(r"\bfunctionally competitive with steam\b", re.IGNORECASE),
    re.compile(r"\bbenefit of epic launcher starts and ends\b", re.IGNORECASE),
    re.compile(r"\bwhat does epic have to offer\b", re.IGNORECASE),
    re.compile(r"\bmostly shit\b", re.IGNORECASE),
]

_MIXED_PATTERNS = [
    re.compile(r"\bcheaper, but\b", re.IGNORECASE),
    re.compile(r"\bbut as a platform\b", re.IGNORECASE),
    re.compile(r"\bi really like epic\b.*\bdisappointed\b", re.IGNORECASE),
    re.compile(r"\bnever had an issue\b.*\bbut\b", re.IGNORECASE),
    re.compile(r"\bfree games\b.*\bbut\b", re.IGNORECASE),
]


class EpicRulesClassifier:
    """Rule-first classifier for Epic Games Store discourse."""

    def classify(self, text: str) -> ClassificationResult:
        """Classify Epic-related text as positive, negative, or ambiguous."""
        normalized = text.strip().lower()
        if not normalized:
            return ClassificationResult(polarity=0, confidence=0.0, discarded=True)

        positive_hits = sum(bool(pattern.search(normalized)) for pattern in _POSITIVE_PATTERNS)
        negative_hits = sum(bool(pattern.search(normalized)) for pattern in _NEGATIVE_PATTERNS)
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

        if mixed and negative_hits >= positive_hits:
            confidence = min(1.0, 0.65 + 0.08 * negative_hits)
            return ClassificationResult(polarity=-1, confidence=confidence, discarded=False)

        if negative_hits > positive_hits:
            confidence = min(1.0, 0.62 + 0.08 * negative_hits)
            return ClassificationResult(polarity=-1, confidence=confidence, discarded=False)

        if positive_hits > negative_hits and not mixed:
            confidence = min(1.0, 0.6 + 0.08 * positive_hits)
            return ClassificationResult(polarity=1, confidence=confidence, discarded=False)

        if positive_hits > negative_hits and "prefer the epic store" in normalized:
            confidence = min(1.0, 0.7 + 0.08 * positive_hits)
            return ClassificationResult(polarity=1, confidence=confidence, discarded=False)

        return ClassificationResult(polarity=0, confidence=0.2, discarded=True)

    def is_ready(self) -> bool:
        """Rules are ready immediately."""
        return True

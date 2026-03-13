"""
VADERClassifier: default sentiment classifier using VADER.

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a rule-based
classifier tuned for social media text. No model download required.

Polarity mapping:
  compound >= threshold  -> positive (polarity=1)
  compound <= -threshold -> negative (polarity=-1)
  otherwise              -> neutral (discarded=True)

Known limitations:
  WSB slang ("tendies", "yolo", "to the moon") may score as neutral since
  VADER's lexicon predates Reddit finance communities. Fine-tuning is
  Priority 2 in the development roadmap.
"""
from __future__ import annotations

import os

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import-untyped]

from .base import ClassificationResult, ClassifierError

_DEFAULT_NEUTRAL_THRESHOLD = 0.05


class VADERClassifier:
    """
    Sentiment classifier backed by VADER.

    The SentimentIntensityAnalyzer is instantiated once at __init__
    (expensive, ~50ms) and reused for all classify() calls (cheap).

    Environment variables:
        VADER_NEUTRAL_THRESHOLD: Float threshold for neutral zone (default 0.05).
            Compounds in (-threshold, threshold) are discarded as neutral.
    """

    def __init__(self) -> None:
        """Initialise the VADER analyzer and load neutral threshold from env."""
        self._analyzer = SentimentIntensityAnalyzer()
        self._threshold = float(
            os.getenv("VADER_NEUTRAL_THRESHOLD", str(_DEFAULT_NEUTRAL_THRESHOLD))
        )

    def classify(self, text: str) -> ClassificationResult:
        """
        Classify text sentiment using VADER compound score.

        Args:
            text: Comment body. Never logged or persisted.

        Returns:
            ClassificationResult with binary polarity.
            When discarded=True, polarity=0 (undefined — pipeline must check).

        Raises:
            ClassifierError: If VADER fails unexpectedly.
        """
        try:
            scores = self._analyzer.polarity_scores(text)
        except Exception as exc:
            raise ClassifierError(f"VADER classification failed: {exc}") from exc

        compound = scores["compound"]
        confidence = abs(compound)  # normalized 0.0-1.0

        if compound >= self._threshold:
            return ClassificationResult(polarity=1, confidence=confidence, discarded=False)
        elif compound <= -self._threshold:
            return ClassificationResult(polarity=-1, confidence=confidence, discarded=False)
        else:
            return ClassificationResult(polarity=0, confidence=confidence, discarded=True)

    def is_ready(self) -> bool:
        """Return True — VADER is always ready after __init__."""
        return True

"""VADER sentiment analysis backend."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import]

logger = logging.getLogger(__name__)

_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


@dataclass
class VaderResult:
    compound: float
    positive: float
    negative: float
    neutral: float
    raw_scores: dict


def analyze(text: str) -> VaderResult:
    """Run VADER on text. Returns scores in [-1, 1] range for compound."""
    analyzer = _get_analyzer()
    scores = analyzer.polarity_scores(text)
    return VaderResult(
        compound=scores["compound"],
        positive=scores["pos"],
        negative=scores["neg"],
        neutral=scores["neu"],
        raw_scores=scores,
    )


def analyze_batch(texts: list[str]) -> list[VaderResult]:
    return [analyze(t) for t in texts]

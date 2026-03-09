"""TextBlob sentiment analysis backend."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TextBlobResult:
    compound: float      # polarity mapped to [-1, 1]
    positive: float
    negative: float
    neutral: float
    raw_scores: dict


def analyze(text: str) -> TextBlobResult:
    """Run TextBlob on text. Polarity is [-1, 1], subjectivity [0, 1]."""
    from textblob import TextBlob  # type: ignore[import]

    blob = TextBlob(text)
    polarity = blob.sentiment.polarity      # -1 to 1
    subjectivity = blob.sentiment.subjectivity  # 0 to 1

    # Map polarity to pos/neg/neu
    pos = max(0.0, polarity)
    neg = max(0.0, -polarity)
    neu = 1.0 - abs(polarity)

    return TextBlobResult(
        compound=polarity,
        positive=pos,
        negative=neg,
        neutral=neu,
        raw_scores={"polarity": polarity, "subjectivity": subjectivity},
    )


def analyze_batch(texts: list[str]) -> list[TextBlobResult]:
    return [analyze(t) for t in texts]

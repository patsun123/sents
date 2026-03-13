"""
SentimentClassifier Protocol and ClassificationResult.

All classifier implementations must satisfy this Protocol.
Using structural subtyping (Protocol) means implementations
do not import from this module -- they just need matching signatures.

PRIVACY RULE: The text argument to classify() must never be
persisted, logged, or stored in any instance variable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ClassificationResult:
    """
    Output of a single comment sentiment classification.

    Attributes:
        polarity: -1 (negative) or 1 (positive). Undefined when discarded=True.
        confidence: Classifier's internal confidence, 0.0-1.0.
        discarded: True if comment is neutral/ambiguous and should not produce a signal.
    """

    polarity: int  # -1 or 1
    confidence: float  # 0.0-1.0
    discarded: bool  # True = do not create a SentimentSignal


class ClassifierError(Exception):
    """Raised when classification fails unrecoverably."""


@runtime_checkable
class SentimentClassifier(Protocol):
    """
    Interface for all sentiment classifier implementations.

    Implementations must be safe to call concurrently (stateless per call).
    Model loading happens once at __init__, not per classify() call.
    """

    def classify(self, text: str) -> ClassificationResult:
        """
        Classify the sentiment of a single text string.

        Args:
            text: Comment body. NEVER log, persist, or store this argument.

        Returns:
            ClassificationResult with polarity, confidence, and discard flag.

        Raises:
            ClassifierError: If classification fails unrecoverably.
        """
        ...

    def is_ready(self) -> bool:
        """
        Return True if classifier is loaded and ready.

        Used during startup validation and health checks.
        """
        ...

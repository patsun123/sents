"""
Classifier factory.

Select classifier via CLASSIFIER_BACKEND environment variable:
  - "vader" (default): lightweight, no model download
  - "finbert": finance-domain transformer (requires finbert module)

Example:
    from worker.src.classifiers import get_classifier
    classifier = get_classifier()
    result = classifier.classify("GME to the moon!")
"""
from __future__ import annotations

import os

from .base import SentimentClassifier


def get_classifier() -> SentimentClassifier:
    """
    Return the configured sentiment classifier.

    Reads CLASSIFIER_BACKEND env var. Defaults to 'vader'.

    Returns:
        A SentimentClassifier implementation.

    Raises:
        ValueError: Unknown backend specified.
        ImportError: 'finbert' selected but FinBERTClassifier not available.
    """
    backend = os.getenv("CLASSIFIER_BACKEND", "vader").lower().strip()

    match backend:
        case "vader":
            from .vader import VADERClassifier

            return VADERClassifier()
        case "finbert":
            # Lazy import: FinBERT requires torch + transformers (~2GB).
            # Raises ImportError with a clear message if the module is absent.
            try:
                from .finbert import (
                    FinBERTClassifier as _FinBERT,
                )
            except ImportError as exc:
                raise ImportError(
                    "FinBERT backend is not installed. "
                    "Install torch and transformers to enable CLASSIFIER_BACKEND=finbert. "
                    f"Original error: {exc}"
                ) from exc
            instance: SentimentClassifier = _FinBERT()
            return instance
        case _:
            raise ValueError(
                f"Unknown CLASSIFIER_BACKEND: '{backend}'. "
                f"Supported values: 'vader', 'finbert'."
            )

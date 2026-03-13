# Contract: SentimentClassifier Interface

**Type**: Python Protocol (structural subtyping)
**File**: `worker/src/classifiers/base.py`
**Date**: 2026-03-09

---

## Purpose

Defines the interface that all sentiment classifier implementations must satisfy. Using a `Protocol` (PEP 544) rather than an abstract base class means implementations do not need to import or inherit from this module — they just need the correct method signatures. The active classifier is selected via the `CLASSIFIER_BACKEND` environment variable.

---

## Protocol Definition

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationResult:
    """Output of a single comment classification."""
    polarity: int          # -1 (negative) or 1 (positive)
    confidence: float      # 0.0–1.0; classifier's internal confidence score
    discarded: bool        # True if comment is ambiguous/neutral and should not be stored


@runtime_checkable
class SentimentClassifier(Protocol):
    """
    Interface for all sentiment classifier implementations.

    Implementations must be stateless with respect to individual calls.
    Initialization (model loading) happens once at startup.
    """

    def classify(self, text: str) -> ClassificationResult:
        """
        Classify the sentiment of a single text string.

        Args:
            text: Raw comment text (in-memory only; never persisted)

        Returns:
            ClassificationResult with polarity, confidence, and discard flag

        Raises:
            ClassifierError: If classification fails unrecoverably
        """
        ...

    def is_ready(self) -> bool:
        """
        Returns True if the classifier is loaded and ready to process.
        Used during health checks and startup validation.
        """
        ...
```

---

## Implementations

| Backend | `CLASSIFIER_BACKEND` value | Notes |
|---------|---------------------------|-------|
| VADER | `vader` (default) | Lightweight, no model download, CPU-only |
| FinBERT | `finbert` | ~400MB download on first run, CPU inference ~200–500ms/comment |

---

## Selection Logic

```python
# worker/src/classifiers/__init__.py

import os
from .vader import VADERClassifier
from .base import SentimentClassifier


def get_classifier() -> SentimentClassifier:
    backend = os.getenv("CLASSIFIER_BACKEND", "vader").lower()
    match backend:
        case "vader":
            return VADERClassifier()
        case "finbert":
            from .finbert import FinBERTClassifier  # lazy import — only load if configured
            return FinBERTClassifier()
        case _:
            raise ValueError(f"Unknown classifier backend: {backend}")
```

---

## Behaviour Rules

- `classify()` must never persist the `text` argument or any derivative containing the original text
- `polarity` is strictly binary: `-1` or `1`. Neutral results must set `discarded = True`
- `classify()` must be safe to call concurrently (stateless per call)
- `ClassifierError` must be caught by the pipeline runner; a failed classification discards the comment but does not fail the cycle

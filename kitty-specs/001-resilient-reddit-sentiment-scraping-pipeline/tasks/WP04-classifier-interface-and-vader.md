---
work_package_id: WP04
title: Classifier Interface & VADER
lane: "doing"
dependencies: [WP01]
base_branch: 001-resilient-reddit-sentiment-scraping-pipeline-WP01
base_commit: 7e38de562c61693212607d5f4fb1061125053261
created_at: '2026-03-13T14:53:40.204083+00:00'
subtasks:
- T017
- T018
- T019
- T020
- T021
phase: Phase 1 - Core Components
assignee: ''
agent: ''
shell_pid: "11224"
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-03-09T19:41:43Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
requirement_refs:
- FR-003
---

# Work Package Prompt: WP04 - Classifier Interface & VADER

## Objectives & Success Criteria

- `SentimentClassifier` Protocol defined with `ClassificationResult` dataclass
- `VADERClassifier` correctly maps compound score to polarity=1 (positive), polarity=-1 (negative), discarded=True (neutral)
- Neutral threshold configurable via `VADER_NEUTRAL_THRESHOLD` env var (default 0.05)
- Classifier factory (`get_classifier()`) selects correct implementation via `CLASSIFIER_BACKEND` env var
- `CLASSIFIER_BACKEND=finbert` raises a clear `ImportError` (FinBERT module not yet implemented) — not a crash
- VADER `SentimentIntensityAnalyzer` instantiated ONCE at class init, not per `classify()` call
- Comment text is never logged at any level
- Unit tests pass; `ruff`, `mypy`, `bandit` clean

## Context & Constraints

- **Spec**: FR-003, FR-004a — sentiment polarity classification, pluggable algorithms
- **Contract**: `contracts/classifier-interface.md` — canonical Protocol definition
- **Research**: R-003 — FinBERT availability (CPU inference, lazy import)
- **WP04 parallel with WP02, WP03, WP05** — no shared code between them
- **"The algorithm is the product"**: The classifier interface is the most important extensibility point in SSE

**Implementation command**: `spec-kitty implement WP04 --base WP01`

---

## Subtasks & Detailed Guidance

### Subtask T017 - Define SentimentClassifier Protocol

**Purpose**: Establish the contract every classifier must satisfy. Defines once; all implementations are structurally typed — no inheritance required.

**Steps**:
1. Create `worker/src/classifiers/base.py`:

```python
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
    polarity: int        # -1 or 1
    confidence: float    # 0.0-1.0
    discarded: bool      # True = do not create a SentimentSignal


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
```

**Files**: `worker/src/classifiers/base.py`

---

### Subtask T018 - Implement VADERClassifier

**Purpose**: The default, zero-setup sentiment classifier. VADER understands internet text, capitalization, and punctuation emphasis — adequate for initial SSE launch.

**Steps**:
1. Create `worker/src/classifiers/vader.py`:

```python
"""
VADERClassifier: default sentiment classifier using VADER.

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a rule-based
classifier tuned for social media text. No model download required.

Polarity mapping:
  compound >= threshold  -> positive (polarity=1)
  compound <= -threshold -> negative (polarity=-1)
  otherwise              -> neutral (discarded=True)
"""
from __future__ import annotations

import os

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .base import ClassificationResult, ClassifierError


_DEFAULT_NEUTRAL_THRESHOLD = 0.05


class VADERClassifier:
    """
    Sentiment classifier backed by VADER.

    The SentimentIntensityAnalyzer is instantiated once at __init__
    (expensive) and reused for all classify() calls (cheap).
    """

    def __init__(self) -> None:
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
        """VADER is always ready after __init__."""
        return True
```

**Files**: `worker/src/classifiers/vader.py`

**Notes**:
- VADER `SentimentIntensityAnalyzer()` loads a lexicon file at instantiation (~50ms). Do this once.
- `polarity=0` when `discarded=True` — the pipeline runner must check `discarded` before creating a signal

---

### Subtask T019 - Classifier factory

**Purpose**: Single entry point for classifier selection. FinBERT is supported via lazy import — if the module doesn't exist, the error is clear and expected.

**Steps**:
1. Update `worker/src/classifiers/__init__.py`:

```python
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
            # If not installed, this raises ImportError with a clear message.
            from .finbert import FinBERTClassifier  # type: ignore[import]
            return FinBERTClassifier()
        case _:
            raise ValueError(
                f"Unknown CLASSIFIER_BACKEND: '{backend}'. "
                f"Supported values: 'vader', 'finbert'."
            )
```

**Files**: `worker/src/classifiers/__init__.py`

---

### Subtask T020 - Unit tests for VADERClassifier

**Purpose**: Verify polarity mapping, neutral discard, threshold configuration, and the privacy guarantee (text never logged).

**Steps**:
1. Create `worker/tests/unit/test_classifiers/test_vader.py`:

```python
import pytest
from unittest.mock import patch
from worker.src.classifiers.vader import VADERClassifier
from worker.src.classifiers.base import ClassificationResult


@pytest.fixture
def classifier():
    return VADERClassifier()


def test_positive_sentiment(classifier):
    result = classifier.classify("GME is absolutely going to the moon! Best stock ever!")
    assert result.polarity == 1
    assert result.discarded is False
    assert 0.0 <= result.confidence <= 1.0


def test_negative_sentiment(classifier):
    result = classifier.classify("This company is completely bankrupt and worthless.")
    assert result.polarity == -1
    assert result.discarded is False


def test_neutral_is_discarded(classifier):
    result = classifier.classify("The stock price changed.")
    assert result.discarded is True


def test_custom_threshold(monkeypatch):
    monkeypatch.setenv("VADER_NEUTRAL_THRESHOLD", "0.3")
    c = VADERClassifier()
    # A mildly positive sentence that passes 0.05 but not 0.3
    result = c.classify("The stock went up a little.")
    assert result.discarded is True  # below 0.3 threshold


def test_is_ready(classifier):
    assert classifier.is_ready() is True


def test_text_not_logged(classifier, caplog):
    secret_text = "SECRET_COMMENT_DO_NOT_LOG"
    classifier.classify(secret_text)
    assert secret_text not in caplog.text


def test_classifier_error_on_failure(classifier, monkeypatch):
    from worker.src.classifiers.base import ClassifierError
    monkeypatch.setattr(
        classifier._analyzer, "polarity_scores",
        lambda _: (_ for _ in ()).throw(RuntimeError("VADER failed"))
    )
    with pytest.raises(ClassifierError):
        classifier.classify("anything")
```

**Files**: `worker/tests/unit/test_classifiers/test_vader.py`

---

### Subtask T021 - Integration test for classifier factory

**Purpose**: Verify the factory selects the correct implementation and handles unknown backends gracefully.

**Steps**:
1. Create `worker/tests/unit/test_classifiers/test_factory.py`:

```python
import pytest
from worker.src.classifiers import get_classifier
from worker.src.classifiers.vader import VADERClassifier


def test_default_is_vader():
    classifier = get_classifier()
    assert isinstance(classifier, VADERClassifier)


def test_vader_explicit(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_BACKEND", "vader")
    classifier = get_classifier()
    assert isinstance(classifier, VADERClassifier)


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_BACKEND", "gpt99")
    with pytest.raises(ValueError, match="Unknown CLASSIFIER_BACKEND"):
        get_classifier()


def test_finbert_import_error(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_BACKEND", "finbert")
    with pytest.raises(ImportError):
        get_classifier()  # finbert module doesn't exist yet -- expected


def test_vader_classify_roundtrip():
    classifier = get_classifier()
    result = classifier.classify("Best stock ever!")
    assert result.polarity in (-1, 1) or result.discarded is True
```

**Files**: `worker/tests/unit/test_classifiers/test_factory.py`

---

## Test Strategy

- No external API calls (VADER is fully local)
- `caplog` fixture verifies text is never logged
- `monkeypatch` used for env var and threshold testing

## Risks & Mitigations

- **VADER accuracy on WSB slang**: "tendies", "yolo", "to the moon" — VADER may score these neutrally. Document known limitations in `VADERClassifier` docstring. Fine-tuning is Priority 2 in the development roadmap.
- **VADER analyzer instantiation cost**: ~50ms at startup. Acceptable. Must NOT be instantiated per-call.
- **FinBERT stub**: `get_classifier("finbert")` will raise `ImportError` — this is expected and tested. The error message should guide the operator to install torch + transformers.

## Review Guidance

- Verify `_analyzer` is instantiated in `__init__`, not in `classify()`
- Verify `discarded=True` for neutral text (compound in [-0.05, 0.05])
- Verify `text` argument never appears in any log call
- Verify `get_classifier("finbert")` raises `ImportError` (not a crash, not a 500)
- Verify `mypy --strict` passes (all return types annotated)

## Activity Log

- 2026-03-09T19:41:43Z - system - lane=planned - Prompt created.

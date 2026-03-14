"""
Unit tests for the classifier factory (get_classifier).

Covers:
- Default backend is VADER
- Explicit CLASSIFIER_BACKEND=vader returns VADERClassifier
- Unknown backend raises ValueError with helpful message
- CLASSIFIER_BACKEND=finbert raises ImportError (module not yet implemented)
- Full classify() round-trip via factory
"""
from __future__ import annotations

import pytest

from classifiers import get_classifier
from classifiers.vader import VADERClassifier


def test_default_is_vader(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CLASSIFIER_BACKEND is not set, default to VADERClassifier."""
    monkeypatch.delenv("CLASSIFIER_BACKEND", raising=False)
    classifier = get_classifier()
    assert isinstance(classifier, VADERClassifier)


def test_vader_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLASSIFIER_BACKEND=vader should return a VADERClassifier."""
    monkeypatch.setenv("CLASSIFIER_BACKEND", "vader")
    classifier = get_classifier()
    assert isinstance(classifier, VADERClassifier)


def test_vader_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend name should be matched case-insensitively."""
    monkeypatch.setenv("CLASSIFIER_BACKEND", "VADER")
    classifier = get_classifier()
    assert isinstance(classifier, VADERClassifier)


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown CLASSIFIER_BACKEND should raise ValueError with a clear message."""
    monkeypatch.setenv("CLASSIFIER_BACKEND", "gpt99")
    with pytest.raises(ValueError, match="Unknown CLASSIFIER_BACKEND"):
        get_classifier()


def test_unknown_backend_message_contains_backend_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValueError message should include the invalid backend name."""
    monkeypatch.setenv("CLASSIFIER_BACKEND", "badbackend")
    with pytest.raises(ValueError, match="badbackend"):
        get_classifier()


def test_finbert_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """finbert backend raises ImportError — module not yet implemented, expected."""
    monkeypatch.setenv("CLASSIFIER_BACKEND", "finbert")
    with pytest.raises(ImportError):
        get_classifier()  # finbert module doesn't exist yet -- expected


def test_vader_classify_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory-created classifier must produce a valid ClassificationResult."""
    monkeypatch.delenv("CLASSIFIER_BACKEND", raising=False)
    classifier = get_classifier()
    result = classifier.classify("Best stock ever!")
    assert result.polarity in (-1, 0, 1)
    assert isinstance(result.discarded, bool)
    assert 0.0 <= result.confidence <= 1.0


def test_factory_returns_ready_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory-returned classifier must report is_ready() == True."""
    monkeypatch.delenv("CLASSIFIER_BACKEND", raising=False)
    classifier = get_classifier()
    assert classifier.is_ready() is True

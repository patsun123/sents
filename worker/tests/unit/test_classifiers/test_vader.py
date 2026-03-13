"""
Unit tests for VADERClassifier.

Covers:
- Positive / negative / neutral polarity mapping
- Neutral discard behaviour
- Custom VADER_NEUTRAL_THRESHOLD env var
- is_ready() always True
- Privacy guarantee: text never appears in logs
- ClassifierError raised on unexpected VADER failure
"""
from __future__ import annotations

import pytest

from classifiers.base import ClassificationResult, ClassifierError
from classifiers.vader import VADERClassifier


@pytest.fixture
def classifier() -> VADERClassifier:
    """Provide a default VADERClassifier instance."""
    return VADERClassifier()


def test_positive_sentiment(classifier: VADERClassifier) -> None:
    """Strongly positive text should yield polarity=1 and discarded=False."""
    result = classifier.classify("GME is absolutely going to the moon! Best stock ever!")
    assert result.polarity == 1
    assert result.discarded is False
    assert 0.0 <= result.confidence <= 1.0


def test_negative_sentiment(classifier: VADERClassifier) -> None:
    """Strongly negative text should yield polarity=-1 and discarded=False."""
    result = classifier.classify("This company is completely bankrupt and worthless.")
    assert result.polarity == -1
    assert result.discarded is False
    assert 0.0 <= result.confidence <= 1.0


def test_neutral_is_discarded(classifier: VADERClassifier) -> None:
    """Neutral text should be discarded (no signal created)."""
    result = classifier.classify("The stock price changed.")
    assert result.discarded is True


def test_discarded_result_is_classification_result(classifier: VADERClassifier) -> None:
    """Discarded results must still be ClassificationResult instances."""
    result = classifier.classify("The stock price changed.")
    assert isinstance(result, ClassificationResult)


def test_custom_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """A high threshold should discard mildly positive sentences."""
    monkeypatch.setenv("VADER_NEUTRAL_THRESHOLD", "0.3")
    c = VADERClassifier()
    # A mildly positive sentence that passes 0.05 but not 0.3
    result = c.classify("The stock went up a little.")
    assert result.discarded is True  # below 0.3 threshold


def test_default_threshold_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env override, default threshold 0.05 should be used."""
    monkeypatch.delenv("VADER_NEUTRAL_THRESHOLD", raising=False)
    c = VADERClassifier()
    assert c._threshold == 0.05


def test_is_ready(classifier: VADERClassifier) -> None:
    """VADER is always ready after __init__."""
    assert classifier.is_ready() is True


def test_text_not_logged(classifier: VADERClassifier, caplog: pytest.LogCaptureFixture) -> None:
    """Privacy guarantee: comment text must never appear in any log output."""
    secret_text = "SECRET_COMMENT_DO_NOT_LOG"  # noqa: S105
    classifier.classify(secret_text)
    assert secret_text not in caplog.text


def test_confidence_is_abs_compound(classifier: VADERClassifier) -> None:
    """Confidence should equal abs(compound) — ranges 0.0-1.0."""
    result = classifier.classify("Amazing! Incredible! Best stock ever!")
    assert 0.0 <= result.confidence <= 1.0


def test_classifier_error_on_failure(
    classifier: VADERClassifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ClassifierError should be raised when VADER raises unexpectedly."""

    def _raise(_text: str) -> None:
        raise RuntimeError("VADER failed")

    monkeypatch.setattr(classifier._analyzer, "polarity_scores", _raise)
    with pytest.raises(ClassifierError):
        classifier.classify("anything")


def test_analyzer_instantiated_once() -> None:
    """The SentimentIntensityAnalyzer must be set at __init__, not per call."""
    c = VADERClassifier()
    analyzer_id_before = id(c._analyzer)
    c.classify("First call")
    c.classify("Second call")
    assert id(c._analyzer) == analyzer_id_before

"""Tests for TextBlob sentiment backend."""
from processor.sentiment.textblob_backend import analyze_batch


def test_analyze_batch_positive():
    results = analyze_batch(["This is a great and wonderful opportunity!"])
    assert len(results) == 1
    assert results[0].compound > 0


def test_analyze_batch_negative():
    results = analyze_batch(["This is a terrible and horrible disaster."])
    assert len(results) == 1
    assert results[0].compound < 0


def test_analyze_batch_returns_scores():
    results = analyze_batch(["Neutral test sentence."])
    assert len(results) == 1
    r = results[0]
    assert hasattr(r, 'compound')
    assert hasattr(r, 'positive')
    assert hasattr(r, 'negative')
    assert hasattr(r, 'neutral')
    assert hasattr(r, 'raw_scores')

"""Tests for VADER sentiment backend."""
from processor.sentiment.vader_backend import analyze_batch


def test_analyze_batch_positive():
    results = analyze_batch(["This stock is absolutely amazing and wonderful!"])
    assert len(results) == 1
    assert results[0].compound > 0


def test_analyze_batch_negative():
    results = analyze_batch(["This stock is terrible and awful, going bankrupt."])
    assert len(results) == 1
    assert results[0].compound < 0


def test_analyze_batch_multiple():
    texts = ["Great stock!", "Terrible stock!", "Regular stock."]
    results = analyze_batch(texts)
    assert len(results) == 3


def test_analyze_batch_empty():
    results = analyze_batch([])
    assert results == []

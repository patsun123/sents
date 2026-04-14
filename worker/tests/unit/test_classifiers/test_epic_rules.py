"""
Unit tests for EpicRulesClassifier.

Covers:
- Positive Epic preference cases
- Negative Epic-vs-Steam comparative cases
- Mixed cases that should resolve negative
- Ambiguous text discarded
- is_ready() always True
"""
from __future__ import annotations

from src.classifiers.epic_rules import EpicRulesClassifier


def test_positive_epic_preference() -> None:
    """Clear Epic preference should score positive."""
    classifier = EpicRulesClassifier()
    result = classifier.classify(
        "Looking forward to this as I prefer the Epic Store to Steam."
    )
    assert result.polarity == 1
    assert result.discarded is False


def test_negative_delete_account() -> None:
    """Direct anti-Epic phrasing should score negative."""
    classifier = EpicRulesClassifier()
    result = classifier.classify(
        "It seems like you have an Epic games account. "
        "You should delete your Epic account because supporting Epic is harmful."
    )
    assert result.polarity == -1
    assert result.discarded is False


def test_negative_steam_comparison() -> None:
    """Steam-better-than-Epic phrasing should score negative."""
    classifier = EpicRulesClassifier()
    result = classifier.classify("Epic can't even compare to Steam.")
    assert result.polarity == -1
    assert result.discarded is False


def test_mixed_text_resolves_negative() -> None:
    """Mixed praise-plus-critique should stay negative when critique dominates."""
    classifier = EpicRulesClassifier()
    result = classifier.classify(
        "Games are cheaper on Epic, but as a platform Epic can't even compare to Steam."
    )
    assert result.polarity == -1
    assert result.discarded is False


def test_ambiguous_text_is_discarded() -> None:
    """Uninformative mentions should not create a signal."""
    classifier = EpicRulesClassifier()
    result = classifier.classify("The Epic launcher exists.")
    assert result.discarded is True


def test_is_ready() -> None:
    """Rule classifier is always ready."""
    assert EpicRulesClassifier().is_ready() is True

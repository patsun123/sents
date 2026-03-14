"""
Unit tests for :class:`tickers.extractor.TickerExtractor`.

Covers WSB-style comment formats, edge cases, and false-positive scenarios.
No external calls; all tests operate purely on in-memory strings.
"""

import pytest

from tickers.extractor import ExtractedTicker, TickerExtractor


@pytest.fixture
def extractor() -> TickerExtractor:
    """Return a fresh TickerExtractor for each test."""
    return TickerExtractor()


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------


def test_explicit_dollar_sign(extractor: TickerExtractor) -> None:
    """$GME should be extracted as explicit=True."""
    results = extractor.extract("$GME to the moon!")
    assert any(t.symbol == "GME" and t.explicit for t in results)


def test_bare_caps(extractor: TickerExtractor) -> None:
    """TSLA bare ALL-CAPS should be extracted as explicit=False."""
    results = extractor.extract("Bought more TSLA today")
    assert any(t.symbol == "TSLA" and not t.explicit for t in results)


def test_multiple_tickers_in_one_text(extractor: TickerExtractor) -> None:
    """Multiple distinct tickers extracted from a single text."""
    results = extractor.extract("Long $GME and short TSLA")
    symbols = {t.symbol for t in results}
    assert "GME" in symbols
    assert "TSLA" in symbols


# ---------------------------------------------------------------------------
# Deduplication / explicit-overrides-bare
# ---------------------------------------------------------------------------


def test_explicit_overrides_bare(extractor: TickerExtractor) -> None:
    """When a symbol appears both as $GME and GME, return it once as explicit."""
    results = extractor.extract("$GME and GME are the same")
    gme = [t for t in results if t.symbol == "GME"]
    assert len(gme) == 1
    assert gme[0].explicit is True


def test_deduplication_bare_only(extractor: TickerExtractor) -> None:
    """Bare mention repeated multiple times returns the symbol only once."""
    results = extractor.extract("AAPL AAPL AAPL")
    aapl = [t for t in results if t.symbol == "AAPL"]
    assert len(aapl) == 1


# ---------------------------------------------------------------------------
# Single-letter exclusions
# ---------------------------------------------------------------------------


def test_single_letter_bare_excluded(extractor: TickerExtractor) -> None:
    """Single-letter bare tokens are excluded (too noisy)."""
    results = extractor.extract("I bought A shares of U")
    symbols = [t.symbol for t in results]
    assert "I" not in symbols
    assert "A" not in symbols
    assert "U" not in symbols


def test_explicit_single_letter_included(extractor: TickerExtractor) -> None:
    """$A explicit mention is included despite being one letter."""
    results = extractor.extract("Bought more $A")
    assert any(t.symbol == "A" and t.explicit for t in results)


# ---------------------------------------------------------------------------
# Case sensitivity
# ---------------------------------------------------------------------------


def test_mixed_case_not_extracted(extractor: TickerExtractor) -> None:
    """Mixed-case words like 'Tesla' must NOT be extracted."""
    results = extractor.extract("Tesla is a great company")
    symbols = [t.symbol for t in results]
    assert "TESLA" not in symbols


def test_lowercase_not_extracted(extractor: TickerExtractor) -> None:
    """All-lowercase words must NOT be extracted."""
    results = extractor.extract("gme to the moon")
    assert results == []


# ---------------------------------------------------------------------------
# Edge / boundary cases
# ---------------------------------------------------------------------------


def test_empty_text(extractor: TickerExtractor) -> None:
    """Empty string returns an empty list."""
    assert extractor.extract("") == []


def test_no_tickers(extractor: TickerExtractor) -> None:
    """Text with no stock mentions returns an empty list."""
    results = extractor.extract("no stock mentions here at all")
    assert results == []


def test_five_letter_ticker_accepted(extractor: TickerExtractor) -> None:
    """Five-letter tickers like GOOGL are within the 2–5 bare range."""
    results = extractor.extract("GOOGL is up today")
    assert any(t.symbol == "GOOGL" for t in results)


def test_six_letter_bare_excluded(extractor: TickerExtractor) -> None:
    """Six-letter ALL-CAPS strings are NOT extracted (outside 2–5 range)."""
    results = extractor.extract("GOOGLE earnings today")
    assert all(t.symbol != "GOOGLE" for t in results)


def test_explicit_six_letter_excluded(extractor: TickerExtractor) -> None:
    """$TOOLONG (6 chars) is not extracted; explicit pattern caps at 5."""
    results = extractor.extract("$TOOLNG to the moon")
    # TOOLNG is 6 chars — should not be extracted
    assert all(t.symbol != "TOOLNG" for t in results)


def test_explicit_five_letter_ticker(extractor: TickerExtractor) -> None:
    """$GOOGL explicit form is extracted correctly."""
    results = extractor.extract("$GOOGL just hit ATH")
    assert any(t.symbol == "GOOGL" and t.explicit for t in results)


def test_ticker_at_start_of_text(extractor: TickerExtractor) -> None:
    """Ticker at the very start of a string is detected."""
    results = extractor.extract("GME is going up")
    assert any(t.symbol == "GME" for t in results)


def test_ticker_at_end_of_text(extractor: TickerExtractor) -> None:
    """Ticker at the very end of a string is detected."""
    results = extractor.extract("I'm buying GME")
    assert any(t.symbol == "GME" for t in results)


def test_ticker_with_punctuation(extractor: TickerExtractor) -> None:
    """Bare ticker followed by punctuation is still detected."""
    results = extractor.extract("GME, TSLA, and AAPL!")
    symbols = {t.symbol for t in results}
    assert {"GME", "TSLA", "AAPL"}.issubset(symbols)


def test_extracted_ticker_is_frozen_dataclass(extractor: TickerExtractor) -> None:
    """ExtractedTicker is a frozen dataclass and thus hashable."""
    results = extractor.extract("$GME")
    assert len(results) == 1
    t = results[0]
    assert isinstance(t, ExtractedTicker)
    # frozen dataclasses are hashable
    assert hash(t) is not None
    # frozen dataclasses raise FrozenInstanceError on attempted mutation
    with pytest.raises(AttributeError):
        t.symbol = "OTHER"  # type: ignore[misc]

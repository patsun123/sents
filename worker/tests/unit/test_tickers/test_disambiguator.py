"""
Unit tests for :class:`tickers.disambiguator.TickerDisambiguator`.

Uses ``tmp_path`` fixtures with isolated data files so each test controls
the blocklist and universe precisely.  No external HTTP calls.
"""

import pytest

from tickers.disambiguator import TickerDisambiguator
from tickers.extractor import ExtractedTicker


@pytest.fixture
def disambiguator(tmp_path: pytest.TempPathFactory) -> TickerDisambiguator:
    """Return a TickerDisambiguator backed by controlled data files.

    Blocklist:  IT, NOW, AM
    Universe:   GME, TSLA, AAPL, IT
    """
    data_dir = tmp_path / "data"  # type: ignore[operator]
    data_dir.mkdir()
    (data_dir / "false_positive_blocklist.txt").write_text("IT\nNOW\nAM\n", encoding="utf-8")
    (data_dir / "ticker_universe.txt").write_text("GME\nTSLA\nAAPL\nIT\n", encoding="utf-8")
    return TickerDisambiguator(data_dir=data_dir)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_valid — basic cases
# ---------------------------------------------------------------------------


def test_real_ticker_passes(disambiguator: TickerDisambiguator) -> None:
    """GME is in the universe and not blocklisted — should be valid."""
    assert disambiguator.is_valid("GME") is True


def test_blocklisted_bare_fails(disambiguator: TickerDisambiguator) -> None:
    """IT is blocklisted; bare mention must fail."""
    assert disambiguator.is_valid("IT", explicit=False) is False


def test_blocklisted_explicit_passes(disambiguator: TickerDisambiguator) -> None:
    """$IT explicit mention bypasses the blocklist (user clearly meant the stock)."""
    assert disambiguator.is_valid("IT", explicit=True) is True


def test_not_in_universe_fails(disambiguator: TickerDisambiguator) -> None:
    """MADEUP is not in the ticker universe — must fail regardless of explicit flag."""
    assert disambiguator.is_valid("MADEUP") is False


def test_not_in_universe_explicit_still_fails(disambiguator: TickerDisambiguator) -> None:
    """$MADEUP explicit mention still fails because it is not in the universe."""
    assert disambiguator.is_valid("MADEUP", explicit=True) is False


def test_lowercase_symbol_normalised(disambiguator: TickerDisambiguator) -> None:
    """Symbol is uppercased internally; 'gme' should match 'GME'."""
    assert disambiguator.is_valid("gme") is True


# ---------------------------------------------------------------------------
# filter()
# ---------------------------------------------------------------------------


def test_filter_mixed_list(disambiguator: TickerDisambiguator) -> None:
    """filter() removes blocklisted bare tickers and unknown symbols."""
    candidates = [
        ExtractedTicker("GME", explicit=True),
        ExtractedTicker("IT", explicit=False),      # blocklisted bare
        ExtractedTicker("MADEUP", explicit=False),  # not in universe
        ExtractedTicker("TSLA", explicit=False),
    ]
    result = disambiguator.filter(candidates)
    assert set(result) == {"GME", "TSLA"}


def test_filter_explicit_blocklisted_included(disambiguator: TickerDisambiguator) -> None:
    """filter() keeps $IT because explicit=True bypasses blocklist."""
    candidates = [
        ExtractedTicker("IT", explicit=True),
        ExtractedTicker("TSLA", explicit=False),
    ]
    result = disambiguator.filter(candidates)
    assert set(result) == {"IT", "TSLA"}


def test_filter_empty_candidates(disambiguator: TickerDisambiguator) -> None:
    """filter() on empty list returns empty list."""
    assert disambiguator.filter([]) == []


def test_filter_all_blocked(disambiguator: TickerDisambiguator) -> None:
    """filter() returns empty list when all candidates are blocklisted."""
    candidates = [
        ExtractedTicker("IT", explicit=False),
        ExtractedTicker("NOW", explicit=False),
        ExtractedTicker("AM", explicit=False),
    ]
    assert disambiguator.filter(candidates) == []


# ---------------------------------------------------------------------------
# reload()
# ---------------------------------------------------------------------------


def test_reload_adds_new_ticker(
    disambiguator: TickerDisambiguator, tmp_path: pytest.TempPathFactory
) -> None:
    """reload() picks up a new ticker added to the universe file."""
    (tmp_path / "data" / "ticker_universe.txt").write_text(  # type: ignore[operator]
        "GME\nTSLA\nNEWTKR\n", encoding="utf-8"
    )
    disambiguator.reload()
    assert disambiguator.is_valid("NEWTKR") is True


def test_reload_removes_old_ticker(
    disambiguator: TickerDisambiguator, tmp_path: pytest.TempPathFactory
) -> None:
    """reload() removes a ticker that is no longer in the universe file."""
    assert disambiguator.is_valid("GME") is True  # confirm it was valid before
    (tmp_path / "data" / "ticker_universe.txt").write_text(  # type: ignore[operator]
        "TSLA\n", encoding="utf-8"
    )
    disambiguator.reload()
    assert disambiguator.is_valid("GME") is False


def test_reload_updates_blocklist(
    disambiguator: TickerDisambiguator, tmp_path: pytest.TempPathFactory
) -> None:
    """reload() picks up a blocklist change (add TSLA to blocklist)."""
    assert disambiguator.is_valid("TSLA") is True  # initially valid
    (tmp_path / "data" / "false_positive_blocklist.txt").write_text(  # type: ignore[operator]
        "IT\nNOW\nAM\nTSLA\n", encoding="utf-8"
    )
    disambiguator.reload()
    assert disambiguator.is_valid("TSLA", explicit=False) is False


# ---------------------------------------------------------------------------
# Data file format
# ---------------------------------------------------------------------------


def test_comments_and_blank_lines_ignored(tmp_path: pytest.TempPathFactory) -> None:
    """Lines starting with # and blank lines are ignored in data files."""
    data_dir = tmp_path / "data"  # type: ignore[operator]
    data_dir.mkdir()  # type: ignore[union-attr]
    (data_dir / "false_positive_blocklist.txt").write_text(  # type: ignore[operator]
        "# comment\n\nIT\n\n# another comment\n", encoding="utf-8"
    )
    (data_dir / "ticker_universe.txt").write_text(  # type: ignore[operator]
        "# source info\n\nGME\nTSLA\n", encoding="utf-8"
    )
    d = TickerDisambiguator(data_dir=data_dir)  # type: ignore[arg-type]
    assert d.is_valid("GME") is True
    assert d.is_valid("IT", explicit=False) is False


def test_default_data_dir_used_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """When data_dir=None, the default path (next to module) is used."""
    # This exercises the default path code branch.
    # The production data files are present, so GME and TSLA should be valid.
    d = TickerDisambiguator()
    assert d.is_valid("GME") is True
    assert d.is_valid("TSLA") is True
    # Blocklisted common word should fail
    assert d.is_valid("IT", explicit=False) is False

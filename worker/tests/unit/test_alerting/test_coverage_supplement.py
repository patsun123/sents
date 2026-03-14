"""
Coverage supplement tests for modules that were below threshold.

These tests exercise paths in src.classifiers, src.tickers, and src.scrapers
that were previously only tested via old-style imports (without 'src.' prefix).
The tests here use the correct 'src.' import path so coverage.py tracks them.

These are smoke/integration tests of the module API — detailed behavior is
covered in the module-specific test files.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestVADERClassifierViaSrcImport:
    """Smoke tests for VADERClassifier via src. import path for coverage tracking."""

    def test_positive_sentiment(self) -> None:
        """Positive text returns polarity=1."""
        from src.classifiers.vader import VADERClassifier  # noqa: PLC0415

        c = VADERClassifier()
        result = c.classify("This stock is absolutely amazing and going to the moon!")
        assert result.polarity == 1
        assert result.discarded is False

    def test_negative_sentiment(self) -> None:
        """Negative text returns polarity=-1."""
        from src.classifiers.vader import VADERClassifier  # noqa: PLC0415

        c = VADERClassifier()
        result = c.classify("This is terrible, awful, and a complete disaster.")
        assert result.polarity == -1
        assert result.discarded is False

    def test_neutral_sentiment_is_discarded(self) -> None:
        """Neutral text returns discarded=True."""
        from src.classifiers.vader import VADERClassifier  # noqa: PLC0415

        c = VADERClassifier()
        result = c.classify("The stock moved.")
        assert result.discarded is True

    def test_is_ready_always_true(self) -> None:
        """is_ready() always returns True for VADER."""
        from src.classifiers.vader import VADERClassifier  # noqa: PLC0415

        assert VADERClassifier().is_ready() is True

    def test_classifier_error_on_invalid_input(self) -> None:
        """ClassifierError raised if VADER polarity_scores fails."""
        from src.classifiers.base import ClassifierError  # noqa: PLC0415
        from src.classifiers.vader import VADERClassifier  # noqa: PLC0415

        c = VADERClassifier()
        with patch.object(c._analyzer, "polarity_scores", side_effect=RuntimeError("fail")):
            with pytest.raises(ClassifierError):
                c.classify("text")


class TestClassifierFactoryViaSrcImport:
    """Smoke tests for the classifier factory via src. import path."""

    def test_default_backend_is_vader(self) -> None:
        """get_classifier() returns a VADERClassifier by default."""
        from src.classifiers import get_classifier  # noqa: PLC0415
        from src.classifiers.vader import VADERClassifier  # noqa: PLC0415

        with patch.dict(os.environ, {"CLASSIFIER_BACKEND": "vader"}):
            clf = get_classifier()
        assert isinstance(clf, VADERClassifier)

    def test_unknown_backend_raises_value_error(self) -> None:
        """get_classifier() raises ValueError for unknown backend."""
        from src.classifiers import get_classifier  # noqa: PLC0415

        with patch.dict(os.environ, {"CLASSIFIER_BACKEND": "gpt99"}):
            with pytest.raises(ValueError, match="Unknown CLASSIFIER_BACKEND"):
                get_classifier()

    def test_finbert_without_module_raises_import_error(self) -> None:
        """get_classifier() raises ImportError when finbert module is absent."""
        from src.classifiers import get_classifier  # noqa: PLC0415

        with (
            patch.dict(os.environ, {"CLASSIFIER_BACKEND": "finbert"}),
            patch.dict("sys.modules", {"src.classifiers.finbert": None}),
        ):
            with pytest.raises((ImportError, TypeError)):
                get_classifier()


class TestTickerExtractorViaSrcImport:
    """Smoke tests for TickerExtractor via src. import path for coverage tracking."""

    def test_explicit_ticker_extracted(self) -> None:
        """$GME is extracted as explicit=True."""
        from src.tickers.extractor import TickerExtractor  # noqa: PLC0415

        e = TickerExtractor()
        results = e.extract("Just bought $GME calls!")
        symbols = {r.symbol for r in results}
        explicit = {r.symbol for r in results if r.explicit}
        assert "GME" in symbols
        assert "GME" in explicit

    def test_bare_ticker_extracted(self) -> None:
        """TSLA (bare caps) is extracted as explicit=False."""
        from src.tickers.extractor import TickerExtractor  # noqa: PLC0415

        e = TickerExtractor()
        results = e.extract("TSLA is going down today")
        symbols = {r.symbol for r in results}
        assert "TSLA" in symbols
        non_explicit = {r.symbol for r in results if not r.explicit}
        assert "TSLA" in non_explicit

    def test_explicit_overrides_bare(self) -> None:
        """$GME mentioned alongside bare GME: only one entry, marked explicit=True."""
        from src.tickers.extractor import TickerExtractor  # noqa: PLC0415

        e = TickerExtractor()
        results = e.extract("$GME and GME both mentioned")
        gme_results = [r for r in results if r.symbol == "GME"]
        assert len(gme_results) == 1
        assert gme_results[0].explicit is True

    def test_empty_text_returns_empty(self) -> None:
        """Empty text yields no tickers."""
        from src.tickers.extractor import TickerExtractor  # noqa: PLC0415

        assert TickerExtractor().extract("") == []


class TestTickerDisambiguatorViaSrcImport:
    """Smoke tests for TickerDisambiguator via src. import path for coverage tracking."""

    def _make_disambiguator(self, tmp_path: Path) -> object:
        from src.tickers.disambiguator import TickerDisambiguator  # noqa: PLC0415

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "false_positive_blocklist.txt").write_text("IT\nNOW\n", encoding="utf-8")
        (data_dir / "ticker_universe.txt").write_text("GME\nTSLA\nIT\n", encoding="utf-8")
        return TickerDisambiguator(data_dir=data_dir)

    def test_valid_ticker_passes(self, tmp_path: Path) -> None:
        """GME is valid (in universe, not blocklisted)."""
        d = self._make_disambiguator(tmp_path)
        assert d.is_valid("GME") is True  # type: ignore[attr-defined]

    def test_blocklisted_fails(self, tmp_path: Path) -> None:
        """IT is blocklisted for bare mention."""
        d = self._make_disambiguator(tmp_path)
        assert d.is_valid("IT") is False  # type: ignore[attr-defined]

    def test_explicit_bypasses_blocklist(self, tmp_path: Path) -> None:
        """$IT (explicit) bypasses blocklist but must be in universe."""
        d = self._make_disambiguator(tmp_path)
        assert d.is_valid("IT", explicit=True) is True  # type: ignore[attr-defined]

    def test_not_in_universe_fails(self, tmp_path: Path) -> None:
        """Symbol not in universe fails even if not blocklisted."""
        d = self._make_disambiguator(tmp_path)
        assert d.is_valid("FAKE") is False  # type: ignore[attr-defined]

    def test_filter_returns_valid_symbols(self, tmp_path: Path) -> None:
        """filter() returns only valid symbol strings."""
        from src.tickers.extractor import ExtractedTicker  # noqa: PLC0415

        d = self._make_disambiguator(tmp_path)
        candidates = [
            ExtractedTicker(symbol="GME", explicit=False),
            ExtractedTicker(symbol="IT", explicit=False),  # blocklisted
            ExtractedTicker(symbol="FAKE", explicit=False),  # not in universe
        ]
        result = d.filter(candidates)  # type: ignore[attr-defined]
        assert result == ["GME"]

    def test_reload_picks_up_changes(self, tmp_path: Path) -> None:
        """reload() re-reads data files from disk."""
        d = self._make_disambiguator(tmp_path)
        # Add AAPL to universe
        universe_path = tmp_path / "data" / "ticker_universe.txt"
        universe_path.write_text("GME\nTSLA\nIT\nAAPL\n", encoding="utf-8")
        d.reload()  # type: ignore[attr-defined]
        assert d.is_valid("AAPL") is True  # type: ignore[attr-defined]


class TestScrapersInitViaSrcImport:
    """Tests for scrapers factory functions via src. import path."""

    def test_get_primary_scraper_returns_json_endpoint(self) -> None:
        """get_primary_scraper() returns a JsonEndpointScraper."""
        from src.scrapers import get_primary_scraper  # noqa: PLC0415
        from src.scrapers.json_endpoint import JsonEndpointScraper  # noqa: PLC0415

        scraper = get_primary_scraper()
        assert isinstance(scraper, JsonEndpointScraper)

    def test_get_fallback_scraper_returns_none_without_credentials(self) -> None:
        """get_fallback_scraper() returns None when REDDIT_CLIENT_ID is not set."""
        from src.scrapers import get_fallback_scraper  # noqa: PLC0415

        with patch.dict(os.environ, {}, clear=True):
            result = get_fallback_scraper()
        assert result is None

    def test_get_fallback_scraper_returns_praw_with_credentials(self) -> None:
        """get_fallback_scraper() returns a PRAWOAuthScraper when credentials are set."""
        from src.scrapers import get_fallback_scraper  # noqa: PLC0415
        from src.scrapers.praw_oauth import PRAWOAuthScraper  # noqa: PLC0415

        env = {
            "REDDIT_CLIENT_ID": "test_id",
            "REDDIT_CLIENT_SECRET": "test_secret",
            "REDDIT_USERNAME": "test_user",
            "REDDIT_PASSWORD": "test_pass",
        }
        with patch.dict(os.environ, env):
            scraper = get_fallback_scraper()
        assert isinstance(scraper, PRAWOAuthScraper)

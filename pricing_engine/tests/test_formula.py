"""Unit tests for the pricing formula engine.

Tests are deterministic and require no external dependencies.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from pricing_engine.formula.engine import (
    FormulaEngine,
    FormulaParams,
    SentimentSnapshot,
)


def _snap(ticker: str, agg_score: float, count: int, upvote: float = 10.0) -> SentimentSnapshot:
    return SentimentSnapshot(
        ticker=ticker,
        window_end=datetime.now(timezone.utc),
        agg_score=agg_score,
        mention_count=count,
        avg_upvote_score=upvote,
    )


REAL_PRICE = Decimal("100.00")
DEFAULT_PARAMS = FormulaParams()


class TestBootstrap:
    """When prev_snapshot is None, sentiment_price equals real_price."""

    def test_bootstrap_returns_real_price(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        result = engine.compute(_snap("TSLA", 0.5, 10), prev_snapshot=None, real_price=REAL_PRICE)
        assert result.sentiment_price == REAL_PRICE
        assert result.sentiment_delta == Decimal("0")

    def test_bootstrap_logs_ticker(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        result = engine.compute(_snap("NVDA", 0.8, 5), prev_snapshot=None, real_price=REAL_PRICE)
        assert result.ticker == "NVDA"


class TestMinMentions:
    """Tickers below min_mentions threshold return real_price unchanged."""

    def test_below_min_mentions(self) -> None:
        params = FormulaParams(min_mentions=5)
        engine = FormulaEngine(params)
        prev = _snap("TSLA", 0.0, 10)
        curr = _snap("TSLA", 0.5, 2)  # only 2 mentions, below threshold of 5
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        assert result.sentiment_price == REAL_PRICE

    def test_at_min_mentions_computes(self) -> None:
        params = FormulaParams(min_mentions=3)
        engine = FormulaEngine(params)
        prev = _snap("TSLA", 0.0, 10)
        curr = _snap("TSLA", 0.3, 3)  # exactly 3 mentions = threshold
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        # Should compute a non-trivial delta since score went from 0 to 0.3
        assert result.sentiment_price != REAL_PRICE


class TestDeltaDirection:
    """Positive score delta → sentiment_price > real_price and vice versa."""

    def test_positive_delta_increases_price(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        prev = _snap("TSLA", 0.0, 20)
        curr = _snap("TSLA", 0.5, 20)  # positive swing
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        assert result.sentiment_price > REAL_PRICE
        assert result.sentiment_delta > Decimal("0")

    def test_negative_delta_decreases_price(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        prev = _snap("TSLA", 0.5, 20)
        curr = _snap("TSLA", -0.3, 20)  # negative swing
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        assert result.sentiment_price < REAL_PRICE
        assert result.sentiment_delta < Decimal("0")

    def test_zero_delta_returns_real_price(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        prev = _snap("TSLA", 0.4, 20)
        curr = _snap("TSLA", 0.4, 20)  # no change
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        assert result.sentiment_price == REAL_PRICE


class TestMaxDeltaClamp:
    """Extreme score swings are clamped to max_delta_pct of real_price."""

    def test_extreme_positive_clamped(self) -> None:
        params = FormulaParams(sensitivity=100.0, max_delta_pct=0.05)
        engine = FormulaEngine(params)
        prev = _snap("TSLA", -1.0, 100)
        curr = _snap("TSLA", 1.0, 100)  # extreme swing
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        max_allowed = REAL_PRICE * Decimal("0.05")
        assert result.sentiment_delta <= max_allowed

    def test_extreme_negative_clamped(self) -> None:
        params = FormulaParams(sensitivity=100.0, max_delta_pct=0.05)
        engine = FormulaEngine(params)
        prev = _snap("TSLA", 1.0, 100)
        curr = _snap("TSLA", -1.0, 100)
        result = engine.compute(curr, prev_snapshot=prev, real_price=REAL_PRICE)
        max_allowed = REAL_PRICE * Decimal("0.05")
        assert result.sentiment_delta >= -max_allowed


class TestTimeShift:
    """Verifies compute_batch returns results for all provided snapshots."""

    def test_batch_processes_multiple_tickers(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        snaps = [
            _snap("TSLA", 0.3, 20),
            _snap("NVDA", -0.2, 15),
            _snap("GME", 0.7, 50),
        ]
        prev_map = {
            "TSLA": _snap("TSLA", 0.0, 20),
            "NVDA": _snap("NVDA", 0.1, 15),
            "GME": _snap("GME", 0.5, 50),
        }
        real_prices = {
            "TSLA": Decimal("250.00"),
            "NVDA": Decimal("800.00"),
            "GME": Decimal("15.00"),
        }
        results = engine.compute_batch(snaps, prev_map, real_prices)
        assert len(results) == 3
        tickers = {r.ticker for r in results}
        assert tickers == {"TSLA", "NVDA", "GME"}

    def test_batch_skips_missing_real_price(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS)
        snaps = [_snap("TSLA", 0.3, 20), _snap("UNKNOWN", 0.5, 10)]
        prev_map = {"TSLA": _snap("TSLA", 0.0, 20)}
        real_prices = {"TSLA": Decimal("250.00")}  # UNKNOWN has no real price
        results = engine.compute_batch(snaps, prev_map, real_prices)
        assert len(results) == 1
        assert results[0].ticker == "TSLA"


class TestVolumeScaling:
    """Different volume_scaling_function values produce different weights."""

    def test_log_vs_linear_produces_different_results(self) -> None:
        log_params = FormulaParams(volume_scaling_function="log", sensitivity=2.0)
        lin_params = FormulaParams(volume_scaling_function="linear", sensitivity=2.0)

        log_engine = FormulaEngine(log_params)
        lin_engine = FormulaEngine(lin_params)

        prev = _snap("TSLA", 0.0, 50)
        curr = _snap("TSLA", 0.5, 50)

        log_result = log_engine.compute(curr, prev, REAL_PRICE)
        lin_result = lin_engine.compute(curr, prev, REAL_PRICE)

        # Linear scaling with 50 mentions should amplify more than log
        assert lin_result.sentiment_delta != log_result.sentiment_delta


class TestParametersVersion:
    """parameters_version is stored in the result."""

    def test_version_label_propagated(self) -> None:
        engine = FormulaEngine(DEFAULT_PARAMS, parameters_version="v42")
        prev = _snap("TSLA", 0.0, 10)
        curr = _snap("TSLA", 0.3, 10)
        result = engine.compute(curr, prev, REAL_PRICE)
        assert result.parameters_version == "v42"

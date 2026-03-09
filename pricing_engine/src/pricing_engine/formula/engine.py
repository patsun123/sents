"""Sentiment price calculation engine.

Formula overview
----------------
sentiment_price(t) = real_price(t) + delta(t)

where:

    delta(t) = clamp(
        weighted_score_delta * sensitivity * upvote_multiplier * volume_weight,
        -max_delta_pct * real_price,
        +max_delta_pct * real_price,
    )

    weighted_score_delta = agg_score(t) - agg_score(t-1)
    volume_weight        = volume_scaling(mention_count) * volume_multiplier

Volume scaling functions:
  "log"    -> log(1 + count)         (default, dampens viral spikes)
  "sqrt"   -> sqrt(count)
  "linear" -> count / VOLUME_NORM    (amplifies volume)

VOLUME_NORM = 100  (normalisation constant for linear mode)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

_VOLUME_NORM = 100.0

VolumeFunction = Literal["log", "sqrt", "linear"]


@dataclass(frozen=True)
class FormulaParams:
    sensitivity: float = 1.0
    max_delta_pct: float = 0.10
    upvote_weight_multiplier: float = 1.0
    volume_scaling_function: VolumeFunction = "log"
    volume_weight_multiplier: float = 1.0
    min_mentions: int = 3

    @classmethod
    def from_dict(cls, d: dict) -> "FormulaParams":
        return cls(
            sensitivity=float(d.get("sensitivity", 1.0)),
            max_delta_pct=float(d.get("max_delta_pct", 0.10)),
            upvote_weight_multiplier=float(d.get("upvote_weight_multiplier", 1.0)),
            volume_scaling_function=d.get("volume_scaling_function", "log"),  # type: ignore[arg-type]
            volume_weight_multiplier=float(d.get("volume_weight_multiplier", 1.0)),
            min_mentions=int(d.get("min_mentions", 3)),
        )


@dataclass
class SentimentSnapshot:
    """A single aggregated sentiment window for one ticker."""
    ticker: str
    window_end: object  # datetime
    agg_score: float           # e.g., avg compound sentiment [-1, 1]
    mention_count: int         # number of posts/comments in window
    avg_upvote_score: float    # average Reddit upvote score in window


@dataclass
class PriceResult:
    ticker: str
    sentiment_price: Decimal
    real_price: Decimal
    sentiment_delta: Decimal
    parameters_version: str


class FormulaEngine:
    """Computes sentiment_price from snapshot data and formula parameters."""

    def __init__(self, params: FormulaParams, parameters_version: str = "default") -> None:
        self._params = params
        self._version = parameters_version

    def _volume_weight(self, mention_count: int) -> float:
        """Convert mention count to a volume weight via the configured scaling function."""
        count = max(0.0, float(mention_count))
        fn = self._params.volume_scaling_function
        if fn == "log":
            raw = math.log1p(count)
        elif fn == "sqrt":
            raw = math.sqrt(count)
        else:  # linear
            raw = count / _VOLUME_NORM
        return raw * self._params.volume_weight_multiplier

    def compute(
        self,
        snapshot: SentimentSnapshot,
        prev_snapshot: SentimentSnapshot | None,
        real_price: Decimal,
    ) -> PriceResult:
        """Compute sentiment_price for a single snapshot.

        Args:
            snapshot: Current sentiment window.
            prev_snapshot: Previous window (None on first boot -> bootstrap to real_price).
            real_price: Current real market price for this ticker.
        """
        p = self._params

        # Skip tickers with insufficient mention volume
        if snapshot.mention_count < p.min_mentions:
            return PriceResult(
                ticker=snapshot.ticker,
                sentiment_price=real_price,
                real_price=real_price,
                sentiment_delta=Decimal("0"),
                parameters_version=self._version,
            )

        # Bootstrap: if no previous snapshot, sentiment_price = real_price
        if prev_snapshot is None:
            return PriceResult(
                ticker=snapshot.ticker,
                sentiment_price=real_price,
                real_price=real_price,
                sentiment_delta=Decimal("0"),
                parameters_version=self._version,
            )

        # Score delta (clamped to [-2, 2] before further weighting)
        raw_delta = max(-2.0, min(2.0, snapshot.agg_score - prev_snapshot.agg_score))

        # Volume weight based on current window's mention count
        vol_w = self._volume_weight(snapshot.mention_count)

        # Upvote engagement multiplier — high-karma posts get more weight
        upvote_mult = 1.0 + math.log1p(max(0.0, snapshot.avg_upvote_score)) * (
            p.upvote_weight_multiplier - 1.0
        ) if p.upvote_weight_multiplier != 1.0 else 1.0

        # Raw delta in price units
        price_delta = raw_delta * vol_w * upvote_mult * p.sensitivity

        # Clamp to max_delta_pct of real_price
        max_abs = float(real_price) * p.max_delta_pct
        price_delta = max(-max_abs, min(max_abs, price_delta))

        sentiment_price = Decimal(str(round(float(real_price) + price_delta, 4)))
        delta = sentiment_price - real_price

        return PriceResult(
            ticker=snapshot.ticker,
            sentiment_price=sentiment_price,
            real_price=real_price,
            sentiment_delta=delta,
            parameters_version=self._version,
        )

    def compute_batch(
        self,
        snapshots: list[SentimentSnapshot],
        prev_snapshots: dict[str, SentimentSnapshot],
        real_prices: dict[str, Decimal],
    ) -> list[PriceResult]:
        """Compute sentiment prices for all tickers in one batch."""
        results = []
        for snap in snapshots:
            real_p = real_prices.get(snap.ticker)
            if real_p is None:
                continue  # Skip tickers without a real price
            prev = prev_snapshots.get(snap.ticker)
            result = self.compute(snap, prev, real_p)
            results.append(result)
        return results

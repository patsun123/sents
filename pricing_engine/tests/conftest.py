"""Shared fixtures for pricing engine tests."""
import pytest
from pricing_engine.formula.engine import FormulaParams, SentimentSnapshot
from datetime import datetime, timezone


@pytest.fixture
def default_params():
    return FormulaParams.from_dict({})


@pytest.fixture
def sample_snapshot():
    return SentimentSnapshot(
        ticker="TSLA",
        window_end=datetime.now(timezone.utc),
        agg_score=0.5,
        mention_count=10,
        avg_upvote_score=100.0,
    )

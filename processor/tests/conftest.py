"""Shared fixtures for processor tests."""
import pytest


@pytest.fixture
def sample_texts():
    """Sample financial texts for sentiment analysis."""
    return [
        "TSLA is going to the moon! Diamond hands forever!",
        "This stock is terrible, going to zero.",
        "Neutral market conditions, holding steady.",
    ]

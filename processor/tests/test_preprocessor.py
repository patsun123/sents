"""Tests for the financial text preprocessor."""
from processor.text.preprocessor import (
    normalize_cashtags,
    expand_slang,
    map_emojis,
    normalize_whitespace,
    preprocess,
)


def test_normalize_cashtags():
    assert normalize_cashtags("Buy $AAPL now") == "Buy AAPL now"
    assert normalize_cashtags("$TSLA and $GME") == "TSLA and GME"
    assert normalize_cashtags("$50 off") == "$50 off"  # numbers not touched


def test_expand_slang():
    result = expand_slang("TSLA to the moon, diamond hands!")
    assert "strongly positive rising" in result
    assert "holding strong positive conviction" in result


def test_expand_slang_case_insensitive():
    result = expand_slang("HODL and YOLO")
    assert "hold strong positive" in result
    assert "high risk investment all in" in result


def test_map_emojis():
    result = map_emojis("TSLA \U0001f680\U0001f48e")
    assert "(positive_sentiment rising)" in result
    assert "(positive_sentiment strong)" in result


def test_normalize_whitespace():
    assert normalize_whitespace("  hello   world  \n\n  test  ") == "hello world test"


def test_preprocess_full_pipeline():
    text = "$TSLA to the moon \U0001f680  bullish af"
    result = preprocess(text)
    assert "TSLA" in result  # cashtag normalized
    assert "(positive_sentiment rising)" in result  # emoji mapped
    assert "very bullish strongly positive" in result  # slang expanded

"""Financial text preprocessor — normalizes Reddit text before sentiment analysis."""
from __future__ import annotations

import re

from processor.text.emoji_map import EMOJI_SENTIMENT
from processor.text.slang_dict import FINANCIAL_SLANG


def normalize_cashtags(text: str) -> str:
    """Strip $ prefix from cashtags like $AAPL -> AAPL."""
    return re.sub(r"\$([A-Za-z]{1,6})\b", r"\1", text)


def expand_slang(text: str) -> str:
    """Case-insensitive whole-word replacement of financial slang."""
    for slang, replacement in FINANCIAL_SLANG.items():
        # Whole-word boundary match, case-insensitive
        pattern = re.compile(r"\b" + re.escape(slang) + r"\b", re.IGNORECASE)
        text = pattern.sub(replacement, text)
    return text


def map_emojis(text: str) -> str:
    """Replace emojis with their sentiment text."""
    for emoji, sentiment_text in EMOJI_SENTIMENT.items():
        text = text.replace(emoji, f" {sentiment_text} ")
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/newlines into single space."""
    return re.sub(r"\s+", " ", text).strip()


def preprocess(text: str) -> str:
    """Full preprocessing pipeline for financial text."""
    text = normalize_cashtags(text)
    text = expand_slang(text)
    text = map_emojis(text)
    text = normalize_whitespace(text)
    return text

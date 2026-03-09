"""FinBERT sentiment analysis backend (lazy-loaded)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_pipeline: Optional[object] = None
_model_name: str = "ProsusAI/finbert"


def load_model(model_name: str = "ProsusAI/finbert") -> None:
    """Load FinBERT model. Call once at startup."""
    global _pipeline, _model_name
    _model_name = model_name
    logger.info("Loading FinBERT model: %s", model_name)
    from transformers import pipeline  # type: ignore[import]
    _pipeline = pipeline(
        "text-classification",
        model=model_name,
        tokenizer=model_name,
        truncation=True,
        max_length=512,
    )
    logger.info("FinBERT loaded successfully")


@dataclass
class FinBERTResult:
    compound: float      # positive=1.0, negative=-1.0, neutral=0.0
    positive: float
    negative: float
    neutral: float
    raw_scores: dict


def _map_label(label: str, score: float) -> tuple[float, float, float, float]:
    """Map FinBERT label+score to (compound, pos, neg, neu)."""
    label = label.lower()
    if label == "positive":
        return score, score, 0.0, 1.0 - score
    elif label == "negative":
        return -score, 0.0, score, 1.0 - score
    else:  # neutral
        return 0.0, 0.0, 0.0, score


def analyze(text: str) -> FinBERTResult:
    if _pipeline is None:
        raise RuntimeError("FinBERT model not loaded. Call load_model() first.")
    result = _pipeline(text[:512])  # type: ignore[call-overload]
    top = result[0] if isinstance(result, list) else result
    label = top["label"]
    score = float(top["score"])
    compound, pos, neg, neu = _map_label(label, score)
    return FinBERTResult(
        compound=compound,
        positive=pos,
        negative=neg,
        neutral=neu,
        raw_scores={"label": label, "score": score},
    )


def analyze_batch(texts: list[str], batch_size: int = 16) -> list[FinBERTResult]:
    if _pipeline is None:
        raise RuntimeError("FinBERT model not loaded. Call load_model() first.")
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        truncated = [t[:512] for t in batch]
        preds = _pipeline(truncated)  # type: ignore[call-overload]
        for pred in preds:
            label = pred["label"]
            score = float(pred["score"])
            compound, pos, neg, neu = _map_label(label, score)
            results.append(FinBERTResult(
                compound=compound, positive=pos, negative=neg, neutral=neu,
                raw_scores={"label": label, "score": score},
            ))
    return results

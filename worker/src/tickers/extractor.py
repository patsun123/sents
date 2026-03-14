"""
TickerExtractor: detect stock ticker symbol candidates in text.

Two extraction modes:
- Explicit: $TICKER format (strong signal, bypasses disambiguation)
- Bare: ALL-CAPS word matching 2-5 characters (weak signal, requires disambiguation)

Text passed to extract() is processed in-memory only and is never stored or logged.
"""

import re
from dataclasses import dataclass

_EXPLICIT_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")
_BARE_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")


@dataclass(frozen=True)
class ExtractedTicker:
    """A candidate ticker found in text.

    Attributes:
        symbol: Uppercase ticker symbol, e.g. ``"GME"``.
        explicit: ``True`` if found as ``$GME``; ``False`` if bare ALL-CAPS.
    """

    symbol: str
    explicit: bool


class TickerExtractor:
    """Extract candidate ticker symbols from raw comment text.

    Does not filter false positives — that is the Disambiguator's job.

    Example::

        extractor = TickerExtractor()
        candidates = extractor.extract("$GME to the moon! Bought TSLA too.")
        # [ExtractedTicker('GME', explicit=True), ExtractedTicker('TSLA', explicit=False)]
    """

    def extract(self, text: str) -> list[ExtractedTicker]:
        """Extract all candidate ticker symbols from text.

        Scans the text for both explicit ``$TICKER`` mentions and bare
        ALL-CAPS words (2–5 characters).  A symbol found as both explicit
        and bare is returned **once**, marked as ``explicit=True``.

        Single-letter bare tokens (``I``, ``A``, ``U``) are excluded by the
        bare pattern (minimum 2 characters).  However ``$A`` as an explicit
        dollar-sign mention *is* included because the user clearly intended it.

        Args:
            text: Comment body.  Processed in-memory; never persisted or logged.

        Returns:
            Deduplicated list of :class:`ExtractedTicker` instances.  Order is
            not guaranteed.
        """
        explicit: set[str] = {m.group(1) for m in _EXPLICIT_PATTERN.finditer(text)}
        bare: set[str] = {m.group(1) for m in _BARE_PATTERN.finditer(text)}

        results: dict[str, ExtractedTicker] = {}
        for symbol in explicit:
            results[symbol] = ExtractedTicker(symbol=symbol, explicit=True)
        for symbol in bare - explicit:  # only bare if not already explicit
            results[symbol] = ExtractedTicker(symbol=symbol, explicit=False)

        return list(results.values())

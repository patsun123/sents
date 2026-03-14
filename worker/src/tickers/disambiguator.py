"""
TickerDisambiguator: filter ticker candidates to confirmed real tickers.

Stage 1: False-positive blocklist (common English words that happen to be valid
         ticker symbols, e.g. ``IT``, ``NOW``, ``ARE``).
Stage 2: NYSE/NASDAQ universe validation (real listed tickers only).

Explicit ``$TICKER`` mentions bypass Stage 1 (blocklist) but still require
Stage 2 (universe) validation.  This preserves strong user-intent signals such
as ``$IT`` (Gartner, Inc.) while still silently ignoring completely made-up
symbols.

Both data files are loaded at instantiation and can be hot-reloaded via
:meth:`reload` without restarting the worker.
"""

from __future__ import annotations

from pathlib import Path

from .extractor import ExtractedTicker


class TickerDisambiguator:
    """Validate extracted tickers against a blocklist and a ticker universe.

    Both data files are plain-text, one symbol per line.  Lines starting with
    ``#`` and blank lines are ignored so comments and blank separators are
    allowed.

    Args:
        data_dir: Directory containing ``false_positive_blocklist.txt`` and
            ``ticker_universe.txt``.  Defaults to the ``data/`` sub-directory
            next to this module file.

    Example::

        disambiguator = TickerDisambiguator()
        disambiguator.is_valid("GME")            # True
        disambiguator.is_valid("IT")             # False (blocklisted bare)
        disambiguator.is_valid("IT", explicit=True)  # True ($IT bypasses blocklist)
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir: Path = data_dir or Path(__file__).parent / "data"
        self._blocklist: frozenset[str] = frozenset()
        self._universe: frozenset[str] = frozenset()
        self.reload()

    def reload(self) -> None:
        """Reload blocklist and universe from disk.

        Call this to pick up edits to the data files without restarting the
        worker process.  Thread-safety note: attribute assignment is atomic in
        CPython, so a concurrent :meth:`is_valid` call during reload will see
        either the old or new set — never a partial set.
        """
        blocklist_path = self._data_dir / "false_positive_blocklist.txt"
        universe_path = self._data_dir / "ticker_universe.txt"

        self._blocklist = frozenset(
            line.strip().upper()
            for line in blocklist_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
        self._universe = frozenset(
            line.strip().upper()
            for line in universe_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )

    def is_valid(self, symbol: str, *, explicit: bool = False) -> bool:
        """Return ``True`` if *symbol* is a valid, unambiguous ticker.

        Args:
            symbol: Uppercase ticker candidate.
            explicit: ``True`` if the symbol was found as a ``$TICKER``
                dollar-sign mention.  Explicit mentions bypass the blocklist
                (Stage 1) but still require universe membership (Stage 2).

        Returns:
            ``True`` if the symbol should be included in sentiment scoring.
        """
        upper = symbol.upper()
        if not explicit and upper in self._blocklist:
            return False
        return upper in self._universe

    def filter(self, candidates: list[ExtractedTicker]) -> list[str]:
        """Filter a list of :class:`~tickers.extractor.ExtractedTicker` to valid symbols.

        Args:
            candidates: Extracted ticker candidates from
                :class:`~tickers.extractor.TickerExtractor`.

        Returns:
            Deduplicated list of uppercase symbol strings that passed both
            the blocklist and universe checks.
        """
        return [
            c.symbol
            for c in candidates
            if self.is_valid(c.symbol, explicit=c.explicit)
        ]

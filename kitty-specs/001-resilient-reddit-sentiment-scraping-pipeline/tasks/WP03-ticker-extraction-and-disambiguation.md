---
work_package_id: WP03
title: Ticker Extraction & Disambiguation
lane: "doing"
dependencies: [WP01]
base_branch: 001-resilient-reddit-sentiment-scraping-pipeline-WP01
base_commit: 7e38de562c61693212607d5f4fb1061125053261
created_at: '2026-03-13T14:53:35.203237+00:00'
subtasks:
- T012
- T013
- T014
- T015
- T016
phase: Phase 1 - Core Components
assignee: ''
agent: "claude-sonnet-4-6"
shell_pid: "23988"
review_status: ''
reviewed_by: ''
history:
- timestamp: '2026-03-09T19:41:43Z'
  lane: planned
  agent: system
  shell_pid: ''
  action: Prompt generated via /spec-kitty.tasks
requirement_refs:
- FR-002
- FR-005
---

# Work Package Prompt: WP03 - Ticker Extraction & Disambiguation

## Objectives & Success Criteria

- `TickerExtractor` reliably detects `$GME` style explicit mentions and bare ALL-CAPS tickers
- `TickerDisambiguator` rejects common English words (`IT`, `NOW`, `ARE`) while accepting real tickers (`TSLA`, `GME`)
- Explicit `$TICKER` mentions bypass the blocklist (strong intent signal)
- Single-letter bare tickers are excluded (too noisy); `$A` explicit form is accepted
- Blocklist and ticker universe files are loaded at startup and hot-reloadable
- Unit tests cover WSB-style text, edge cases, and false-positive scenarios
- All tests pass; `ruff`, `mypy`, `bandit` clean

## Context & Constraints

- **Spec**: FR-002 — dynamic ticker discovery with disambiguation
- **Research**: `research.md` R-004 — ticker extraction patterns and disambiguation approach
- **Data model**: `data-model.md` — Disambiguation Reference section
- **WP03 is parallel to WP02, WP04, WP05** — no dependencies between them, only on WP01
- **No external API calls** — all disambiguation is local (blocklist + universe file)

**Implementation command**: `spec-kitty implement WP03 --base WP01`

---

## Subtasks & Detailed Guidance

### Subtask T012 - Implement TickerExtractor

**Purpose**: Extract candidate ticker symbols from raw comment text using regex patterns. Returns a deduplicated list of candidate symbols. Disambiguation happens in T013.

**Steps**:
1. Create `worker/src/tickers/extractor.py`:

```python
"""
TickerExtractor: detect stock ticker symbol candidates in text.

Two extraction modes:
- Explicit: $TICKER format (strong signal, bypasses disambiguation)
- Bare: ALL-CAPS word matching 2-5 characters (weak signal, requires disambiguation)
"""
import re
from dataclasses import dataclass


_EXPLICIT_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")
_BARE_PATTERN = re.compile(r"\b([A-Z]{2,5})\b")


@dataclass(frozen=True)
class ExtractedTicker:
    """A candidate ticker found in text."""
    symbol: str        # Uppercase, e.g. "GME"
    explicit: bool     # True if found as $GME; False if bare ALL-CAPS


class TickerExtractor:
    """
    Extracts candidate ticker symbols from text.

    Does not filter false positives — that is the Disambiguator's job.
    """

    def extract(self, text: str) -> list[ExtractedTicker]:
        """
        Extract all candidate ticker symbols from text.

        Args:
            text: Comment body (never persisted).

        Returns:
            Deduplicated list of ExtractedTicker instances.
            A symbol found as both explicit and bare is returned once, as explicit=True.
        """
        explicit = {m.group(1) for m in _EXPLICIT_PATTERN.finditer(text)}
        bare = {m.group(1) for m in _BARE_PATTERN.finditer(text)}

        results: dict[str, ExtractedTicker] = {}
        for symbol in explicit:
            results[symbol] = ExtractedTicker(symbol=symbol, explicit=True)
        for symbol in bare - explicit:  # only bare if not already explicit
            results[symbol] = ExtractedTicker(symbol=symbol, explicit=False)

        return list(results.values())
```

**Files**: `worker/src/tickers/extractor.py`

**Notes**:
- Bare pattern minimum 2 chars to exclude single-letter noise (`I`, `A`, `U`)
- Text is passed in-memory only and must not be stored or logged

---

### Subtask T013 - Implement TickerDisambiguator

**Purpose**: Filter extracted candidates to only real, non-ambiguous ticker symbols. Two-stage filter: blocklist (common words) then universe validation (real tickers only).

**Steps**:
1. Create `worker/src/tickers/disambiguator.py`:

```python
"""
TickerDisambiguator: filter ticker candidates to confirmed real tickers.

Stage 1: False-positive blocklist (common English words)
Stage 2: NYSE/NASDAQ universe validation (real listed tickers)

Explicit $TICKER mentions bypass Stage 1 (blocklist) but still
require Stage 2 (universe) validation.
"""
import importlib.resources
from pathlib import Path


class TickerDisambiguator:
    """
    Validates extracted tickers against blocklist and ticker universe.

    Both data files are loaded at instantiation. Call reload() to
    refresh from disk without restarting.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or Path(__file__).parent / "data"
        self.reload()

    def reload(self) -> None:
        """Reload blocklist and universe from disk (no restart required)."""
        blocklist_path = self._data_dir / "false_positive_blocklist.txt"
        universe_path = self._data_dir / "ticker_universe.txt"

        self._blocklist: frozenset[str] = frozenset(
            line.strip().upper()
            for line in blocklist_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        )
        self._universe: frozenset[str] = frozenset(
            line.strip().upper()
            for line in universe_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        )

    def is_valid(self, symbol: str, explicit: bool = False) -> bool:
        """
        Return True if symbol is a valid, unambiguous ticker.

        Args:
            symbol: Uppercase ticker candidate.
            explicit: True if found as $TICKER (bypasses blocklist check).

        Returns:
            True if the symbol should be scored.
        """
        upper = symbol.upper()
        if not explicit and upper in self._blocklist:
            return False
        return upper in self._universe

    def filter(self, candidates: list) -> list[str]:
        """
        Filter a list of ExtractedTicker to valid symbols only.

        Returns list of uppercase symbol strings.
        """
        from .extractor import ExtractedTicker
        return [
            c.symbol for c in candidates
            if self.is_valid(c.symbol, explicit=c.explicit)
        ]
```

**Files**: `worker/src/tickers/disambiguator.py`

---

### Subtask T014 - Create blocklist and ticker universe data files

**Purpose**: The raw data that powers disambiguation. Both files are versioned in the repo so any change is tracked.

**Steps**:
1. Create `worker/src/tickers/data/false_positive_blocklist.txt`:
   ```
   # Common English words that are valid ticker symbols
   # Add one per line, uppercase
   # Last updated: 2026-03-09
   A
   I
   IT
   ON
   OR
   TO
   DO
   BE
   AT
   IN
   FOR
   ARE
   NOW
   GO
   HE
   SHE
   WE
   US
   AM
   AN
   AS
   BY
   OF
   SO
   UP
   ```

2. Create `worker/src/tickers/data/ticker_universe.txt`:
   - Download current NYSE + NASDAQ ticker list from SEC EDGAR Full-Text Search or similar free source
   - Format: one ticker per line, uppercase, no header
   - Store in the file — this will be ~10,000 lines
   - Document the source URL and date in a comment at the top of the file
   - Example (first few lines):
   ```
   # Source: SEC EDGAR company tickers (https://www.sec.gov/files/company_tickers.json)
   # Retrieved: 2026-03-09
   # Format: one ticker symbol per line, uppercase
   AAPL
   MSFT
   GOOGL
   AMZN
   TSLA
   GME
   AMC
   ...
   ```

3. Ensure both files are included in the Docker image (they are in `src/tickers/data/` which is copied by Dockerfile)

**Files**: `worker/src/tickers/data/false_positive_blocklist.txt`, `worker/src/tickers/data/ticker_universe.txt`

**Notes**:
- SEC EDGAR JSON: `https://www.sec.gov/files/company_tickers.json` — free, no auth, updated regularly
- Parse the JSON and extract ticker symbols: `data[key]["ticker"]` for each entry
- A small Python script to generate `ticker_universe.txt` from the SEC JSON is acceptable; document it in README

---

### Subtask T015 - Unit tests for TickerExtractor

**Purpose**: Verify extraction patterns handle all WSB-style text formats correctly.

**Steps**:
1. Create `worker/tests/unit/test_tickers/test_extractor.py`:

```python
import pytest
from worker.src.tickers.extractor import TickerExtractor, ExtractedTicker

@pytest.fixture
def extractor():
    return TickerExtractor()

def test_explicit_dollar_sign(extractor):
    results = extractor.extract("$GME to the moon!")
    assert any(t.symbol == "GME" and t.explicit for t in results)

def test_bare_caps(extractor):
    results = extractor.extract("Bought more TSLA today")
    assert any(t.symbol == "TSLA" and not t.explicit for t in results)

def test_explicit_overrides_bare(extractor):
    results = extractor.extract("$GME and GME are the same")
    gme = [t for t in results if t.symbol == "GME"]
    assert len(gme) == 1
    assert gme[0].explicit is True  # explicit takes priority

def test_single_letter_bare_excluded(extractor):
    results = extractor.extract("I bought A shares of U")
    symbols = [t.symbol for t in results]
    assert "I" not in symbols
    assert "A" not in symbols
    assert "U" not in symbols

def test_explicit_single_letter_included(extractor):
    results = extractor.extract("Bought more $A")
    assert any(t.symbol == "A" and t.explicit for t in results)

def test_mixed_case_not_extracted(extractor):
    results = extractor.extract("Tesla is great")  # not ALL-CAPS
    symbols = [t.symbol for t in results]
    assert "TESLA" not in symbols

def test_empty_text(extractor):
    assert extractor.extract("") == []

def test_no_tickers(extractor):
    results = extractor.extract("no stock mentions here at all")
    assert results == []
```

**Files**: `worker/tests/unit/test_tickers/test_extractor.py`

---

### Subtask T016 - Unit tests for TickerDisambiguator

**Purpose**: Verify disambiguation correctly rejects common words and accepts real tickers, with correct explicit bypass behaviour.

**Steps**:
1. Create `worker/tests/unit/test_tickers/test_disambiguator.py` using temporary data files:

```python
import pytest
from pathlib import Path
from worker.src.tickers.disambiguator import TickerDisambiguator
from worker.src.tickers.extractor import ExtractedTicker

@pytest.fixture
def disambiguator(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "false_positive_blocklist.txt").write_text("IT\nNOW\nAM\n")
    (data_dir / "ticker_universe.txt").write_text("GME\nTSLA\nAAPL\nIT\n")
    return TickerDisambiguator(data_dir=data_dir)

def test_real_ticker_passes(disambiguator):
    assert disambiguator.is_valid("GME") is True

def test_blocklisted_bare_fails(disambiguator):
    assert disambiguator.is_valid("IT", explicit=False) is False

def test_blocklisted_explicit_passes(disambiguator):
    # $IT explicit mention bypasses blocklist (user clearly meant the stock)
    assert disambiguator.is_valid("IT", explicit=True) is True

def test_not_in_universe_fails(disambiguator):
    # MADEUP is not in our ticker universe
    assert disambiguator.is_valid("MADEUP") is False

def test_filter_mixed_list(disambiguator):
    candidates = [
        ExtractedTicker("GME", explicit=True),
        ExtractedTicker("IT", explicit=False),   # blocklisted
        ExtractedTicker("MADEUP", explicit=False),  # not in universe
        ExtractedTicker("TSLA", explicit=False),
    ]
    result = disambiguator.filter(candidates)
    assert set(result) == {"GME", "TSLA"}

def test_reload(disambiguator, tmp_path):
    # Add a new ticker to universe and reload
    (tmp_path / "data" / "ticker_universe.txt").write_text("GME\nTSLA\nNEWTKR\n")
    disambiguator.reload()
    assert disambiguator.is_valid("NEWTKR") is True
```

**Files**: `worker/tests/unit/test_tickers/test_disambiguator.py`

---

## Test Strategy

- No external HTTP calls (all data is local files)
- Use `tmp_path` fixtures for isolated data files in disambiguator tests
- Edge cases: empty text, single-letter tickers, mixed explicit/bare for same symbol

## Risks & Mitigations

- **Ticker universe staleness**: Document quarterly refresh in README. A stale universe means new IPOs won't be detected, which is acceptable — better a false negative than scoring garbage.
- **Blocklist gaps**: Start conservatively (known bad words) and add based on production noise. Operator can edit the file without restart.
- **Performance**: Loading 10k ticker universe at startup is ~1ms. No performance risk.

## Review Guidance

- Verify `$IT` (explicit) returns valid but bare `IT` does not
- Verify single-letter bare tickers (`A`, `I`) are excluded
- Verify `reload()` picks up changes without restart
- Verify no comment text is referenced in any log call within the tickers module

## Activity Log

- 2026-03-09T19:41:43Z - system - lane=planned - Prompt created.
- 2026-03-13T14:53:35Z – claude-sonnet-4-6 – shell_pid=17964 – lane=doing – Assigned agent via workflow command
- 2026-03-13T15:00:22Z – claude-sonnet-4-6 – shell_pid=17964 – lane=for_review – Implementation complete: TickerExtractor (regex extraction, explicit/bare modes), TickerDisambiguator (two-stage blocklist+universe filter with hot-reload), data files (28-word blocklist, 10416-symbol SEC EDGAR universe), 34 unit tests at 100% coverage; ruff/mypy/bandit all clean
- 2026-03-13T15:01:12Z – claude-sonnet-4-6 – shell_pid=23988 – lane=doing – Started review via workflow command

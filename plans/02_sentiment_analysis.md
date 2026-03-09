# Sentiment Analysis — Atomic Implementation Plan

## Domain: NLP, Weighting Model, Pricing Formula, Configuration

---

### TASK-NLP01: Define the SentimentAnalyzer abstract interface
**Domain:** Sentiment Analysis
**Depends on:** none
**Description:** Create a Python abstract base class (or Protocol) defining the contract every sentiment backend must implement. Accepts raw text, returns a normalized score in [-1.0, 1.0] where -1.0 is maximally bearish and 1.0 is maximally bullish.
**Acceptance criteria:**
- Abstract class `SentimentAnalyzer` with single required method `analyze(text: str) -> float`
- Method is type-annotated with docstring specifying the [-1.0, 1.0] contract
- `NotImplementedError` raised if subclass fails to override
- Importable from a stable module path (e.g., `sentiment.base`)
- No dependency on VADER, TextBlob, or any ML library in this file

---

### TASK-NLP02: Implement `SentimentResult` data structure
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01
**Description:** Define a typed dataclass carrying all output from a sentiment analysis run. Fields: `text`, `score: float`, `direction: str` (bullish/bearish/neutral), `backend: str`, `raw_scores: dict`, `confidence: float | None`. Direction is derived automatically from score using configurable thresholds.
**Acceptance criteria:**
- `SentimentResult` dataclass with all required fields
- `direction` derived from `score` with configurable thresholds (`threshold_pos=0.05`, `threshold_neg=-0.05`)
- Serializable to plain dict via `.to_dict()`
- Unit tests confirm direction derivation edge cases (score at threshold, score exactly 0.0)

---

### TASK-NLP03: Build financial slang and emoji pre-processor
**Domain:** Sentiment Analysis
**Depends on:** none
**Description:** Text pre-processing step that runs before any NLP backend. Expands known financial slang into sentiment-bearing plain English phrases and converts common emojis to semantic equivalents so lexicon tools (VADER, TextBlob) can score them accurately.
**Acceptance criteria:**
- `FinancialTextPreprocessor` class with `preprocess(text: str) -> str` method
- Slang dictionary covers at minimum: "to the moon" → bullish phrase, "diamond hands" → holding bullish, "paper hands" → selling bearish, "tendies" → profits, "yolo" → high risk bullish, "apes" → retail investors buying, "short squeeze" → bullish price spike, "bagholder" → losing bearish position
- Emoji mapping covers at minimum: 🚀 🐻 🐂 💎 📉 📈 🩳 🔥 💀 with sentiment-bearing text equivalents
- Slang and emoji dictionaries loaded from external config file (YAML/JSON), not hardcoded
- Pre-processing is case-insensitive for slang matching
- Unit test confirms "🚀🚀🚀 to the moon!!" transforms into a VADER-scorable bullish string

---

### TASK-NLP04: Implement the VADER sentiment backend
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01, TASK-NLP03
**Description:** Concrete `SentimentAnalyzer` subclass using VADER (`vaderSentiment` library). Applies financial pre-processor before scoring. Maps VADER compound score directly to [-1.0, 1.0] output contract.
**Acceptance criteria:**
- `VaderSentimentAnalyzer` inherits from `SentimentAnalyzer` and implements `analyze(text: str) -> float`
- `FinancialTextPreprocessor` applied before scoring
- VADER compound score returned as-is
- `raw_scores` in `SentimentResult` includes all four VADER subscores: pos, neg, neu, compound
- `backend` field set to `"vader"`
- Unit tests: plain bullish text, plain bearish text, emoji-only input, slang-only input, empty string, negation case ("not good")

---

### TASK-NLP05: Implement the TextBlob sentiment backend
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01, TASK-NLP03
**Description:** Concrete `SentimentAnalyzer` subclass using TextBlob. Polarity [-1.0, 1.0] maps to output contract; subjectivity [0.0, 1.0] stored in `raw_scores`.
**Acceptance criteria:**
- `TextBlobSentimentAnalyzer` inherits from `SentimentAnalyzer` and implements `analyze(text: str) -> float`
- `FinancialTextPreprocessor` applied before scoring
- `raw_scores` includes `polarity` and `subjectivity`
- `backend` field set to `"textblob"`
- Unit tests mirror TASK-NLP04 test cases exactly (enables direct comparison)

---

### TASK-NLP06: Build manual labeling data schema and tooling
**Domain:** Sentiment Analysis
**Depends on:** none
**Description:** Define schema for the manually-labeled ground-truth dataset and provide a CLI script to load raw Reddit comments and record human labels, outputting structured records to JSONL for the validation framework.
**Acceptance criteria:**
- JSONL schema defined: `id`, `text`, `source` (subreddit), `label` (bullish/bearish/neutral), `labeled_by`, `labeled_at` (ISO 8601), `notes`
- Script `label_comments.py` presents each comment interactively with `b`/`e`/`n` keybindings
- Partial labeling sessions resumable (already-labeled IDs skipped)
- Schema documented in adjacent README
- 10 pre-labeled fixture records included for testing the validation framework

---

### TASK-NLP07: Collect and label 100+ real Reddit comments for ground truth
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP06
**Description:** Using TASK-NLP06 tooling, collect and manually label at least 100 real Reddit comments from r/wallstreetbets and r/stocks. Dataset must include representative samples of known challenges: sarcasm, emojis, slang, negation, and mixed-ticker posts.
**Acceptance criteria:**
- At least 100 labeled records in ground-truth JSONL file
- At least 50 from r/wallstreetbets, at least 30 from r/stocks
- No single label class exceeds 60% of total records
- At least 15 records involve financial slang from TASK-NLP03 dictionary
- At least 10 records are emoji-heavy (3+ sentiment-relevant emojis)
- At least 10 records involve sarcasm or irony
- At least 5 records mention multiple tickers in a single post

---

### TASK-NLP08: Build the accuracy validation framework — metrics computation
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01, TASK-NLP06, TASK-NLP07
**Description:** Core validation runner that loads the ground-truth dataset, runs any `SentimentAnalyzer` backend against it, and computes classification metrics. Backend-agnostic. Report generation lives in TASK-NLP23; CLI entry point in TASK-NLP24.
**Acceptance criteria:**
- `validate_backend(analyzer: SentimentAnalyzer, dataset_path: str) -> ValidationReport` function exists
- `ValidationReport` dataclass contains: `backend`, `accuracy`, `precision` (per class), `recall` (per class), `f1` (per class), `confusion_matrix`, `failure_cases`
- `ValidationReport` is serializable to dict/JSON with no external dependencies
- Unit tests confirm metrics computation using the 10 fixture records from TASK-NLP06 — no file I/O or CLI in this task

---

### TASK-NLP09: Define accuracy escalation threshold and decision rule
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP08
**Description:** Establish the numeric accuracy threshold below which the system escalates from VADER/TextBlob to FinBERT. Stored in central config, not hardcoded. Document the decision rule and rationale.
**Acceptance criteria:**
- Config key `sentiment.accuracy_threshold` exists, defaulting to `0.75`
- Validation CLI exits with non-zero code and prints clear escalation warning if below threshold
- Decision rule document explains: what the threshold means, what escalation means operationally, how to re-run validation after switching backends
- Threshold overridable via `SSE_ACCURACY_THRESHOLD` environment variable

---

### TASK-NLP10: Implement the FinBERT sentiment backend
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01, TASK-NLP03
**Description:** Concrete `SentimentAnalyzer` subclass using `ProsusAI/finbert` via Hugging Face `transformers`. FinBERT outputs three class probabilities; map to [-1.0, 1.0] as `score = P(positive) - P(negative)`.
**Acceptance criteria:**
- `FinBertSentimentAnalyzer` inherits from `SentimentAnalyzer`
- Model loaded from Hugging Face hub; model ID configurable via config
- Score formula: `score = P(positive) - P(negative)`
- `raw_scores` includes `prob_positive`, `prob_negative`, `prob_neutral`
- `backend` field set to `"finbert"`
- Text over 512-token limit handled by truncation with logged warning; truncation strategy configurable
- Pre-processor optionally applied (default: off — FinBERT handles financial text natively)
- Model loading is lazy (on first `analyze` call, not import time)
- Unit tests mock Hugging Face pipeline to avoid GPU/network requirement in CI

---

### TASK-NLP11: Implement SentimentAnalyzer factory and backend registry
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP04, TASK-NLP05, TASK-NLP10
**Description:** Factory function that instantiates the correct `SentimentAnalyzer` backend based on a string identifier from configuration. The sole place in the codebase where backend selection logic lives.
**Acceptance criteria:**
- `get_sentiment_analyzer(backend: str, config: dict) -> SentimentAnalyzer` factory function
- Supported backends: `"vader"`, `"textblob"`, `"finbert"`
- Raises `ValueError` with clear message listing valid options for unknown backend string
- Active backend read from config key `sentiment.backend`
- Registry dict maps string → class; adding a new backend requires only one new entry
- Unit tests confirm each backend string returns the correct class instance

---

### TASK-NLP12: Implement per-comment weighted sentiment scoring
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01, TASK-NLP02, TASK-NLP11
**Description:** Implement the two-dimensional weighting model. NLP determines direction (from score), Reddit net score determines magnitude. Output: a single `weighted_sentiment` float per comment combining both dimensions.
**Acceptance criteria:**
- `compute_weighted_sentiment(result: SentimentResult, net_score: int, config: dict) -> float` function
- Formula: `weighted_sentiment = result.score * magnitude_weight(net_score, config)`
- Default magnitude_weight: log-scaling `weight = log(abs(net_score) + 1) + 1` (score-0 comments contribute weight 1.0)
- Negative `net_score` behavior controlled by config `sentiment.weighting.downvote_behavior`: `"ignore_sign"` (default), `"invert"`, or `"attenuate"`
- All scaling parameters under `sentiment.weighting.*` in config
- Unit tests: score=0/net_score=0, bullish score with 1000 upvotes, bearish score with downvotes under each mode

---

### TASK-NLP13: Implement temporal decay weighting
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP12
**Description:** Extend the weighting model with a time-decay factor so older comments contribute less. Decay window and decay function both configurable.
**Acceptance criteria:**
- `compute_temporal_weight(comment_age_seconds: float, config: dict) -> float` function
- Returns float in (0.0, 1.0] — 1.0 for fresh comments, approaches 0 as age approaches window
- Default: exponential decay `weight = exp(-lambda * age_seconds)` where `lambda = ln(2) / half_life_seconds`
- Default half-life configurable via `sentiment.temporal.half_life_hours` (default: 6 hours)
- Hard cutoff `sentiment.temporal.max_age_hours` (default: 24 hours) returns 0.0 for older comments
- Linear decay also supported via `sentiment.temporal.decay_function` config key
- Unit tests: age=0 returns 1.0, age=half-life returns ~0.5, age>max returns 0.0

---

### TASK-NLP14: Implement per-ticker aggregate sentiment computation
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP12, TASK-NLP13
**Description:** Function aggregating all weighted, time-decayed sentiment scores for a single ticker within a time window into a single `TickerSentiment` value (the ticker-level signal used by the pricing formula).
**Acceptance criteria:**
- `compute_ticker_sentiment(comments: list[CommentRecord], ticker: str, config: dict) -> TickerSentiment` function
- Only comments mentioning `ticker` included
- Aggregate formula: `sum(weighted_sentiment_i * temporal_weight_i) / sum(temporal_weight_i)` (weighted average)
- Zero-weight comments excluded from numerator and denominator
- `TickerSentiment` contains: `ticker`, `aggregate_score`, `comment_count`, `weighted_comment_count`, `window_start`, `window_end`
- Unit tests: single comment, mixed-sign comments, all past max age (→ 0.0), multi-ticker posts with only relevant ticker counted

---

### TASK-NLP15: Implement volume weighting (mention count signal)
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP14
**Description:** Volume dimension: more mentions of a ticker amplify the sentiment signal. A ticker mentioned 200 times produces a stronger price signal than the same sentiment with 3 mentions.
**Acceptance criteria:**
- `TickerSentiment` extended with `volume_weight: float` field
- Default volume weight formula: `volume_weight = log(weighted_comment_count + 1)`
- Config key `sentiment.volume.scaling_function` supports: `"log"` (default), `"sqrt"`, `"linear"`
- Config key `sentiment.volume.min_mentions` (default: 1): tickers below threshold excluded from pricing
- Aggregate score exposed to pricing: `aggregate_score * volume_weight`
- Unit tests: volume_weight=0 when weighted_comment_count=0, monotonically increasing with count

---

### TASK-NLP16: Implement the sentiment price change formula
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP14, TASK-NLP15
**Description:** Formula converting aggregate sentiment into a `sentiment_delta`. The canonical pricing formula is `sentiment_price = real_price + sentiment_delta` — this function computes the `sentiment_delta` component. Price movement is a function of sentiment CHANGE (current vs previous window), not absolute sentiment level, preventing a permanently bullish ticker from having a permanently inflated price.
**Acceptance criteria:**
- `compute_sentiment_price_delta(current: TickerSentiment, previous: TickerSentiment | None, config: dict) -> float` function
- Return value is `sentiment_delta` — an additive offset applied to `real_price` by the Pricing Engine (TASK-PRC05). This is NOT a standalone price.
- If `previous` is None (first boot bootstrap): `delta = current.aggregate_score * volume_weight * sensitivity`. The Pricing Engine (TASK-PRC11) handles the case where `previous=None` by setting `sentiment_price = real_price` directly.
- Otherwise: `delta = (current.aggregate_score - previous.aggregate_score) * volume_weight * sensitivity`
- `sensitivity` configurable under `sentiment.pricing.sensitivity` (default: 1.0)
- Dampening: `delta = sign(delta) * min(abs(delta), max_delta)` where `max_delta` configurable
- High-volume tickers get different sensitivity: configurable `high_volume_threshold` and `high_volume_sensitivity_multiplier`
- Unit tests: no previous window, positive change, negative change, delta clamped by max_delta, high/low volume branching; docstring explicitly states the `sentiment_price = real_price + delta` formula

---

### TASK-NLP17: Build central configuration schema for all sentiment parameters
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP03, TASK-NLP04, TASK-NLP05, TASK-NLP10, TASK-NLP12, TASK-NLP13, TASK-NLP15, TASK-NLP16
**Description:** Consolidate all configurable parameters from across the sentiment pipeline into a single validated configuration schema. Loadable from YAML with environment variable overrides.
**Acceptance criteria:**
- Config schema (Pydantic `BaseSettings` or dataclass with validation) covers all parameters from TASK-NLP03–NLP16
- Every parameter has explicit default matching its originating task spec
- Config loadable from YAML file path specified by `SSE_CONFIG_PATH` env var
- Env var overrides follow `SSE_SENTIMENT__<SECTION>__<KEY>` pattern (double underscore)
- `validate_config()` raises `ValueError` with human-readable message for out-of-range values
- `config.example.yaml` provided with all parameters at defaults and inline explanatory comments
- Unit tests: default config loads cleanly, invalid range raises ValueError, YAML overrides default, env var overrides YAML

---

### TASK-NLP18: Implement PostgreSQL schema for sentiment results
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP02, TASK-NLP14
**Description:** Database schema for persisting sentiment analysis outputs. Two tables: `comment_sentiment` for individual comment-level results and `ticker_sentiment_snapshot` for per-ticker aggregate snapshots per time window.
**Acceptance criteria:**
- `comment_sentiment` table: `id SERIAL PK`, `reddit_comment_id TEXT UNIQUE`, `ticker TEXT`, `text TEXT`, `net_score INT`, `nlp_score FLOAT`, `weighted_sentiment FLOAT`, `temporal_weight FLOAT`, `backend TEXT`, `raw_scores JSONB`, `analyzed_at TIMESTAMPTZ`, `comment_created_at TIMESTAMPTZ`
- `ticker_sentiment_snapshot` table: `id SERIAL PK`, `ticker TEXT`, `window_start TIMESTAMPTZ`, `window_end TIMESTAMPTZ`, `aggregate_score FLOAT`, `volume_weight FLOAT`, `weighted_comment_count FLOAT`, `comment_count INT`, `sentiment_price_delta FLOAT`, `backend TEXT`, `created_at TIMESTAMPTZ`
- Unique constraint on `ticker_sentiment_snapshot (ticker, window_start, window_end)`
- Indexes on: `comment_sentiment(ticker)`, `comment_sentiment(comment_created_at)`, `ticker_sentiment_snapshot(ticker, window_start)`
- Data access layer: `save_comment_sentiment()`, `save_ticker_snapshot()`, `get_previous_snapshot(ticker, before) -> TickerSentiment | None`
- All queries use parameterized statements

---

### TASK-NLP19: Implement the end-to-end sentiment pipeline orchestrator
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP11, TASK-NLP12, TASK-NLP13, TASK-NLP14, TASK-NLP15, TASK-NLP16, TASK-NLP18
**Description:** Top-level orchestrator wiring all pipeline stages: fetch comments → preprocess → analyze → weight → aggregate → compute delta → persist. Single entry point for each analysis run.
**Acceptance criteria:**
- `run_sentiment_pipeline(comments: list[RawComment], tickers: list[str], config: SentimentConfig) -> list[TickerSentimentDelta]` function
- Pipeline stages execute in order with no business logic in the orchestrator itself
- Failed NLP scoring on a single comment logs the error and skips that comment; does not abort the run
- Orchestrator logs: comments received, successfully scored, skipped, tickers processed, time elapsed
- Dry-run mode (`config.dry_run = True`): runs all stages but skips persistence
- Integration test runs full pipeline against 10 fixture records using VADER backend, asserting `TickerSentimentDelta` objects produced without error

---

### TASK-NLP20: Backend comparison report tooling
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP08, TASK-NLP09, TASK-NLP23, TASK-NLP24
**Description:** Script running the validation framework against all registered backends on the same ground-truth dataset and producing a side-by-side comparison report in markdown. Used to make the VADER/TextBlob vs FinBERT escalation decision.
**Acceptance criteria:**
- Script `compare_backends.py` runs `validate_backend` for vader, textblob, and finbert
- Output: markdown table with accuracy, macro F1, per-class F1 for each backend
- Flags any backend below `sentiment.accuracy_threshold` with a clear warning line
- Writes output to `reports/backend_comparison_<timestamp>.md`
- `--backends` flag allows running a subset (e.g., skip slow FinBERT)
- VADER + TextBlob comparison on 100 records completes in under 30 seconds on commodity hardware

---

### TASK-NLP21: Add `analyze_batch` method to `SentimentAnalyzer` interface
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP01, TASK-NLP04, TASK-NLP05, TASK-NLP10
**Description:** Extend `SentimentAnalyzer` ABC with `analyze_batch(texts: list[str]) -> list[float]`. The default base-class implementation loops over `analyze()` (backward-compatible). The FinBERT backend overrides with native batched inference. The pipeline orchestrator (TASK-NLP19) is updated to call `analyze_batch` instead of a per-comment loop.
**Acceptance criteria:**
- `SentimentAnalyzer` defines `analyze_batch(texts: list[str]) -> list[float]` with default loop-based implementation
- `FinBertSentimentAnalyzer.analyze_batch` uses HuggingFace `pipeline(texts, batch_size=N)` where `N` is from config `sentiment.finbert.batch_size` (default: 32, valid: 1–128)
- `len(output) == len(texts)` enforced; mismatched lengths raise `ValueError`
- `VaderSentimentAnalyzer` and `TextBlobSentimentAnalyzer` inherit the default loop implementation — no change needed
- TASK-NLP19 pipeline orchestrator updated to call `analyze_batch` for all comments in a run
- Unit tests: empty list → empty list; single-element → same result as `analyze()`; order preserved; FinBERT mock verifies `pipeline` called once per batch, not once per text

---

### TASK-NLP22: Pre-analysis existence check in sentiment pipeline
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP18, TASK-NLP19
**Description:** Before running NLP on a batch of comments, query `comment_sentiment` for existing rows matching `reddit_comment_id` + `backend`. Skip re-analysis unless `recompute_on_score_change` config is true and net score has changed above a threshold.
**Acceptance criteria:**
- `SentimentRepository.get_existing_scores(comment_ids: list[str], backend: str) -> dict[str, SentimentResult]` added — fetches all matching rows in one query
- `run_sentiment_pipeline` calls this once per run and filters comments before `analyze_batch`
- Config key `sentiment.recompute_on_score_change` (bool, default: false)
- Config key `sentiment.recompute_score_delta_threshold` (int, default: 10) — minimum net-score change triggering re-analysis when flag is true
- Skipped comments logged at DEBUG with reason "existing result, no recompute"
- Pipeline metrics extended with `comments_skipped_cached` counter
- Note: score updates (TASK-S03 upserts) do NOT trigger this — only the next scheduled pipeline run with `recompute_on_score_change=true` triggers re-analysis (AMBIG-3 resolution)
- Unit tests: all cached → zero NLP calls; one with score change above threshold → one NLP call; flag false → no re-analysis regardless

---

### TASK-NLP23: Accuracy report file generation
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP08
**Description:** Report writer that takes a `ValidationReport` from TASK-NLP08 and serializes it to a JSON file. Separate from the metrics computation and the CLI.
**Acceptance criteria:**
- `write_validation_report(report: ValidationReport, output_path: str) -> None` function
- Writes JSON file with all `ValidationReport` fields
- Output filename includes backend name and ISO timestamp if not specified
- Creates parent directories if they don't exist
- Unit tests verify file contents match input report exactly

---

### TASK-NLP24: Validation CLI entry point
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP08, TASK-NLP23
**Description:** Command-line interface that wires together TASK-NLP08 (metrics computation) and TASK-NLP23 (report writing). The CLI is the only layer that knows about file paths and argument parsing.
**Acceptance criteria:**
- `python validate.py --backend vader --dataset path/to/labels.jsonl [--output path/to/report.json]` runs end-to-end
- `--backend` accepts: `vader`, `textblob`, `finbert`
- Unknown backend prints clear error listing valid options and exits with code 1
- Exits with code 0 on success, non-zero on any error
- Exits with code 2 and prints escalation warning if accuracy is below `sentiment.accuracy_threshold`
- Unit tests mock `validate_backend` and `write_validation_report`; verify argument parsing and exit codes

---

### TASK-NLP25: Algorithm registry and multi-algorithm pipeline execution
**Domain:** Sentiment Analysis
**Depends on:** TASK-NLP04, TASK-NLP05, TASK-NLP10, TASK-NLP17, TASK-NLP19, TASK-OPS34
**Description:** Formalize a canonical list of available sentiment algorithms and extend the pipeline to run all configured algorithms per scrape cycle, persisting each backend's results as separate rows. The existing `comment_sentiment` and `ticker_sentiment_snapshot` schemas already support multi-backend storage via the `backend TEXT` column — this task wires the configuration and pipeline iteration.

**Algorithm registry (canonical definition):**
- `AVAILABLE_ALGORITHMS = ["vader", "textblob", "finbert"]` defined as a constant in `sse_common/constants.py` (TASK-OPS34). This is the single authoritative list shared by backend, processor, pricing engine, and frontend types.
- `AlgorithmRegistry` class in `sentiment/registry.py` maps string name → `SentimentAnalyzer` subclass: `{"vader": VaderSentimentAnalyzer, "textblob": TextBlobSentimentAnalyzer, "finbert": FinBertSentimentAnalyzer}`
- `AlgorithmRegistry.get(name: str) -> SentimentAnalyzer` raises `ValueError` with list of valid names if unknown

**Configuration additions to NLP17 schema:**
- `sentiment.active_algorithms: list[str]` — algorithms to run each cycle (default: `["vader"]`; valid values: any subset of `AVAILABLE_ALGORITHMS`)
- `sentiment.primary_algorithm: str` — which algorithm's `sentiment_price_delta` feeds the pricing formula (default: `"vader"`; must be in `active_algorithms`)
- Validation: `primary_algorithm` must be a member of `active_algorithms`; empty `active_algorithms` raises `ValueError`

**Pipeline execution:**
- `run_sentiment_pipeline` (TASK-NLP19) updated to iterate over `config.active_algorithms`
- For each algorithm: instantiate via registry, call `analyze_batch` (TASK-NLP21), persist to `comment_sentiment` with `backend = algorithm_name`
- `compute_sentiment_price_delta` (TASK-NLP16) called only for `primary_algorithm`; other algorithms' snapshots are stored in `ticker_sentiment_snapshot` but do NOT drive the pricing formula
- TASK-NLP22 existence check already deduplicates per `(reddit_comment_id, backend)` — no change needed

**Acceptance criteria:**
- `AVAILABLE_ALGORITHMS` exported from `sse_common.constants` (Python only — not a frontend concern)
- `AlgorithmRegistry.get("unknown")` raises `ValueError` listing all valid names
- Config `active_algorithms: [vader, finbert]` causes pipeline to run both backends; only `primary_algorithm` output reaches the pricing engine
- `comment_sentiment` after a run with `active_algorithms=[vader, textblob]` contains two rows per comment (one per backend), verified by integration test
- `config.example.yaml` updated with `active_algorithms` and `primary_algorithm` entries with inline comments
- Unit tests: registry maps all three names correctly; unknown name raises ValueError; pipeline iteration verified with mocked analyzers; validation rejects `primary_algorithm` not in `active_algorithms`

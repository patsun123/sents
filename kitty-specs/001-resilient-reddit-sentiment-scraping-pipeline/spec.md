# Feature Specification: Resilient Reddit Sentiment Scraping Pipeline

**Feature Branch**: `001-resilient-reddit-sentiment-scraping-pipeline`
**Created**: 2026-03-09
**Status**: Draft
**Mission**: software-dev

---

## Overview

The scraping pipeline is the existential foundation of SentiX. Without reliable, continuous sentiment data flowing in from Reddit, the sentiment price engine has nothing to work with. This feature establishes a fault-tolerant, privacy-respecting pipeline that collects comments from configurable subreddits on a regular schedule, identifies and scores ticker mentions, and stores only structured sentiment results — never raw posts, never user data.

This pipeline runs unattended. The developer cannot monitor it 24/7, so resilience and self-recovery are non-negotiable requirements, not enhancements.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Continuous Sentiment Collection (Priority: P1)

The pipeline runs on a fixed 15-minute schedule, collecting comments from all configured subreddits, extracting ticker mentions, scoring the sentiment of those mentions, and storing the results. This happens automatically, without human intervention, around the clock.

**Why this priority**: Without this running reliably, SentiX has no data. Everything else depends on it. If collection fails silently, sentiment prices go stale without anyone knowing.

**Independent Test**: Can be fully tested by running the pipeline in isolation against a set of known subreddits and verifying that structured sentiment scores appear in storage within 15 minutes, with no raw comment data or user identifiers present anywhere in the system.

**Acceptance Scenarios**:

1. **Given** the pipeline is enabled and subreddits are configured, **When** a 15-minute interval elapses, **Then** comments are collected from all active subreddits, tickers are identified and scored, and results are stored
2. **Given** a collection cycle runs successfully, **When** the results are inspected, **Then** no raw comment text, usernames, or any personally identifiable information exists anywhere in storage
3. **Given** a collection cycle completes, **When** the same subreddit is checked again in 15 minutes, **Then** only new comments since the last run are processed (no duplicate scoring)

---

### User Story 2 - Source Configuration Without Downtime (Priority: P2)

The operator can add or remove subreddits from the collection list at any time. The change takes effect on the next scheduled collection cycle without restarting the system or deploying new code.

**Why this priority**: The starting subreddits (r/wallstreetbets, r/stocks, r/investing) are not the final list. As the product evolves, new sources will be added and underperforming ones removed. Requiring a redeploy for every change would be untenable for a solo operator.

**Independent Test**: Can be tested by adding a new subreddit to the configuration, waiting for the next collection cycle, and confirming that sentiment scores from that subreddit appear in storage without any system restart.

**Acceptance Scenarios**:

1. **Given** a new subreddit is added to the source configuration, **When** the next collection cycle runs, **Then** comments from that subreddit are included in scoring
2. **Given** a subreddit is disabled in the source configuration, **When** the next collection cycle runs, **Then** no new data is collected from that subreddit
3. **Given** an invalid subreddit name is added to configuration, **When** the collection cycle runs, **Then** the error is logged, collection from other subreddits continues unaffected, and no crash occurs

---

### User Story 3 - Fault Recovery and Self-Healing (Priority: P1)

When Reddit is temporarily unreachable, rate-limiting requests, or a subreddit becomes unavailable, the pipeline handles the failure gracefully — backing off, retrying, and resuming automatically once conditions improve. The operator receives an alert but does not need to manually restart anything.

**Why this priority**: This is a solo project with no live ops monitoring. A pipeline that crashes silently and requires manual restart would cause extended data gaps. Self-healing is essential.

**Independent Test**: Can be tested by simulating a source outage mid-run and verifying the pipeline retries with backoff, collects from other sources in the meantime, and resumes from the failed source automatically when it becomes available — all without human intervention.

**Acceptance Scenarios**:

1. **Given** a subreddit is temporarily unavailable, **When** the collection attempt fails, **Then** the failure is logged, the pipeline retries with increasing wait times, and other subreddits are not affected
2. **Given** the pipeline has been rate-limited by a source, **When** the limit window expires, **Then** collection resumes automatically on the next cycle without manual action
3. **Given** a collection cycle fails entirely, **When** the next scheduled interval arrives, **Then** the pipeline starts fresh and attempts collection again
4. **Given** any failure occurs, **When** the error threshold is exceeded, **Then** the operator receives an alert notification

---

### User Story 4 - Zero PII Storage (Priority: P1)

At no point in the pipeline — collection, processing, or storage — is any user-identifiable information retained. Comments are processed in memory and discarded. Only the derived sentiment score for each ticker is persisted.

**Why this priority**: Privacy by design is a legal and ethical requirement. Storing Reddit usernames or comment text creates liability and is entirely unnecessary for the product's function.

**Independent Test**: Can be tested by auditing all storage locations after a full collection cycle and confirming that no usernames, comment IDs, comment text, or any other user-attributable data exists anywhere in the system.

**Acceptance Scenarios**:

1. **Given** a collection cycle completes, **When** all data stores are inspected, **Then** no Reddit usernames, comment bodies, post titles, or comment IDs are found
2. **Given** the pipeline processes a comment mentioning a ticker, **When** scoring is complete, **Then** only the ticker symbol, sentiment score, timestamp, subreddit source, and comment count are retained
3. **Given** an error occurs during processing, **When** the error is logged, **Then** the log contains no user-identifiable content from Reddit

---

### Edge Cases

- What happens when a subreddit goes private or is banned mid-cycle?
- What happens when the same ticker appears in hundreds of comments within one cycle — is there a volume cap?
- What happens when a comment mentions a ticker symbol that is also a common English word (e.g., "NOW", "ARE", "IT")?
- If a collection cycle takes longer than 15 minutes, the next cycle is queued and runs immediately after the current one finishes (sequential, not concurrent).
- What happens when the scoring system is unavailable while collection succeeds?
- What happens when Reddit returns malformed or unexpected response data?

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST collect comments from a configurable list of subreddits on a 15-minute schedule; if a cycle is still running when the next interval fires, the next cycle MUST queue and execute sequentially after the current one completes — concurrent cycle execution is not permitted
- **FR-002**: The system MUST dynamically identify any ticker symbol mentioned in collected comments — the tracked ticker set is not pre-configured; tickers are discovered organically from comment content; the system MUST apply disambiguation rules to suppress false positives (common English words that are also valid ticker symbols, e.g., "IT", "NOW", "ARE")
- **FR-003**: The system MUST classify the sentiment of each ticker mention as positive or negative and record the upvote count of the source comment as the signal weight; the pipeline stores raw signals, not pre-computed scores — scoring algorithms are applied separately and interchangeably against the stored signals
- **FR-004**: The system MUST store one sentiment signal record per ticker mention per collection cycle containing: ticker symbol, sentiment polarity (positive or negative), upvote weight, and collection timestamp; signals are the algorithm-agnostic source of truth that any scoring formula can consume; no raw comment text, usernames, or user-attributable data is retained
- **FR-004a**: The system MUST support multiple scoring algorithms being applied to the same stored signals simultaneously, enabling algorithm comparison and tuning without re-collecting data
- **FR-005**: The system MUST NOT retain raw comment text, usernames, comment IDs, or any user-attributable data at any stage
- **FR-006**: The system MUST process only comments newer than the last successful collection cycle to avoid duplicate scoring
- **FR-007**: The system MUST retry failed collection attempts using a backoff strategy before marking a cycle as failed
- **FR-008**: The system MUST continue collecting from available subreddits when one source fails
- **FR-009**: The system MUST log all collection events, failures, and retry attempts for operational visibility
- **FR-010**: The system MUST alert the operator when error thresholds are exceeded
- **FR-011**: Source subreddits MUST be configurable without requiring a system restart or code deployment
- **FR-012**: The system MUST respect source-imposed rate limits and back off accordingly
- **FR-013**: The system MUST handle malformed or unexpected source responses without crashing

### Key Entities

- **Sentiment Signal**: The atomic unit of storage. Represents one ticker mention from one comment in one collection cycle. Contains: ticker symbol, sentiment polarity (positive or negative), upvote weight (the comment's upvote count at time of collection), collection timestamp. Signals are the algorithm-agnostic raw data — they never contain comment text, usernames, or any PII. All scoring algorithms operate on signals.
- **Scored Result**: A computed output derived by applying a specific scoring algorithm to a set of Sentiment Signals. Multiple algorithms can produce multiple Scored Results from the same signals simultaneously, enabling comparison and tuning. Scored Results are derived/computed — signals are the source of truth.
- **Data Source**: A configured subreddit entry. Contains: subreddit name, enabled/disabled status, date added. Sources are managed through configuration, not code.
- **Collection Run**: A record of a single pipeline execution. Contains: start time, end time, status (success/partial/failed), sources attempted, sources succeeded, total signals stored. Used for operational monitoring.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The pipeline achieves 99% or greater successful collection cycles over any rolling 30-day period
- **SC-002**: Fresh sentiment signals for all configured subreddits are stored at least every 15 minutes under normal operating conditions
- **SC-003**: Zero instances of user-identifiable Reddit data stored anywhere in the system, validated by automated audit
- **SC-004**: A new subreddit source can be added and producing scores within one collection cycle (15 minutes), with no system restart
- **SC-005**: The pipeline recovers automatically from transient source outages within one collection cycle of the source becoming available again
- **SC-006**: No manual intervention is required to restart the pipeline after a transient failure
- **SC-007**: All collection failures and retries are observable in logs without requiring access to the source system

---

## Clarifications

### Session 2026-03-09

- Q: If a cycle takes longer than 15 minutes, what happens to the next scheduled cycle? → A: Queue it — run immediately after the current one finishes (sequential, not concurrent)
- Q: Are sentiment scores stored per-subreddit or aggregated across all subreddits? → A: Aggregated — one score per ticker across all subreddits, weighted by comment upvote count (popularity)
- Q: Is the tracked ticker list pre-configured or discovered dynamically? → A: Dynamic — any ticker found in comments is scored; disambiguation rules suppress common-word false positives
- Q: What does the confidence indicator represent? → A: Volume-based — higher mention count yields higher confidence score
- Q: Should the pipeline store pre-computed scores or raw signals? → A: Raw signals (ticker, sentiment polarity, upvote weight, timestamp) — scoring algorithms are applied separately so multiple algos can be compared against the same data; this also implicitly answers score retention: signals are the long-term store

---

## Assumptions

- Reddit's publicly accessible comment data (without authentication) is sufficient for the initial subreddit targets
- Comment volume on the initial subreddits (r/wallstreetbets, r/stocks, r/investing) is manageable within a 15-minute collection window
- A 15-minute collection frequency is sufficient for meaningful sentiment signal — real-time streaming is not required at launch
- Ticker symbols are discovered dynamically from comment content, not from a pre-configured list; disambiguation of false positives (common English words that are also valid tickers) is a required capability of the pipeline
- The operator's alerting tolerance is per-cycle, not per-comment — summary alerts are preferable to per-error noise

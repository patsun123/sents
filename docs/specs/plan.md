# Milestone Plan — V1 Gap Closure

**Author:** Treebeard (Planner)
**Date:** 2026-03-30
**Status:** APPROVED

---

## Dependency Map

Before laying out milestones, here is how the requirements depend on each other:

```
REQ-03 (Quality Filtering) ─────┐
REQ-04 (Text Preprocessor) ─────┼──► REQ-02 (Weighting Model) ──► REQ-12 (Cont. Agg.)
REQ-01 (Comment Scraping) ──────┘                                       │
                                                                        ▼
REQ-15 (Redis Auth) ──► REQ-06 (Redis Resilience)              REQ-08 (Frontend Charts)
                    ──► REQ-05 (Health Endpoints)                       │
                                                                        ▼
REQ-14 (Read-Only Containers) ─┐                               REQ-11 (Frontend Tests)
REQ-16 (DB Backups) ───────────┤
REQ-07 (Rate Limiting) ────────┼──► REQ-10 (GitHub Actions CI)
REQ-09 (Service Tests) ────────┘         │
                                         ▼
                                  REQ-13 (Documentation)
```

Key constraints:
- **Redis auth (REQ-15)** must come first — it changes connection strings for every service
- **Quality filtering (REQ-03)** and **text preprocessor (REQ-04)** must precede weighting (REQ-02), since weighting operates on filtered + preprocessed data
- **Comment scraping (REQ-01)** is independent of processor changes but must precede E2E validation
- **Tests (REQ-09, 11)** should be written alongside the code they test, but CI (REQ-10) depends on tests existing
- **Documentation (REQ-13)** should come last since it documents the final state

---

## Milestone 1: Infrastructure Hardening
**Goal:** Secure the foundation — Redis auth, read-only containers, DB backups. Every subsequent milestone builds on a hardened stack.

### Tasks
- [ ] **1.1** Add Redis password auth to docker-compose.yml and .env — assigned to **Engineer**
- [ ] **1.2** Update all service configs (scraper, processor, pricing_engine, backend) to use Redis password in connection URL — assigned to **Backend Dev**
- [ ] **1.3** Add `read_only: true` + tmpfs mounts to all application containers in docker-compose.yml — assigned to **Engineer**
- [ ] **1.4** Create `database/backup.sh` script — assigned to **Engineer**
- [ ] **1.5** Add `db-backup` service to docker-compose.yml with volume + env config — assigned to **Engineer**
- [ ] **1.6** Update Redis healthcheck to use password — assigned to **Engineer**
- [ ] **1.7** Update `pricing_configurations` seed data in `init.sql` to include new weighting params (`decay_halflife_hours`, `upvote_weight_min`, `upvote_weight_max`) — assigned to **Backend Dev**
- [ ] **1.8** Smoke test: `docker compose down -v && docker compose up --build` — verify all services start with new auth + read-only settings — assigned to **Engineer**

### Dependencies
- None — this is the foundation milestone

### Risks
- **Existing services break with Redis auth:** Mitigated by updating all configs in the same milestone before testing
- **Read-only filesystem breaks service:** Mitigated by tmpfs mounts for known writable paths; smoke test catches remaining issues

### Covers
- REQ-14 (Container Read-Only)
- REQ-15 (Redis Auth)
- REQ-16 (DB Backups)
- Partial REQ-02 (seed data update)

---

## Milestone 2: Data Pipeline — Quality & Preprocessing
**Goal:** Clean up the data pipeline so the processor receives high-quality, preprocessed text. This is prerequisite to meaningful weighted sentiment.

### Tasks
- [ ] **2.1** Implement `_should_skip()` quality filter in `RedditClient` (deleted, bots, min length) — assigned to **Backend Dev**
- [ ] **2.2** Add bot username list and min_content_length to scraper config — assigned to **Backend Dev**
- [ ] **2.3** Add processor-side quality filtering in `get_unprocessed_posts()` SQL query — assigned to **Backend Dev**
- [ ] **2.4** Implement duplicate detection: mark `is_duplicate = TRUE` after batch insert via `content_fingerprint` — assigned to **Backend Dev**
- [ ] **2.5** Create `processor/src/processor/text/slang_dict.py` — financial slang expansion dictionary — assigned to **Backend Dev**
- [ ] **2.6** Create `processor/src/processor/text/emoji_map.py` — emoji-to-sentiment mapping — assigned to **Backend Dev**
- [ ] **2.7** Create `processor/src/processor/text/preprocessor.py` — preprocess() pipeline (cashtags, slang, emoji, whitespace) — assigned to **Backend Dev**
- [ ] **2.8** Integrate `preprocess()` call in `pipeline.py` before sentiment backends — assigned to **Backend Dev**
- [ ] **2.9** Manual test: run scraper + processor, verify filtered posts are excluded and text is preprocessed in DB — assigned to **Backend Dev**

### Dependencies
- **Milestone 1** (Redis auth must be in place so services can connect)

### Risks
- **Slang dictionary too aggressive:** "dip" and "rip" are common English words. Mitigated by whole-word matching only.
- **Preprocessor changes sentiment scores:** Expected and desired — the whole point is better signal

### Covers
- REQ-03 (Quality Filtering)
- REQ-04 (Financial Text Preprocessor)

---

## Milestone 3: Comment Scraping
**Goal:** Scraper fetches Reddit comments in addition to posts, enriching the sentiment signal.

### Tasks
- [ ] **3.1** Implement `RedditClient.fetch_comments(post_reddit_id, limit)` — assigned to **Backend Dev**
- [ ] **3.2** Create `RedditComment` dataclass — assigned to **Backend Dev**
- [ ] **3.3** Modify `run_scrape_cycle()` to fetch comments for top-10 posts (by num_comments) per cycle — assigned to **Backend Dev**
- [ ] **3.4** Extend `store_posts()` to handle comment storage in `reddit_raw` with `post_type='comment'` — assigned to **Backend Dev**
- [ ] **3.5** Verify quality filtering applies to comments (same `_should_skip()` logic) — assigned to **Backend Dev**
- [ ] **3.6** Manual test: run full cycle, verify comments appear in `reddit_raw` and flow through processor — assigned to **Backend Dev**

### Dependencies
- **Milestone 2** (quality filtering must exist to filter comments at ingestion)

### Risks
- **Reddit rate limiting on comment endpoints:** Mitigated by throttling to 10 posts/cycle with 1s delay between requests
- **Comment volume overwhelms processor:** Mitigated by limit=50 per post and 10 posts per cycle cap

### Covers
- REQ-01 (Comment Scraping)

---

## Milestone 4: NLP Weighting Model
**Goal:** Replace raw AVG sentiment with weighted aggregation using upvote magnitude, temporal decay, and volume weighting.

### Tasks
- [ ] **4.1** Implement weighted aggregation SQL in `aggregate_sentiment_snapshot()` (upvote weight + temporal decay) — assigned to **Backend Dev**
- [ ] **4.2** Read weighting params from `pricing_configurations` JSONB (or defaults) — assigned to **Backend Dev**
- [ ] **4.3** Update backend scenario series SQL in `tickers.py` to use per-config weighting params — assigned to **Backend Dev**
- [ ] **4.4** Verify `weighted_mention_count` is now sum-of-weights (not raw count) — assigned to **Backend Dev**
- [ ] **4.5** Manual test: run full pipeline end-to-end, verify weighted snapshots differ from raw AVG — assigned to **Backend Dev**

### Dependencies
- **Milestone 2** (preprocessed + filtered data)
- **Milestone 3** (comments add volume for meaningful weighting)

### Risks
- **Weighted SQL performance:** Mitigated by running at snapshot time (not query time). Only processes last window_hours of data.
- **Parameter tuning:** Defaults are reasonable; further tuning is a post-V1 concern

### Covers
- REQ-02 (NLP Weighting Model)

---

## Milestone 5: Service Resilience
**Goal:** Health endpoints on all pipeline services, processor Redis resilience, API rate limiting.

### Tasks
- [ ] **5.1** Create shared `HealthServer` class (aiohttp-based) in `sse_common` or per-service — assigned to **Engineer**
- [ ] **5.2** Integrate health server in scraper (port 8001), update `last_success` after each cycle — assigned to **Backend Dev**
- [ ] **5.3** Integrate health server in processor (port 8002) — assigned to **Backend Dev**
- [ ] **5.4** Integrate health server in pricing_engine (port 8003) — assigned to **Backend Dev**
- [ ] **5.5** Add Docker healthcheck config for scraper, processor, pricing_engine in docker-compose.yml — assigned to **Engineer**
- [ ] **5.6** Implement processor dual-mode: event-driven + poll fallback — assigned to **Backend Dev**
- [ ] **5.7** Implement processor Redis reconnect loop — assigned to **Backend Dev**
- [ ] **5.8** Add `slowapi` dependency to backend — assigned to **Backend Dev**
- [ ] **5.9** Configure rate limiter in `main.py` with in-memory backend — assigned to **Backend Dev**
- [ ] **5.10** Apply rate limit decorators to all API endpoints (60/min general, 10/min SSE) — assigned to **Backend Dev**
- [ ] **5.11** Smoke test: stop Redis, verify processor falls back to polling; restart Redis, verify reconnect — assigned to **Backend Dev**

### Dependencies
- **Milestone 1** (Redis auth in place)

### Risks
- **Health server port conflicts:** Mitigated by dedicated ports 8001-8003, not exposed to host
- **aiohttp not installed:** Check dependency; add if missing
- **Poll fallback double-processes:** Mitigated by checking last_run timestamp before running pipeline

### Covers
- REQ-05 (Health Endpoints)
- REQ-06 (Processor Redis Resilience)
- REQ-07 (Rate Limiting)

---

## Milestone 6: Frontend Charts & Components
**Goal:** Implement SparklineChart, DivergenceGauge, ChartLegend, and SSE live chart updates.

### Tasks
- [ ] **6.1** Add `sparkline` field to market overview backend query in `market.py` — assigned to **Backend Dev**
- [ ] **6.2** Update `TickerSummary` TypeScript type to include `sparkline: number[]` — assigned to **Frontend Dev**
- [ ] **6.3** Implement `SparklineChart` component (canvas-based, 80x32px) — assigned to **Frontend Dev**
- [ ] **6.4** Implement `DivergenceGauge` component (sm + md sizes) — assigned to **Frontend Dev**
- [ ] **6.5** Implement `ChartLegend` component — assigned to **Frontend Dev**
- [ ] **6.6** Update `MarketTable` columns: replace DeltaCell with DivergenceGauge, add Sparkline column — assigned to **Frontend Dev**
- [ ] **6.7** Update `TickerDetail` header: add DivergenceGauge (md) next to ticker name — assigned to **Frontend Dev**
- [ ] **6.8** Add ChartLegend below TickerChart — assigned to **Frontend Dev**
- [ ] **6.9** Implement SSE live chart updates: use `update()` for incremental append in TickerChart — assigned to **Frontend Dev**
- [ ] **6.10** Verify: chart respects user viewport on live updates (no forced fitContent on SSE events) — assigned to **Frontend Dev**

### Dependencies
- **Milestone 4** (weighted sentiment must be flowing for meaningful chart data)
- Backend sparkline API field (task 6.1) must complete before frontend integration

### Risks
- **Canvas sparkline rendering issues:** Mitigated by simple 2D line drawing, no complex library
- **SSE update() conflicts with setData():** Mitigated by using update() only for live events, setData() only for initial/query loads

### Covers
- REQ-08 (Frontend Chart Components)

---

## Milestone 7: Continuous Aggregate Optimization
**Goal:** History queries use TimescaleDB continuous aggregates instead of scanning raw hypertable.

### Tasks
- [ ] **7.1** Verify `sentiment_prices_1h` continuous aggregate definition in `init.sql` — assigned to **Backend Dev**
- [ ] **7.2** Add continuous aggregate refresh policy if not present — assigned to **Backend Dev**
- [ ] **7.3** Update `tickers.py` 1d history query to read from `sentiment_prices_1h` — assigned to **Backend Dev**
- [ ] **7.4** Update 1w and 1m history queries to aggregate from `sentiment_prices_1h` — assigned to **Backend Dev**
- [ ] **7.5** Verify: history endpoints return correct data from continuous aggregate — assigned to **Backend Dev**

### Dependencies
- **Milestone 4** (weighting model changes must be stable before optimizing queries)

### Risks
- **Continuous aggregate stale data:** Mitigated by refresh policy (1 hour lag is acceptable for prototype)
- **Query results differ from raw table:** Verify with side-by-side comparison during testing

### Covers
- REQ-12 (Continuous Aggregate Optimization)

---

## Milestone 8: Testing
**Goal:** Comprehensive test coverage for all services + frontend. Write tests for all new code from milestones 2-7.

### Tasks
- [ ] **8.1** Add test dependencies to each service's `pyproject.toml` — assigned to **Engineer**
- [ ] **8.2** Create scraper test fixtures (`conftest.py`) — assigned to **Backend Dev**
- [ ] **8.3** Write scraper tests: `test_reddit_client.py`, `test_comment_parsing.py`, `test_quality_filter.py`, `test_storage.py` — assigned to **Backend Dev**
- [ ] **8.4** Create processor test fixtures — assigned to **Backend Dev**
- [ ] **8.5** Write processor tests: `test_vader.py`, `test_textblob.py`, `test_preprocessor.py`, `test_weighting.py`, `test_pipeline.py` — assigned to **Backend Dev**
- [ ] **8.6** Create pricing_engine test fixtures — assigned to **Backend Dev**
- [ ] **8.7** Write pricing_engine tests: `test_formula.py`, `test_config_loading.py`, `test_publisher.py` — assigned to **Backend Dev**
- [ ] **8.8** Install frontend test dependencies (vitest, @testing-library/react, jsdom) — assigned to **Frontend Dev**
- [ ] **8.9** Configure Vitest in `vite.config.ts`, create `src/test/setup.ts` — assigned to **Frontend Dev**
- [ ] **8.10** Write frontend tests: `MarketTable.test.tsx`, `SparklineChart.test.tsx`, `DivergenceGauge.test.tsx`, `ChartLegend.test.tsx` — assigned to **Frontend Dev**
- [ ] **8.11** Write SSE hook test: `useSSE.test.ts` — assigned to **Frontend Dev**
- [ ] **8.12** Run all tests locally, fix any failures — assigned to **Engineer**

### Dependencies
- **Milestones 2-7** (all production code must be written before comprehensive testing)

### Risks
- **Mocking asyncpg is complex:** Mitigated by testing at the function level with simple mock pools
- **Canvas testing in jsdom:** SparklineChart canvas may need simplified assertion (check render, not pixel output)

### Covers
- REQ-09 (Service Test Coverage)
- REQ-11 (Frontend Tests)

---

## Milestone 9: CI/CD Pipeline
**Goal:** GitHub Actions CI that lints, tests, and builds on every push/PR.

### Tasks
- [ ] **9.1** Create `ruff.toml` at project root — assigned to **Engineer**
- [ ] **9.2** Run ruff across entire codebase, fix lint errors — assigned to **Engineer**
- [ ] **9.3** Create `.github/workflows/ci.yml` with lint, test-backend (matrix), test-frontend, build-frontend jobs — assigned to **Engineer**
- [ ] **9.4** Add `npm run test` script to `package.json` (Vitest) — assigned to **Frontend Dev**
- [ ] **9.5** Push to GitHub and verify CI pipeline runs green — assigned to **Engineer**
- [ ] **9.6** Fix any CI-specific failures (path issues, dependency resolution) — assigned to **Engineer**

### Dependencies
- **Milestone 8** (tests must exist for CI to run them)

### Risks
- **uv setup in GitHub Actions:** Mitigated by using official `astral-sh/setup-uv` action
- **sse_common install order:** CI must install sse_common before service packages

### Covers
- REQ-10 (GitHub Actions CI)

---

## Milestone 10: Documentation
**Goal:** Write operational documentation covering architecture, local dev, operations, and security.

### Tasks
- [ ] **10.1** Write `docs/architecture-overview.md` — system diagram, service descriptions, data flow — assigned to **Engineer**
- [ ] **10.2** Write `docs/local-dev-setup.md` — prerequisites, docker compose commands, env vars, troubleshooting — assigned to **Engineer**
- [ ] **10.3** Write `docs/operations-runbook.md` — reset DB, restart services, check logs, backup/restore procedure — assigned to **Engineer**
- [ ] **10.4** Write `docs/security.md` — DB roles, Redis auth, container hardening, network model — assigned to **Engineer**

### Dependencies
- **All prior milestones** (documentation reflects final state)

### Risks
- **Documentation becomes outdated:** Acceptable risk for prototype; docs reflect V1 state

### Covers
- REQ-13 (Documentation)

---

## Critical Path

```
M1 (Infra) ──► M2 (Quality/Preprocess) ──► M3 (Comments) ──► M4 (Weighting)
                                                                    │
                                                              ┌─────┴─────┐
                                                              ▼           ▼
                                                    M6 (Frontend)  M7 (Cont.Agg.)
                                                              │           │
                                                              └─────┬─────┘
                                                                    ▼
M1 ──► M5 (Resilience) ──────────────────────────────────► M8 (Testing)
                                                                    │
                                                                    ▼
                                                            M9 (CI/CD)
                                                                    │
                                                                    ▼
                                                           M10 (Documentation)
```

**Longest path:** M1 → M2 → M3 → M4 → M6 → M8 → M9 → M10

**Parallelizable:** M5 can run in parallel with M2-M4. M6 and M7 can run in parallel.

---

## Milestone Summary

| Milestone | REQs | Tasks | Dependencies |
|-----------|------|-------|-------------|
| M1: Infrastructure Hardening | 14, 15, 16 | 8 | None |
| M2: Quality & Preprocessing | 03, 04 | 9 | M1 |
| M3: Comment Scraping | 01 | 6 | M2 |
| M4: NLP Weighting Model | 02 | 5 | M2, M3 |
| M5: Service Resilience | 05, 06, 07 | 11 | M1 |
| M6: Frontend Charts | 08 | 10 | M4 |
| M7: Continuous Aggregate | 12 | 5 | M4 |
| M8: Testing | 09, 11 | 12 | M2-M7 |
| M9: CI/CD Pipeline | 10 | 6 | M8 |
| M10: Documentation | 13 | 4 | M1-M9 |
| **Total** | **16 REQs** | **76 tasks** | |

---

## Key Risks

1. **Reddit rate limiting on comment fetches:** 10 additional HTTP requests per cycle (10 posts × 1 request each). Mitigated by throttling and 1s delays. If rate-limited, comment scraping degrades gracefully (posts still work).

2. **Weighted aggregation SQL correctness:** The LATERAL join with exponential decay is non-trivial. Mitigated by writing unit tests (M8) that verify known inputs produce expected outputs, and manual validation during M4.

3. **Docker read-only breakage:** Some services may write to unexpected paths (pip cache, Python bytecode). Mitigated by smoke test in M1 and iterative tmpfs additions if needed.

4. **CI environment differences:** Tests pass locally but fail in GitHub Actions due to path, dependency, or timing differences. Mitigated by using the same Python/Node versions and running tests in CI early (M9).

5. **Scope creep in test writing:** Testing milestone could expand significantly. Mitigated by scoping tests to new code only and keeping mock complexity low.

---

## Sign-Off

- [x] Lead Engineer (Gandalf) — approved 2026-03-30
- [x] Product Manager (Aragorn) — approved 2026-03-30
- [x] Stakeholder (User) — approved 2026-03-30

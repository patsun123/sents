# V1 Gap Closure — Build Progress

**Last updated:** 2026-03-30
**Status:** BUILD COMPLETE — All milestones M1-M10 implemented

---

## Spec Phase: COMPLETE

All four spec layers approved and signed off:

| Layer | File | Status |
|-------|------|--------|
| Requirements | `docs/specs/requirements.md` | APPROVED |
| Design | `docs/specs/design.md` | APPROVED |
| Architecture | `docs/specs/architecture.md` | APPROVED |
| Plan | `docs/specs/plan.md` | APPROVED |

---

## Build Phase Progress

### M1: Infrastructure Hardening — COMPLETE

Files modified:
- `.env` / `.env.example` — added `REDIS_PASSWORD`, updated `REDIS_URL`
- `docker-compose.yml` — Redis `--requirepass`, `read_only: true` + `tmpfs`, `db-backup` service, Docker healthchecks
- `database/backup.sh` — pg_dump backup script with retention
- `database/init.sql` — weighting params in `pricing_configurations` seed data, UPDATE grant for `sse_scraper`

### M2: Quality Filtering + Text Preprocessor — COMPLETE

Files modified:
- `scraper/src/scraper/reddit/client.py` — `_should_skip()` quality filter (existed from M1 scaffold)
- `scraper/src/scraper/config.py` — `bot_usernames`, `min_content_length` config fields
- `processor/src/processor/pipeline/pipeline.py` — processor-side SQL filtering (deleted/bot/min-length), `preprocess()` integration
- `scraper/src/scraper/storage/db.py` — content_fingerprint duplicate detection after batch insert
- `processor/src/processor/text/` — slang_dict.py, emoji_map.py, preprocessor.py (existed from M1 scaffold)

### M3: Comment Scraping — COMPLETE

Files modified:
- `scraper/src/scraper/reddit/client.py` — `RedditComment` dataclass + `fetch_comments()` (existed from M1 scaffold)
- `scraper/src/scraper/scheduler/__init__.py` — comment fetching for top-10 posts per cycle, 1s throttling
- `scraper/src/scraper/storage/db.py` — `store_comments()` function for `post_type='comment'` storage

### M4: NLP Weighting Model — COMPLETE

Files modified:
- `processor/src/processor/pipeline/pipeline.py` — `aggregate_sentiment_snapshot()` replaced AVG with weighted aggregation (upvote ln-weight + temporal decay via CROSS JOIN LATERAL)
- `backend/app/api/v1/endpoints/tickers.py` — clarifying comment on weighted_mention_count semantics

### M5: Service Resilience — COMPLETE

Files modified:
- `scraper/src/scraper/health.py` — HealthServer (stdlib http.server, existed from M1)
- `processor/src/processor/health.py` — HealthServer for processor
- `pricing_engine/src/pricing_engine/health.py` — HealthServer for pricing engine
- `processor/src/processor/main.py` — health server integration, dual-mode (event-driven + poll fallback), Redis reconnect loop, graceful degradation without Redis
- `pricing_engine/src/pricing_engine/main.py` — health server integration, record_success on cycles
- `backend/app/main.py` — slowapi limiter setup + RateLimitExceeded handler
- `backend/app/api/v1/endpoints/market.py` — `@limiter.limit("60/minute")`
- `backend/app/api/v1/endpoints/tickers.py` — `@limiter.limit("60/minute")`
- `backend/app/api/v1/endpoints/stream.py` — `@limiter.limit("10/minute")` on SSE endpoints
- `backend/app/api/v1/endpoints/pricing.py` — `@limiter.limit("60/minute")`
- `backend/pyproject.toml` — added `slowapi>=0.1.9` dependency

### M6: Frontend Charts — COMPLETE

Files modified/created:
- `backend/app/api/v1/endpoints/market.py` — sparkline LATERAL subquery (last 24 sentiment prices)
- `backend/app/schemas/__init__.py` — `sparkline: list[float] = []` on TickerSummary
- `frontend/src/types/api.ts` — `sparkline: number[]` on TickerSummary
- `frontend/src/components/SparklineChart.tsx` — NEW: Canvas-based 80x32px sparkline with HiDPI
- `frontend/src/components/DivergenceGauge.tsx` — NEW: visual bar gauge (sm/md sizes)
- `frontend/src/components/ChartLegend.tsx` — NEW: configurable legend (solid/dashed/dotted)
- `frontend/src/components/MarketTable.tsx` — replaced Delta column with Trend (sparkline) + Divergence (gauge)
- `frontend/src/components/TickerDetail.tsx` — DivergenceGauge (md) in header, ChartLegend below chart
- `frontend/src/hooks/useTickerSSE.ts` — V1 design comment (query invalidation approach)

### M7: Continuous Aggregate Optimization — COMPLETE

Files modified:
- `backend/app/api/v1/endpoints/tickers.py` — replaced f-string raw table query with static per-timeframe SQL reading from `sentiment_prices_1h` continuous aggregate (1d: direct, 1w: daily re-agg, 1m: weekly re-agg)

### M8: Testing — COMPLETE

Files created:
- `scraper/tests/` — conftest.py, test_quality_filter.py (6 tests), test_reddit_client.py (7 tests)
- `processor/tests/` — conftest.py, test_preprocessor.py (6 tests), test_vader.py (4 tests), test_textblob.py (3 tests)
- `pricing_engine/tests/` — conftest.py, test_config_loading.py (1 test), test_formula.py (pre-existing, comprehensive)
- `frontend/src/test/setup.ts` — jest-dom setup
- `frontend/src/components/__tests__/` — SparklineChart.test.tsx (3), DivergenceGauge.test.tsx (5), ChartLegend.test.tsx (2)
- `frontend/src/hooks/__tests__/useSSE.test.ts` (1)

Dependencies added:
- `scraper/pyproject.toml` — aioresponses dev dep
- `processor/pyproject.toml` — fakeredis dev dep
- `pricing_engine/pyproject.toml` — fakeredis dev dep
- `frontend/package.json` — vitest, @testing-library/react, @testing-library/jest-dom, jsdom

### M9: GitHub Actions CI — COMPLETE

Files created:
- `ruff.toml` — project-wide linter/formatter config (py311, line-length 100)
- `.github/workflows/ci.yml` — 4 jobs: lint (ruff), test-backend (matrix: scraper/processor/pricing_engine), test-frontend (vitest), build-frontend

### M10: Documentation — COMPLETE

Files created:
- `docs/architecture-overview.md` — system diagram, service descriptions, data flow, Redis channels, DB tables, pricing formula
- `docs/local-dev-setup.md` — prerequisites, quick start, env vars, common commands, troubleshooting
- `docs/operations-runbook.md` — DB reset, service restart, logs, health checks, backup/restore, Redis inspection
- `docs/security.md` — DB roles, Redis auth, container hardening, network model, rate limiting, V1 limitations

---

## Dependency Order (all complete)

```
M1 (DONE) ──► M2 (DONE) ──► M3 (DONE) ──► M4 (DONE) ──► M6 (DONE)
                                                        ──► M7 (DONE)
M1 (DONE) ──► M5 (DONE)
                                         All ──► M8 (DONE) ──► M9 (DONE) ──► M10 (DONE)
```

Parallel execution: M2+M5 (wave 1), M6+M7 (wave 4), M8-backend+M8-frontend (wave 5).

# Test Plan — Sentiment Stock Exchange (SSE)

## Scope

This document defines the **system-level test plan** to be executed after all implementation tasks are complete. It is distinct from task-level acceptance criteria and automated test suites defined in the implementation plans. Its purpose is to verify the assembled system satisfies the spec end-to-end.

**In scope:** all V1 functionality across the full stack in a production-equivalent environment.
**Out of scope:** future features (trading, leaderboards, expanded tickers), cross-browser matrix beyond Chrome, and chaos engineering beyond the resilience scenarios listed.

---

## Environments

| Environment | Purpose | Data |
|---|---|---|
| **Local** (`make dev`) | Developer smoke tests during implementation | Seeded fake data |
| **Staging** (DigitalOcean droplet, `staging.*`) | Pre-production acceptance testing | Real Reddit + market data |
| **Production** (`sse.io` or equivalent) | Post-deploy verification only | Live data |

All test suites below run against **Staging** unless marked *(local only)* or *(production only)*.

---

## Test Suite 1: Data Pipeline (End-to-End)

Verifies the full chain: Reddit → DB → Sentiment → Pricing → API → Frontend.

### TP-01: Full pipeline run produces a price update

**Type:** Integration
**Trigger:** Manual — initiate a scraper run
**Steps:**
1. Note current `sentiment_price` for `TSLA` from `GET /api/v1/tickers/TSLA`
2. Trigger a scraper run: `docker compose exec scraper python -m scraper.main --once`
3. Wait for the pipeline to complete (monitor logs: `docker compose logs -f processor pricing api`)
4. Confirm Redis pub/sub chain: `sse:scraper:run_complete` → `sse:sentiment:run_complete` → `sse:pricing:run_complete`
5. Re-call `GET /api/v1/tickers/TSLA`

**Pass criteria:**
- All three Redis channels published within 5 minutes of scraper completion
- `updated_at` timestamp on TSLA response is newer than step 1
- `sentiment_price` value reflects the new run (may or may not change numerically, but `updated_at` must advance)

---

### TP-02: New Reddit post is captured and attributed

**Type:** Integration
**Pre-condition:** Access to a controlled test subreddit or can identify a recent real post by `reddit_id`
**Steps:**
1. Identify a Reddit post containing "TSLA" in body, published within the last hour. Record its `reddit_id`.
2. Run the scraper: `docker compose exec scraper python -m scraper.main --once`
3. Query the DB directly: `SELECT * FROM reddit_raw WHERE reddit_id = '<id>' AND ticker_mentioned = 'TSLA';`

**Pass criteria:**
- Row exists with correct `reddit_id`, `ticker_mentioned = 'TSLA'`, `body` not null, `score` ≥ 0
- `is_duplicate = FALSE`
- `content_fingerprint` is a 64-char hex string

---

### TP-03: Duplicate post is not double-counted

**Type:** Integration
**Steps:**
1. Run the scraper twice back-to-back without waiting for new posts: `--once` flag twice
2. Query: `SELECT COUNT(*) FROM reddit_raw WHERE reddit_id = '<known_id>' AND ticker_mentioned = 'TSLA';`

**Pass criteria:**
- COUNT = 1 (composite UNIQUE enforced; second run is a no-op upsert, not an insert)
- `score` on the row reflects the most recent value (upsert updates it)

---

### TP-04: Near-duplicate content fingerprinting

**Type:** Integration
**Steps:**
1. Insert two rows with the same body text but different `reddit_id` values directly into `reddit_raw`
2. Run the deduplication filter logic (or trigger a pipeline run)
3. Query: `SELECT reddit_id, is_duplicate FROM reddit_raw WHERE content_fingerprint = '<sha>';`

**Pass criteria:**
- The second row has `is_duplicate = TRUE`
- Only the first row is included in subsequent sentiment analysis

---

### TP-05: Pipeline handles scraper downtime gracefully

**Type:** Resilience
**Steps:**
1. Stop the scraper: `docker compose stop scraper`
2. Wait 35 minutes (past the 30-minute staleness warning threshold)
3. Call `GET /api/v1/tickers`

**Pass criteria:**
- All tickers still return data (prices are held, not zeroed)
- `staleness_level` is `"warning"` or higher for all tickers
- No 500 errors from the API

---

## Test Suite 2: Sentiment Analysis

### TP-06: Sentiment scores fall within expected range

**Type:** Validation
**Steps:**
1. After a pipeline run, query: `SELECT MIN(sentiment_score), MAX(sentiment_score), AVG(sentiment_score) FROM sentiment_scores WHERE created_at > NOW() - INTERVAL '1 hour';`

**Pass criteria:**
- `MIN` ≥ -1.0, `MAX` ≤ 1.0
- At least one positive and one negative score present (not all zero)
- `AVG` is not NaN or NULL

---

### TP-07: FinBERT escalation activates correctly

**Type:** Functional
**Pre-condition:** VADER accuracy threshold configured at 70% (default)
**Steps:**
1. Run the validation CLI: `docker compose exec processor python validate.py --backend vader --dataset tests/fixtures/labeled_posts.csv`
2. Note accuracy. If < 70%, confirm FinBERT auto-selected.
3. Check logs: `docker compose logs processor | grep "backend"`

**Pass criteria:**
- Validation report written to `reports/validation_YYYYMMDD.json`
- If VADER accuracy < threshold, logs show `"Escalating to FinBERT"`
- FinBERT model loads without OOM error on the 4GB droplet

---

### TP-08: Pre-analysis caching skips already-scored posts

**Type:** Performance / Correctness
**Steps:**
1. Run the pipeline once (populates `sentiment_scores`)
2. Run again immediately: `docker compose exec processor python -m processor.main --once`
3. Check logs for `comments_skipped_cached` counter

**Pass criteria:**
- `comments_skipped_cached` > 0 on the second run (not re-analyzing already-scored posts)
- Second run completes faster than the first

---

## Test Suite 3: Pricing Engine

### TP-09: Sentiment price formula is applied correctly

**Type:** Functional
**Steps:**
1. From the DB, get a known ticker's `real_price` and `sentiment_delta`:
   ```sql
   SELECT real_price, sentiment_delta, sentiment_price
   FROM pricing_history
   WHERE ticker = 'TSLA'
   ORDER BY calculated_at DESC
   LIMIT 1;
   ```
2. Verify: `sentiment_price = real_price + sentiment_delta`

**Pass criteria:**
- Formula holds to 2 decimal places for all 6 seed tickers in the latest pricing row

---

### TP-10: Pricing bootstraps correctly on first boot

**Type:** Functional
**Steps:**
1. Wipe the `pricing_history` table: `TRUNCATE pricing_history;`
2. Restart the pricing engine: `docker compose restart pricing`
3. Wait 60 seconds. Call `GET /api/v1/tickers/TSLA`

**Pass criteria:**
- Response returns `sentiment_price` equal to `real_price` (bootstrap: `sentiment_delta = 0`)
- No 404 or 500 response
- Subsequent pipeline run produces a non-zero `sentiment_delta`

---

### TP-11: Real price fetching respects market hours

**Type:** Functional
**Run during:** Market open (NYSE 9:30–16:00 ET, Mon–Fri)
**Steps:**
1. Call `GET /api/v1/tickers/NVDA` during market hours
2. Note `real_price`
3. Wait 10 minutes
4. Call again

**Pass criteria:**
- `real_price` updates within the 5-minute fetch interval during market hours
- During non-market hours (run same test on weekend), `real_price` remains constant (no stale fetch error)

---

## Test Suite 4: API Endpoints

### TP-12: All documented endpoints return correct shape

**Type:** Contract
**Tool:** `curl` or Postman collection

| Endpoint | Expected status | Key fields |
|---|---|---|
| `GET /api/v1/tickers` | 200 | `tickers[]` with 6 items; each has `symbol`, `sentiment_price`, `real_price`, `divergence`, `staleness_level`, `timestamp` |
| `GET /api/v1/tickers/TSLA` | 200 | Single ticker object |
| `GET /api/v1/tickers/FAKE` | 404 | `{"detail": "..."}` JSON body |
| `GET /api/v1/tickers/TSLA/history?timeframe=1D` | 200 | Array of `{timestamp, sentiment_price, real_price}` |
| `GET /api/v1/tickers/TSLA/history?timeframe=1W` | 200 | Same shape, longer range |
| `GET /api/v1/tickers/TSLA/history?timeframe=1M` | 200 | Same shape, longer range |
| `GET /api/v1/tickers/stream` | 200 (SSE) | `Content-Type: text/event-stream` |
| `GET /api/v1/tickers/TSLA/stream` | 200 (SSE) | `Content-Type: text/event-stream` |
| `GET /health` | 200 | `{"status": "ok", ...}` |

**Pass criteria:** All rows pass with correct status codes and JSON shapes.

---

### TP-13: Rate limiting is enforced

**Type:** Security / Functional
**Steps:**
1. Send 70 rapid GET requests to `/api/v1/tickers` within 60 seconds:
   ```bash
   for i in {1..70}; do curl -o /dev/null -s -w "%{http_code}\n" https://staging.example.com/api/v1/tickers; done
   ```

**Pass criteria:**
- First 60 requests return 200
- Requests 61+ return 429
- Response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- 429 body is JSON: `{"detail": "Rate limit exceeded..."}`

---

### TP-14: SSE global stream delivers all tickers on connect

**Type:** Functional
**Steps:**
1. Connect to the global SSE stream: `curl -N https://staging.example.com/api/v1/tickers/stream`
2. Observe the first event

**Pass criteria:**
- First event has `event: all_tickers_snapshot` (or equivalent initial payload type)
- Payload contains all 6 seed tickers with current prices
- Connection stays open (no immediate close)
- After a pipeline run completes, a `price_update` event is received within 10 seconds

---

### TP-15: SSE per-ticker stream filters correctly

**Type:** Functional
**Steps:**
1. Connect to `GET /api/v1/tickers/TSLA/stream`
2. Trigger a pipeline run that produces pricing updates for all tickers
3. Observe events received on the TSLA stream for 2 minutes

**Pass criteria:**
- Only events with `"ticker": "TSLA"` appear on the stream (no NVDA, GME, etc.)
- At least one `price_update` event received per pipeline run

---

### TP-16: `"stream"` is not treated as a ticker symbol

**Type:** Edge case
**Steps:**
1. `GET /api/v1/tickers/stream` — should open SSE
2. `GET /api/v1/tickers/STREAM` (uppercase) — should return 404 (not a real ticker)

**Pass criteria:**
- Request 1 returns `text/event-stream` (global SSE endpoint, registered first)
- Request 2 returns 404 JSON

---

## Test Suite 5: Frontend UI

### TP-17: Homepage renders all 6 tickers

**Type:** E2E
**Tool:** Browser (Chrome) against Staging
**Steps:**
1. Navigate to the staging URL
2. Wait for page to fully load (no spinners)

**Pass criteria:**
- 6 ticker cards visible: TSLA, NVDA, GME, PLTR, SOFI, RIVN
- Each card shows: symbol, real price ($X.XX), sentiment price ($X.XX), sparkline
- No "NaN", "undefined", or "$0.00" values
- Page title is "Sentiment Stock Exchange" (or equivalent)

---

### TP-18: Live price updates appear without page reload

**Type:** E2E / Real-time
**Steps:**
1. Open the homepage
2. Open browser DevTools → Network tab, filter by `EventStream`
3. Confirm SSE connection to `/api/v1/tickers/stream` is open
4. Wait for a pipeline run to complete (~15–30 min, or trigger manually)
5. Observe the homepage

**Pass criteria:**
- At least one `price_update` SSE event visible in DevTools Network tab
- At least one ticker card price updates without any page navigation or reload
- No JavaScript console errors during the update

---

### TP-19: Ticker detail page — all components render

**Type:** E2E
**Steps:**
1. Click on the TSLA ticker card
2. URL should change to `/TSLA` (or `/tickers/TSLA`)

**Pass criteria:**
- Page shows: ticker symbol (TSLA), real price, sentiment price, divergence indicator
- Timeframe selector shows 1D / 1W / 1M buttons; 1D is active by default
- Chart renders with two visible lines (not blank)
- Staleness indicator shows in footer
- Market hours indicator is visible

---

### TP-20: Timeframe switching reloads chart data

**Type:** E2E
**Steps:**
1. On the TSLA detail page, note chart data range (1D default)
2. Click "1W"
3. Click "1M"

**Pass criteria:**
- Each click triggers a new API request to `history?timeframe=1W` / `history?timeframe=1M` (visible in DevTools)
- Chart updates with new data; X-axis range changes visibly
- Loading state appears briefly during fetch
- No JavaScript errors

---

### TP-21: Staleness indicator thresholds display correctly

**Type:** Functional / Visual
**Steps:**
1. With scraper running normally → note staleness indicator color on homepage header
2. Stop the scraper: `docker compose stop scraper`
3. Wait 35 minutes → refresh page
4. Wait 65 minutes total → refresh page

**Pass criteria:**
- Step 1: green "fresh" badge
- Step 3 (~35 min since last update): yellow/orange "warning" badge
- Step 4 (~65 min since last update): red "critical" badge
- Each `TickerSummary.staleness_level` field matches the visual badge

---

### TP-22: Mobile responsive layout

**Type:** UI
**Tool:** Chrome DevTools device emulation
**Viewports to test:** 375px (iPhone SE), 768px (iPad), 1280px (desktop)

**Pass criteria at each viewport:**
- No horizontal scrollbar
- Ticker grid: 1 column at 375px, 2 columns at 768px, 3 columns at 1280px
- All buttons and links have touch targets ≥ 44px
- Chart fills container (no overflow)
- Text legible (≥ 16px body text)
- Header navigation collapses to hamburger at 375px

---

### TP-23: Accessibility — keyboard navigation

**Type:** Accessibility
**Steps:**
1. Load homepage with keyboard only (no mouse)
2. Tab through all interactive elements
3. Press Enter on a TickerCard
4. Tab through detail page

**Pass criteria:**
- All ticker cards reachable via Tab
- Focus indicator visible on each focused element
- Enter on TickerCard navigates to detail page
- No keyboard trap (can Tab out of any component)
- Screen reader announces price direction with text (not color alone)

---

## Test Suite 6: Security

### TP-24: HTTPS enforced — no plaintext traffic

**Type:** Security
**Steps:**
1. `curl -I http://staging.example.com/` (plain HTTP)
2. `curl -I https://staging.example.com/` (HTTPS)
3. `openssl s_client -connect staging.example.com:443` — check certificate

**Pass criteria:**
- HTTP redirects to HTTPS (301 or 302)
- HTTPS returns 200
- Certificate is valid Let's Encrypt cert for the domain
- `Strict-Transport-Security` header present on HTTPS responses

---

### TP-25: Security headers present

**Type:** Security
**Steps:**
1. `curl -I https://staging.example.com/`

**Pass criteria:**
- `X-Frame-Options: DENY` or `SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `Strict-Transport-Security: max-age=...`
- No `Server: nginx/1.x.x` leaking version (suppress with `server_tokens off`)

---

### TP-26: DB credentials not exposed in API responses

**Type:** Security
**Steps:**
1. Call all documented API endpoints
2. Search every response body for patterns: `postgres`, `password`, `secret`, `DB_URL`, `redis://`

**Pass criteria:**
- No credential strings appear in any API response
- Error responses (400, 404, 500) contain only user-friendly messages, not stack traces or connection strings

---

### TP-27: Non-root container users

**Type:** Security
**Steps:**
1. For each running container, check the active user:
   ```bash
   docker compose ps -q | xargs -I{} docker inspect {} --format '{{.Name}} {{.Config.User}}'
   ```

**Pass criteria:**
- No container reports `root` or empty user (empty = root)
- Each service runs as its designated non-root user (TASK-OPS03)

---

## Test Suite 7: Performance & Load

### TP-28: Locust load test — baseline

**Type:** Performance
**Tool:** `make load-test` (TASK-OPS35)
**Config:** 50 concurrent users, 60-second run, against Staging

**Pass criteria:**
- p95 response time < 500ms for REST endpoints (`GET /tickers`, `GET /tickers/TSLA`, `GET /tickers/TSLA/history`)
- p99 response time < 2000ms for SSE connection establishment
- Error rate < 1%
- No container OOM-kills during the test (check `docker stats`)

---

### TP-29: Sustained load — 1-hour soak test

**Type:** Performance / Resilience
**Config:** 20 concurrent users, 60-minute run (run outside of CI — manual only)

**Pass criteria:**
- No memory leak (Processor container memory stays stable, not growing over time)
- No database connection exhaustion (`pg_stat_activity` connections stay below limit)
- Error rate stays < 1% for the full hour
- No container restarts triggered

---

## Test Suite 8: Resilience & Recovery

### TP-30: Database connection lost and recovered

**Type:** Resilience
**Steps:**
1. Stop PostgreSQL: `docker compose stop postgres`
2. Call `GET /api/v1/tickers` — note error response
3. Start PostgreSQL: `docker compose start postgres`
4. Wait 30 seconds. Call `GET /api/v1/tickers` again

**Pass criteria:**
- Step 2 returns a structured error (503 or 500) with JSON body — not a stack trace or connection string
- Step 4 returns 200 with data (API reconnects automatically — no manual restart required)
- Upstream services (Scraper, Processor) also reconnect automatically

---

### TP-31: Redis connection lost and recovered

**Type:** Resilience
**Steps:**
1. Stop Redis: `docker compose stop redis`
2. Trigger a scraper run — it should complete without publishing to Redis
3. Start Redis: `docker compose start redis`
4. Trigger another scraper run

**Pass criteria:**
- Scraper run with Redis down completes without crashing (logs an error, continues)
- After Redis recovers, next scraper run publishes to Redis and triggers full pipeline chain
- Active SSE clients reconnect within 60 seconds (exponential backoff capped at 60s)

---

### TP-32: Container crash and auto-restart

**Type:** Resilience
**Steps:**
1. Kill the API container forcefully: `docker compose kill api`
2. Wait 10 seconds
3. Call `GET /health`

**Pass criteria:**
- Docker restarts the API automatically (`restart: unless-stopped`)
- `/health` returns 200 within 30 seconds of the kill
- No manual intervention required

---

### TP-33: Droplet reboot — full stack recovers

**Type:** Resilience / DR
**Steps:**
1. Reboot the staging droplet: `sudo reboot`
2. Wait for droplet to come back online (~2 minutes)
3. Call `GET /health`
4. Call `GET /api/v1/tickers`

**Pass criteria:**
- All 9 services start automatically on boot (Docker daemon + Compose `restart: unless-stopped`)
- `/health` returns 200 within 3 minutes of reboot
- All tickers return data (prices held from before reboot)
- No manual `docker compose up` required

---

## Test Suite 9: Monitoring & Observability

### TP-34: Uptime Kuma dashboard is operational

**Type:** Functional
**Steps:**
1. Navigate to the Uptime Kuma web UI
2. Review monitor statuses

**Pass criteria:**
- Monitors present for: API `/health`, Frontend, PostgreSQL, Redis, Scraper `/health`
- All monitors show green (up) in steady state
- Check interval ≤ 5 minutes for all monitors

---

### TP-35: Staleness alert fires correctly

**Type:** Monitoring
**Steps:**
1. Stop the scraper: `docker compose stop scraper`
2. Wait 50 minutes (past the 45-minute Uptime Kuma staleness monitor threshold)

**Pass criteria:**
- Uptime Kuma alert fires (email or Discord/Slack notification received)
- Alert message identifies which service/monitor triggered it

---

### TP-36: Structured logs are parseable

**Type:** Observability
**Steps:**
1. `docker compose logs --no-color scraper | head -20`
2. Pipe to `jq`: `docker compose logs --no-color scraper | head -5 | jq .`

**Pass criteria:**
- Every log line is valid JSON
- Each entry contains: `timestamp`, `level`, `service_name`, `message`
- No unformatted Python tracebacks in production logs (tracebacks should be nested in structured fields)

---

## Test Execution Checklist

Use this checklist before marking the system ready for production.

### Automated (run in CI)
- [ ] `pytest` — all Python unit + integration tests green (TASK-CI03, TASK-CI04)
- [ ] `npm test -- --run` — all Vitest + RTL tests green (TASK-CI06)
- [ ] `tsc --noEmit` — no TypeScript errors
- [ ] `make load-test` — Locust p95 < 500ms, error rate < 1% (TP-28)

### Manual — Staging (run before first production deploy)
- [ ] TP-01: Full pipeline run produces a price update
- [ ] TP-02: New Reddit post is captured
- [ ] TP-03: Duplicate post is not double-counted
- [ ] TP-05: Pipeline handles scraper downtime gracefully
- [ ] TP-09: Pricing formula is applied correctly
- [ ] TP-12: All API endpoints return correct shapes
- [ ] TP-13: Rate limiting enforced
- [ ] TP-14: SSE global stream delivers initial snapshot
- [ ] TP-17: Homepage renders all 6 tickers
- [ ] TP-18: Live price updates appear without page reload
- [ ] TP-21: Staleness indicator thresholds display correctly
- [ ] TP-22: Mobile responsive layout at 375/768/1280px
- [ ] TP-24: HTTPS enforced
- [ ] TP-25: Security headers present
- [ ] TP-26: No credentials in API responses
- [ ] TP-27: Non-root container users verified
- [ ] TP-30: DB loss and recovery
- [ ] TP-33: Droplet reboot — full stack recovers
- [ ] TP-34: Uptime Kuma dashboard operational
- [ ] TP-36: Structured logs are parseable

### Manual — Periodic (after go-live)
- [ ] TP-29: 1-hour soak test — run monthly
- [ ] TP-35: Staleness alert fires — verify after any monitoring config change
- [ ] Security re-scan (`trivy` or `docker scout`) — run quarterly (TASK-OPS30)
- [ ] DR test (restore from backup to new droplet) — run quarterly (TASK-OPS31)

---

## Defect Classification

| Severity | Definition | Examples | Target resolution |
|---|---|---|---|
| **P1 — Critical** | System is down or data is wrong/missing | Prices show $0, pipeline not running, DB corrupt | Before go-live / same day |
| **P2 — High** | Major feature broken but system is up | SSE not delivering updates, chart blank, staleness wrong | Within 1 sprint |
| **P3 — Medium** | Minor feature degraded | Sparkline missing, wrong color, slow load | Within 2 sprints |
| **P4 — Low** | Cosmetic or polish | Alignment off, label truncated | Backlog |

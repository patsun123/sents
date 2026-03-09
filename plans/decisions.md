# Open Decisions — Spec §13 Unresolved Questions

This document records spec §13 open questions that have no implementation task and require a human decision before or during development. None are blockers for V1 development to begin.

---

## DECISION-1: Domain Name

**Spec question:** "What domain name should be used for the live deployment?"

**Status:** Unresolved — human decision required before TASK-OPS17 (Let's Encrypt TLS) can be completed.

**Options:**
- `sentimentstockexchange.com` — matches project name exactly; likely available
- `sse.io` — short; check availability (the `sse_io` repo name suggests this is preferred)
- `ssemarket.io` / `sseapp.io` — alternatives if primary is taken

**Impact:** Affects TASK-OPS17 (Certbot domain config), TASK-OPS16 (Nginx `server_name`), Uptime Kuma monitors (TASK-OPS20), and any future SEO work.

**Action required:** Register domain before first production deployment. Update `DOMAIN=` in `.env.example` (TASK-OPS14).

---

## DECISION-2: SEO and Public Discoverability

**Spec question:** "Should the app be publicly indexed by search engines?"

**Status:** Unresolved — no task exists for SEO.

**Context:** The frontend is a React SPA (Vite + React Router). Single-page apps render content client-side; search engine crawlers see an empty `<div id="root">` unless server-side rendering (SSR) or prerendering is configured.

**Options:**

| Option | Effort | SEO quality | Notes |
|---|---|---|---|
| **Do nothing** | None | Poor | Fine if the app is a portfolio/demo not intended for search discovery |
| **Add `<meta>` tags + `sitemap.xml`** | Low | Minimal | Googlebot handles SPAs reasonably; sufficient for low-traffic hobby project |
| **Static prerender** (`vite-plugin-ssr` or `react-snap`) | Medium | Good | Pre-generates HTML at build time for key routes; no server required |
| **Full SSR** (Next.js / Remix) | High | Best | Requires migrating off Vite; out of scope for V1 |

**Recommendation:** If SSE is a portfolio/demo project, do nothing for V1. Add a `<title>` and basic `<meta description>` at minimum. Revisit if public traffic is a goal.

**Action required:** Owner decides before TASK-FE01 scaffolding if SSR migration is needed (otherwise it's costly to retrofit).

---

## DECISION-3: Proxy Service Selection

**Spec question:** "Which proxy provider / rotation strategy should be used for scraping?"

**Status:** Unresolved — TASK-S06 assumes a proxy pool exists but does not evaluate providers.

**Context:** The scraper plan (TASK-S05–S13) implements proxy rotation, user-agent cycling, and jitter. The implementation depends on a `PROXY_POOL_URLS` environment variable. The *selection* of a proxy provider is not in any task.

**Options:**

| Provider | Cost | Quality | Notes |
|---|---|---|---|
| **No proxy (direct)** | Free | ⚠️ IP ban risk | Suitable for local dev and low-volume testing |
| **Bright Data (Luminati)** | ~$500/mo residential | Excellent | Overkill for hobby project |
| **Webshare.io** | ~$5/mo for 10 shared proxies | Acceptable | Good entry-level; supports HTTP/SOCKS5 |
| **ScraperAPI** | ~$49/mo for 250k req | Good | Handles rotation internally; simpler integration |
| **Oxylabs** | Custom pricing | Excellent | Enterprise tier |

**Recommendation for V1:** Start with **no proxy** for development. Use **Webshare.io** (shared proxies, $5/mo) for staging/production as a cost-effective starting point. Upgrade to residential proxies if Reddit blocks the IP.

**Action required:** Select provider before TASK-S06 is implemented. Add `PROXY_POOL_URLS` to `.env.example` (TASK-OPS14) with chosen format.

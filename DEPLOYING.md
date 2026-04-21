# Deploying SentiX

**This project has a split-deploy architecture.** The API, database, and static site live on a DigitalOcean droplet. The Reddit scraper runs on an always-on machine at home (currently a Windows laptop named `rx123`). The two talk over a private Tailscale mesh. This doc is the prescriptive recipe for pushing changes to production.

If you are a fresh agent / contributor who hasn't touched this repo before, read the whole file. If you've done it once, skim to "TL;DR".

## Key facts you will need

| Thing | Value |
|---|---|
| GitHub repo | `patsun123/sents` |
| Production URL | https://sentix.yetanothertracker.com |
| Droplet public IPv4 | `143.110.153.39` |
| Droplet Tailscale IP | `100.75.109.50` |
| Home machine Tailscale IP | `100.112.86.118` (hostname `rx123`) |
| Deploy SSH key path | `~/.ssh/sents-deploy` (private key) |
| Deploy user on droplet | `deploy` (NOPASSWD sudo in docker group) |
| Repo path on droplet | `/home/deploy/sents` |
| GitHub Actions secrets | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_SSH_PORT` (all already set) |

## TL;DR — push a code change to prod

For 95% of changes (API endpoints, dashboard HTML, CSS, worker logic, config):

```bash
# 1. Branch and commit
git checkout -b my-change
# ... edit files ...
git add -A && git commit -m "descriptive message"
git push -u origin my-change

# 2. Open and merge the PR
gh pr create --base main --title "my-change" --body "what it does"
PR=$(gh pr list --head my-change --json number --jq '.[0].number')
gh pr merge $PR --merge

# 3. Watch the auto-deploy
sleep 5
RUN_ID=$(gh run list --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID

# 4. Verify
curl -s https://sentix.yetanothertracker.com/api/epic/overview

# 5. If the change touched worker/, ALSO redeploy the home worker (see "Worker changes")
```

Deploy takes 90–120 seconds. When `gh run watch` exits with `✓`, the site is live AND has passed automated smoke tests.

## Workflow structure

The deploy workflow `.github/workflows/deploy.yml` has **three jobs running in sequence**:

1. **`validate`** (runs on GitHub runner, no SSH) — `docker compose config --quiet` with test values, `caddy validate` on the Caddyfile, `py_compile` on `api/src/main.py`. If this fails, the droplet is not touched and the previous version stays live.
2. **`deploy`** (SSHes to droplet) — checks the droplet's `.env` has `POSTGRES_PASSWORD`, `DOMAIN`, `TAILSCALE_IP` set, `git reset --hard origin/main`, rebuilds the stack, reloads Caddy, stops any orphan worker container.
3. **`smoke-tests`** (runs on GitHub runner, no SSH) — hits the public URL exactly like a browser would. Asserts HTTP 200, expected JSON shape on API endpoints, 400 on invalid lookback, robots.txt + X-Robots-Tag block indexing, TLS cert valid >24h.

If a later job fails, the earlier ones have already committed their changes — no auto-rollback. `git revert <SHA> && git push` is the manual remediation.

## Architecture (why things are structured this way)

```
                                 GitHub (main branch)
                                        │
           ┌────────────────────────────┼──────────────────────────────┐
           │ auto on push to main       │ manual `git pull` + rebuild  │
           │                            │                              │
           ▼                            │                              ▼
 ┌─────────────────────────┐            │          ┌──────────────────────────────┐
 │ Droplet  sfo3           │            │          │ Home machine (rx123)         │
 │ public  143.110.153.39  │            │          │ Tailscale 100.112.86.118     │
 │ tailnet 100.75.109.50   │            │          │                              │
 │                         │            │          │  worker (Reddit scraper)     │
 │  api (FastAPI on :8000) │            │          │  fetches /r/*/new/.json from │
 │  postgres (TS-only:5432)│◀───────────┼──────────│  residential IP, writes      │
 │  redis                  │            │          │  signals over Tailscale to   │
 │  caddy (80/443, LE TLS) │            │          │  droplet postgres            │
 └─────────────────────────┘            │          └──────────────────────────────┘
              ▲                         │
              │                         │
     https://sentix.yetanothertracker.com
```

Why this split:
- **Reddit blocks DigitalOcean's datacenter ASN** on its public `.json` endpoint. Every scrape from the droplet came back HTTP 403. The worker was moved to a residential IP; Reddit serves that happily.
- **Postgres is NOT reachable from the public internet.** Docker binds it to `100.75.109.50:5432` (the droplet's Tailscale interface). Only peers on the tailnet can connect. The home worker uses this.
- **The droplet only hosts the "reader" path** (api, db, cache, TLS). It does no scraping.

## Standard deploy flow (detailed)

### 1. Work in a branch, never on `main`

```bash
git checkout main
git pull
git checkout -b feat/whatever
```

### 2. Files that matter

| File | Affects | Who restarts |
|---|---|---|
| `api/src/main.py` | API endpoints, SQL, dashboard rendering | Droplet auto-deploy |
| `api/src/epic_dashboard.html` | Live dashboard UI (served at `/` and `/epic`) | Droplet auto-deploy |
| `api/src/dashboard.html` | Steam dashboard at `/steam` | Droplet auto-deploy |
| `api/Dockerfile` | API container build | Droplet auto-deploy |
| `docker-compose.yml` | Base services shared by home + droplet | Droplet auto-deploy; home needs `up -d` |
| `docker-compose.prod.yml` | Droplet-only: caddy, postgres port binding | Droplet auto-deploy |
| `docker-compose.home.yml` | Home-only: worker DATABASE_URL override | Home needs `up -d` |
| `Caddyfile` | TLS, robots, reverse-proxy | Droplet auto-deploy (Caddy reloads config gracefully) |
| `deploy/caddy-static/**` | `robots.txt` etc. served by Caddy | Droplet auto-deploy |
| `.github/workflows/deploy.yml` | The deploy workflow itself | Next run picks up changes |
| `worker/src/**` | Worker scraper, classifier, storage | **Home machine manual rebuild** (see below) |
| `worker/Dockerfile` | Worker image build | **Home machine manual rebuild** |
| `worker/migrations/**` | Alembic DB migrations | Applied automatically when worker starts up |

### 3. Commit and push

```bash
git add -A
git commit -m "descriptive message"
git push -u origin feat/whatever
```

The commit hook runs a markdown UTF-8 encoding check — if it complains, the file has a BOM; resave without BOM or pass `-Encoding utf8NoBOM` in PowerShell.

### 4. Open a PR

```bash
gh pr create --base main --head feat/whatever \
  --title "short imperative title" \
  --body "what this does and why"
```

### 5. Merge — this is what triggers deploy

```bash
gh pr merge <PR-number> --merge
```

The workflow `.github/workflows/deploy.yml` fires on every push to `main` (including merge commits). It:

1. SSHes to the droplet as `deploy@143.110.153.39`
2. Runs `git fetch origin main && git reset --hard origin/main` in `~/sents`
3. Runs `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans`
4. Issues `caddy reload --force` so Caddyfile changes apply without dropping TLS connections
5. Runs `docker compose ... rm -sf worker` — the worker is profile-gated off on the droplet, so this cleans up any stale container

### 6. Watch the deploy

```bash
sleep 5  # let the webhook propagate
RUN_ID=$(gh run list --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID
```

A successful deploy takes 90–120 seconds. `gh run watch` exits `0` on success.

### 7. Verify the site is healthy

The workflow now includes an automated `smoke-tests` job that asserts all of the below for you. If the workflow ends green, these are all true:

- Site root returns HTTP 200
- Dashboard HTML has A + C layouts, timeframe toggle, chart library
- `/api/epic/overview` returns JSON with expected keys
- `/api/epic/sentiment-history?lookback=1mo` returns a data array
- `/api/epic/communities?lookback=1mo` returns an array
- Invalid `?lookback=bogus` is rejected with HTTP 400
- `robots.txt` + `X-Robots-Tag` indexing blocks are present
- TLS certificate is valid for at least 24 more hours

If the `smoke-tests` job goes red, investigate before trusting the deploy. Manual spot-checks:

```bash
curl -sI https://sentix.yetanothertracker.com/ | head -1
curl -s https://sentix.yetanothertracker.com/api/epic/overview
curl -s https://sentix.yetanothertracker.com/robots.txt
curl -sI https://sentix.yetanothertracker.com/ | grep -i x-robots-tag
```

## Worker changes (SPECIAL CASE — DO NOT SKIP)

Worker code lives in `worker/src/**`. Changes go through the same PR → main flow so the repo stays the single source of truth. **But merging does NOT restart the running worker — the worker runs on the home machine, not the droplet.**

After merging a worker change, redeploy the home worker manually. In PowerShell on the home Windows machine (`rx123`):

```powershell
cd D:\github\sse_io
git pull origin main
docker compose --profile embedded-worker -f docker-compose.yml -f docker-compose.home.yml build worker
docker compose --profile embedded-worker -f docker-compose.yml -f docker-compose.home.yml up -d worker
```

Verify it booted with the new code:

```powershell
docker compose --profile embedded-worker -f docker-compose.yml -f docker-compose.home.yml logs -f worker
# Look for:
#   worker_starting log_level=INFO
#   migrations_applied output=...
#   scheduler_started cycle_interval_minutes=15
# Then within 15 minutes:
#   cycle_complete status=success signals_stored=N
```

If you forget this step, the droplet runs the new API code against data being collected by the OLD worker code. That's usually fine but causes confusion if the schema changed.

## Common failures

### "Deploy workflow failed"

```bash
gh run view <RUN_ID> --log-failed | tail -40
```

Most common causes:
- **Missing `.env` variable on the droplet** (e.g. `POSTGRES_PASSWORD`, `DOMAIN`, `TAILSCALE_IP`). SSH in, `cat ~/sents/.env`, add the missing line, re-run deploy manually via `gh workflow run deploy.yml`.
- **Docker out of disk space.** SSH in, `docker system prune -a -f`. Droplet has 50GB; pruning dead images usually recovers a few GB.
- **Tailscale down on droplet.** `sudo systemctl restart tailscaled` on the droplet; postgres will bind once Tailscale's interface comes back up.

### "Site is down (502 or connection refused)"

```bash
ssh -i ~/.ssh/sents-deploy deploy@143.110.153.39
cd ~/sents
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50
```

Usually one container is restarting in a crash loop. Read its logs (`docker compose logs api --tail=100`) for a traceback.

### "Site is up but data is stale / no new signals"

The home worker probably died. On the home machine:

```powershell
docker compose --profile embedded-worker -f docker-compose.yml -f docker-compose.home.yml ps
docker compose --profile embedded-worker -f docker-compose.yml -f docker-compose.home.yml logs worker --tail=50
```

If the container is missing: `docker compose ... up -d worker`. If it's crashing: read the logs. The most common cause is a Tailscale hiccup — check `tailscale status` shows `sents-prod` connected.

### "Chart is blank / dashboard looks broken"

Open browser DevTools, check the Console tab for errors, and the Network tab for 4xx/5xx responses from `/api/epic/*`. If the API returns 400 on sentiment-history, the `lookback` parameter isn't in the valid set (`1d`, `7d`, `1mo`, `3mo`, `6mo`, `1y`).

## Rollback

If a bad commit lands on `main`:

**Option A (preferred): revert via git.** Creates a new commit that undoes the bad one, which the deploy workflow will push out like any other change:
```bash
git checkout main && git pull
git revert <BAD-SHA>
git push origin main
# deploy fires; verify at the URL
```

**Option B (emergency): pin the droplet to a known-good sha.** Use only if main is wedged and you need the site back *now*:
```bash
ssh -i ~/.ssh/sents-deploy deploy@143.110.153.39
cd ~/sents
git log --oneline -10   # find a good sha
git reset --hard <GOOD-SHA>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans
```
**Important:** the next merge to main will reintroduce the bad commit unless you also revert in git. Option A is always better long-term.

## Manually trigger a deploy

If you need to redeploy without a code change (e.g. you changed `.env` on the droplet and want it picked up):

```bash
gh workflow run deploy.yml
sleep 5
gh run watch $(gh run list --workflow=deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Or manually from the droplet (bypasses GitHub Actions):
```bash
ssh -i ~/.ssh/sents-deploy deploy@143.110.153.39
cd ~/sents
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans
```

## Database migrations

Migrations live in `worker/migrations/versions/`. They're applied by the worker on startup (`alembic upgrade head`). You don't run them manually — the next time the home worker boots, it runs them against the droplet's postgres over Tailscale.

**To write a new migration:**
```bash
cd worker
alembic revision -m "describe the change"
# edit the new file under migrations/versions/
```

Commit the new file through the normal PR flow. After merging, redeploy the home worker (see "Worker changes"). The migration runs automatically on next startup.

**To check what migration is applied:**
```bash
ssh -i ~/.ssh/sents-deploy deploy@143.110.153.39
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  psql -U sentix sentix -c "SELECT version_num FROM alembic_version;"
```

## Things NOT to do

- **Don't edit files directly on the droplet.** The deploy does `git reset --hard origin/main` and wipes local changes. If you need a one-off fix, commit it to the repo.
- **Don't push directly to `main`.** Always PR. The deploy still runs, but you lose the diff review and a recorded reason for the change.
- **Don't run `docker compose down -v` anywhere.** The `-v` flag deletes volumes. On the droplet that means wiping the postgres data directory — you lose every signal ever collected. To restart, use `docker compose restart <service>` or `up -d --force-recreate <service>`.
- **Don't commit `.env` files.** They're gitignored for good reason. If you need to document a new env var, update `.env.example`.
- **Don't rotate `POSTGRES_PASSWORD` on the droplet without also updating the home machine's `.env`.** The worker uses that password to authenticate. Mismatch = worker crash-loops with `password authentication failed`.
- **Don't add new Docker services without thinking about the split.** Anything that needs Reddit access must run on the home machine (behind the `embedded-worker` profile or a new home-specific override). Anything user-facing runs on the droplet.
- **Don't bypass the `embedded-worker` profile** by adding the worker back to the default compose services — it will start on the droplet, immediately start 403-ing, and drown the logs.

## Environment secrets reference

On the droplet (`/home/deploy/sents/.env`):
```
POSTGRES_PASSWORD=<43-char random string>   # matches home .env
DOMAIN=sentix.yetanothertracker.com         # used by Caddy for TLS
TAILSCALE_IP=100.75.109.50                  # used by docker-compose.prod.yml to bind postgres
# Optional:
SENTRY_DSN=<if you want error tracking>
REDDIT_CLIENT_ID=<if PRAW OAuth lane configured — not needed>
REDDIT_CLIENT_SECRET=...
REDDIT_USERNAME=...
REDDIT_PASSWORD=...
```

On the home machine (`D:\github\sse_io\.env`):
```
POSTGRES_PASSWORD=<same as droplet>
DROPLET_TAILSCALE_IP=100.75.109.50
CLASSIFIER_BACKEND=epic_rules
CYCLE_INTERVAL_MINUTES=15
ALERT_THRESHOLD=3
LOG_LEVEL=INFO
```

GitHub Actions secrets (already set, visible via `gh secret list`):
- `DEPLOY_HOST` = droplet IP
- `DEPLOY_USER` = `deploy`
- `DEPLOY_SSH_KEY` = private key content (matches `~/.ssh/sents-deploy` on dev machine + `~/deploy/.ssh/authorized_keys` on droplet)
- `DEPLOY_SSH_PORT` = optional, defaults to 22

---

When in doubt, follow the TL;DR. If something doesn't match this doc, the doc is probably wrong — update it.

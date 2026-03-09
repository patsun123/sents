.PHONY: help up up-prod down logs build migrate migrate-down db-users shell-db shell-api shell-scraper test test-frontend lint typecheck format e2e clean ps load-test

# Default target
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Docker Compose ────────────────────────────────────────────────────────────
up: ## Start all services (dev mode with override)
	docker compose up --build -d

up-prod: ## Start all services (production — no override)
	docker compose -f docker-compose.yml up --build -d

down: ## Stop and remove containers
	docker compose down

logs: ## Tail logs for all services
	docker compose logs -f

logs-%: ## Tail logs for a specific service (e.g. make logs-api)
	docker compose logs -f $*

restart-%: ## Restart a specific service (e.g. make restart-scraper)
	docker compose restart $*

build: ## Rebuild all images
	docker compose build

# ── Database ──────────────────────────────────────────────────────────────────
migrate: ## Run Alembic migrations (upgrade head)
	docker compose run --rm api alembic -c /app/../../../database/alembic.ini upgrade head

migrate-down: ## Rollback last Alembic migration
	docker compose run --rm api alembic -c /app/../../../database/alembic.ini downgrade -1

db-users: ## Create per-service DB users (run once after DB init)
	docker compose exec postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB \
	  -f /docker-entrypoint-initdb.d/create_users.sql

shell-db: ## Open psql shell in the postgres container
	docker compose exec postgres psql -U $${POSTGRES_USER:-sse_admin} -d $${POSTGRES_DB:-sse}

# ── Development ───────────────────────────────────────────────────────────────
shell-api: ## Open a shell in the api container
	docker compose exec api bash

shell-scraper: ## Open a shell in the scraper container
	docker compose exec scraper bash

# ── Testing ───────────────────────────────────────────────────────────────────
test: ## Run all backend pytest tests
	docker compose run --rm api pytest

test-frontend: ## Run Vitest unit tests
	cd frontend && npm test -- --run

lint: ## Run ruff linter on all Python services
	ruff check scraper/src processor/src pricing_engine/src backend/app sse_common/sse_common

typecheck: ## Run pyright / mypy type checking
	cd frontend && npm run typecheck

format: ## Auto-format Python with ruff
	ruff format scraper/src processor/src pricing_engine/src backend/app sse_common/sse_common

e2e: ## Run Playwright E2E smoke tests (requires running dev stack)
	cd frontend && npx playwright test e2e/smoke.spec.ts

load-test: ## Run Locust load test headlessly for 60s at 50 users
	docker compose run --rm api locust -f /app/../../../tests/load/locustfile.py \
	  --headless --users 50 --spawn-rate 10 --run-time 60s \
	  --host http://api:8000 --csv tests/load/results/locust

# ── Utilities ─────────────────────────────────────────────────────────────────
clean: ## Remove Docker volumes (WARNING: deletes all data)
	docker compose down -v

ps: ## Show running containers
	docker compose ps

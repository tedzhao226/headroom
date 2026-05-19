.PHONY: up down migrate dev test worker-day worker-night mock-api mock-worker-day mock-worker-night mock-stack smoke-up smoke-down smoke-logs smoke-run smoke psql fmt lint help

PG_URL ?= postgresql+asyncpg://headroom:headroom@localhost:5432/headroom

up: ## Start Postgres
	docker compose up -d db

down: ## Stop Postgres
	docker compose down

migrate: ## Apply alembic migrations
	uv run alembic upgrade head

dev: ## Run API (uvicorn) with autoreload
	DATABASE_URL=$(PG_URL) uv run uvicorn headroom.main:app --reload

worker-day: ## Run the day-queue SAQ worker
	DATABASE_URL=$(PG_URL) uv run headroom-worker day

worker-night: ## Run the night-queue SAQ worker
	DATABASE_URL=$(PG_URL) uv run headroom-worker night

mock-api: ## Run API with MockProvider + MockMonitor (no GCP creds needed)
	HEADROOM_USE_MOCKS=1 DATABASE_URL=$(PG_URL) uv run uvicorn headroom.main:app --reload

mock-worker-day: ## Run day worker with MockProvider + MockMonitor
	DATABASE_URL=$(PG_URL) uv run headroom-worker day --mock

mock-worker-night: ## Run night worker with MockProvider + MockMonitor
	DATABASE_URL=$(PG_URL) uv run headroom-worker night --mock

mock-stack: up migrate ## Spin full mock stack: DB + API + both workers (backgrounded; Ctrl-C to stop)
	@trap 'kill 0' INT TERM; \
	HEADROOM_USE_MOCKS=1 DATABASE_URL=$(PG_URL) uv run uvicorn headroom.main:app --reload & \
	DATABASE_URL=$(PG_URL) uv run headroom-worker day --mock & \
	DATABASE_URL=$(PG_URL) uv run headroom-worker night --mock & \
	wait

smoke-up: ## Build+start dockerized mock stack (db + api + workers)
	docker compose --profile mock up -d --build

smoke-down: ## Stop dockerized mock stack and remove containers
	docker compose --profile mock down

smoke-logs: ## Tail logs from the dockerized mock stack
	docker compose --profile mock logs -f

smoke-run: ## Run the smoke client against the dockerized stack
	uv run python scripts/smoke.py

smoke: smoke-up smoke-run ## Full smoke: build, start, run client (leaves stack running; `make smoke-down` to stop)

psql: ## Open psql shell against the running db container
	docker compose exec db psql -U headroom -d headroom

test: ## Run all tests
	uv run python -m pytest -q

fmt: ## Format with ruff
	uv run ruff format .

lint: ## Lint with ruff
	uv run ruff check .

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

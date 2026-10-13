.DEFAULT_GOAL := help
BACKEND := cd backend &&
FRONTEND := cd frontend &&
TEST_DB ?= postgresql+asyncpg://support:support@localhost:5432/support_test

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up: ## Run the whole stack in Docker (http://localhost:8080)
	docker compose up --build

db: ## Start only Postgres + pgvector
	docker compose up -d db

install: ## Install backend and frontend dependencies for local dev
	$(BACKEND) python -m pip install -e ".[dev]"
	$(FRONTEND) npm ci

setup: ## Migrate, seed demo data and index the knowledge base
	$(BACKEND) alembic upgrade head && python -m support.db.seed && python -m support.rag.ingest

api: ## Run the API with reload on :8000
	$(BACKEND) uvicorn support.main:create_app --factory --reload --port 8000

web: ## Run the web app on :5173 (proxies /api to :8000)
	$(FRONTEND) npm run dev

lint: ## Lint and type-check everything
	$(BACKEND) ruff check src tests alembic && ruff format --check src tests alembic && mypy
	$(FRONTEND) npm run lint && npm run typecheck

test: ## Run all tests (backend integration tests need Postgres; see TEST_DB)
	$(BACKEND) TEST_DATABASE_URL=$(TEST_DB) pytest --cov
	$(FRONTEND) npm test

evals: ## Run agent + retrieval evals against real models (resets the target DB!)
	$(BACKEND) python -m support.evals.runner

.PHONY: help up db install setup api web lint test evals

# Nobody memorizes commands. If you find yourself typing a long incantation more
# than twice, it belongs here.
#
# Windows without `make`: use ./make.ps1 <target>, which mirrors these targets.

.DEFAULT_GOAL := help
.PHONY: help setup dev seed test lint fmt types check migrate migration worker api-types down clean

COMPOSE := docker compose
API     := $(COMPOSE) run --rm --no-deps api

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Build images and bring up the stack, blank spoin_db (first-run entrypoint)
	$(COMPOSE) build
	$(COMPOSE) up -d db
	$(COMPOSE) run --rm seed
	@echo ""
	@echo "  API   http://localhost:8000/docs"
	@echo "  Web   http://localhost:3000"
	@echo ""
	@echo "  Now run: make dev"

dev: ## Run the whole stack with hot reload
	$(COMPOSE) up

seed: ## Apply migrations to spoin_db (no fixtures -- see CLAUDE.md)
	$(COMPOSE) run --rm seed

test: ## Run the test suite (against its own database)
	$(COMPOSE) --profile test run --rm test

lint: ## ruff check
	$(API) ruff check src tests

fmt: ## ruff format
	$(API) ruff format src tests

types: ## mypy --strict
	$(API) mypy src

check: lint types test ## Everything CI runs

migrate: ## Apply migrations
	$(COMPOSE) run --rm seed alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add foo"
	$(COMPOSE) run --rm seed alembic revision --autogenerate -m "$(m)"

worker: ## Run one batch pass of the worker, then exit
	$(COMPOSE) --profile worker run --rm worker

api-types: ## Regenerate packages/api-types from the live OpenAPI schema
	npx --yes openapi-typescript http://localhost:8000/openapi.json \
		-o packages/api-types/schema.d.ts

down: ## Stop everything
	$(COMPOSE) down

clean: ## Stop everything and delete the database volume
	$(COMPOSE) down -v

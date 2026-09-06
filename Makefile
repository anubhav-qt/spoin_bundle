# Nobody memorizes commands. If you find yourself typing a long incantation more
# than twice, it belongs here.
#
# Windows without `make`: use ./make.ps1 <target>, which mirrors these targets.

.DEFAULT_GOAL := help
.PHONY: help setup dev seed test lint fmt types check migrate migration \
        universe-migrate universe-migration corpus-check corpus-ingest \
        curriculum-check curriculum-ingest curriculum-project worker api-types down clean

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

lint: ## ruff check + ruff format --check (apps/api and apps/frog)
	$(API) ruff check src tests
	$(API) ruff format --check src tests
	$(API) sh -c "cd /app/frog && ruff check src tests && ruff format --check src tests"

fmt: ## ruff format (apps/api and apps/frog)
	$(API) ruff format src tests
	$(API) sh -c "cd /app/frog && ruff format src tests"

types: ## mypy --strict (apps/api and apps/frog)
	$(API) mypy src
	$(API) sh -c "cd /app/frog && mypy src"

check: lint types test ## Everything CI runs

migrate: ## Apply migrations
	$(COMPOSE) run --rm seed alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add foo"
	$(COMPOSE) run --rm seed alembic revision --autogenerate -m "$(m)"

# ADR-0088: the corpus database has its OWN alembic environment, in apps/frog,
# which reads SPOIN_UNIVERSE_DATABASE_URL and nothing else. These targets are
# separate from `migrate`/`migration` above for the same reason the environment
# is: so a corpus migration cannot be run against spoin_db_2 by muscle memory.
universe-migrate: ## Create (if absent) and migrate the_spoin_universe
	$(COMPOSE) --profile universe run --rm universe-seed

universe-migration: ## Autogenerate a universe migration: make universe-migration m="add foo"
	$(COMPOSE) --profile universe run --rm --entrypoint alembic universe-seed \
		revision --autogenerate -m "$(m)"

# Task 0038, Phase 2. corpus-check needs no GPU and no database -- it is the contract
# validator alone, and it is what the corpus-authoring track runs. corpus-ingest needs
# both, and runs in the only image carrying torch (apps/frog/Dockerfile).
corpus-check: ## Validate the corpus against the ingestion contract; writes nothing
	$(COMPOSE) --profile frog run --rm frog --check

corpus-ingest: ## Ingest the corpus into the_spoin_universe (GPU; run universe-migrate first)
	$(COMPOSE) --profile frog run --rm frog

# The authored curriculum: validate, and ingest into the_spoin_universe. Both reuse the
# `frog` service (which already mounts the corpus and holds SPOIN_UNIVERSE_DATABASE_URL)
# with its entrypoint overridden -- the same trick `universe-migration` uses. `--check`
# is pure (no GPU, no database, no model); the bare form needs the universe database, so
# run `make universe-migrate` first.
curriculum-check: ## Validate docs/the_spoin_universe/curricula against the contract; writes nothing
	$(COMPOSE) --profile frog run --rm --entrypoint python frog -m frog.curriculum --check

curriculum-ingest: ## Ingest curricula into the_spoin_universe (run universe-migrate first)
	$(COMPOSE) --profile frog run --rm --entrypoint python frog -m frog.curriculum

# The deterministic projection into spoin_db_2 -- no GPU, no model, needs both databases,
# so it runs in the `api` image (not `--no-deps`: it needs `db` up).
curriculum-project: ## Project ingested curricula into Topic/Subtopic in spoin_db_2
	$(COMPOSE) run --rm api python -m spoin.curriculum

worker: ## Run one batch pass of the worker, then exit
	$(COMPOSE) --profile worker run --rm worker

scan: ## Scan incomplete topics and run one generation pass
	$(API) python -m spoin.scan_and_generate --limit 1

api-types: ## Regenerate packages/api-types from the live OpenAPI schema
	npx --yes openapi-typescript http://localhost:8000/openapi.json \
		-o packages/api-types/schema.d.ts

down: ## Stop everything
	$(COMPOSE) down

clean: ## Stop everything and delete the database volume
	$(COMPOSE) down -v

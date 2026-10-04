# LifeRescue developer tasks (KAN-19 / LR 10). Run `make help`.
# Local development only: nothing here deploys anything. Windows users: use WSL2 or Git Bash.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE_FILE := infrastructure/docker-compose.yml
ENV_FILE     := .env
DC           := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
SCRIPTS      := scripts/dev/common.sh scripts/dev/dev.sh scripts/dev/doctor.sh scripts/dev/init-env.sh infrastructure/db/initdb/01-create-test-db.sh

.PHONY: help doctor env dev up db-up db-wait db-logs db-psql down db-down db-reset compose-config lint-infra install install-contract install-api install-web test lint

help: ## Show this help
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## /{printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

doctor: ## Check which parts of the local stack can run on this machine
	@bash scripts/dev/doctor.sh

env: ## Create .env from .env.example with a random local DB password (never overwrites)
	@bash scripts/dev/init-env.sh

dev: ## Start PostgreSQL, then API and web if their scaffolds exist (Ctrl-C stops the apps)
	@bash scripts/dev/dev.sh

up: db-up ## Alias for db-up

db-up: env ## Start PostgreSQL and wait until healthy
	@command -v docker >/dev/null || { echo "docker is not installed or not on PATH (run: make doctor)" >&2; exit 1; }
	$(DC) up -d --wait --wait-timeout 120 db

db-wait: ## Block until PostgreSQL reports healthy (after db-up)
	$(DC) up -d --wait --wait-timeout 120 db

db-logs: ## Follow PostgreSQL logs
	$(DC) logs -f --tail=100 db

db-psql: ## Open psql inside the db container (uses the container's own env; no password on the command line)
	$(DC) exec db sh -c 'exec psql --username "$$POSTGRES_USER" --dbname "$$POSTGRES_DB"'

down: db-down ## Alias for db-down

db-down: ## Stop PostgreSQL (data volume is kept)
	$(DC) down

db-reset: ## DESTROY the local database volume. Requires CONFIRM=yes
	@if [ "$(CONFIRM)" != "yes" ]; then echo "db-reset deletes ALL local database data (volume liferescue_pgdata). Re-run with: make db-reset CONFIRM=yes" >&2; exit 1; fi
	$(DC) down --volumes

compose-config: ## Validate the compose file with the placeholder env (needs docker compose; changes nothing)
	docker compose --env-file .env.example -f $(COMPOSE_FILE) config --quiet
	@echo "compose config OK"

lint-infra: ## shellcheck the dev scripts and validate the compose file when tools exist
	@if command -v shellcheck >/dev/null; then shellcheck -x $(SCRIPTS) && echo "shellcheck OK"; else echo "shellcheck not installed - skipped"; fi
	@if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then $(MAKE) --no-print-directory compose-config; else echo "docker compose not available - compose validation skipped"; fi

install: install-contract install-api install-web ## Install API and web dependencies (each skipped if its scaffold is absent)

install-contract: ## Install packages/contract[dev] into packages/contract/.venv (needs LR 03's contract package)
	@if [ ! -f packages/contract/pyproject.toml ]; then echo "packages/contract/pyproject.toml not found - contract package not merged yet (LR 03). Nothing to install."; exit 0; fi
	python3 -m venv packages/contract/.venv
	packages/contract/.venv/bin/python -m pip install --upgrade pip
	packages/contract/.venv/bin/python -m pip install -e "packages/contract[dev]"

install-api: ## Install apps/api into apps/api/.venv (needs the LR 04 scaffold with pyproject.toml)
	@if [ ! -f apps/api/pyproject.toml ]; then echo "apps/api/pyproject.toml not found - API not scaffolded yet (LR 04). Nothing to install."; exit 0; fi
	python3 -m venv apps/api/.venv
	apps/api/.venv/bin/python -m pip install --upgrade pip
	apps/api/.venv/bin/python -m pip install -e "apps/api[dev]"

install-web: ## Install apps/web dependencies with npm ci (needs the LR 05 scaffold and package-lock.json)
	@if [ ! -f apps/web/package.json ]; then echo "apps/web/package.json not found - web not scaffolded yet (LR 05). Nothing to install."; exit 0; fi
	@if [ ! -f apps/web/package-lock.json ]; then echo "apps/web/package-lock.json missing - run 'npm install' in apps/web once and commit the lockfile" >&2; exit 1; fi
	cd apps/web && npm ci

lint: ## Lint what exists (contract: mypy; api: ruff + mypy; web: eslint + tsc); mirrors the proposed CI jobs
	@if [ -f packages/contract/pyproject.toml ]; then cd packages/contract && ../../packages/contract/.venv/bin/python -m mypy contract; else echo "packages/contract absent - skipped"; fi
	@if [ -f apps/api/pyproject.toml ]; then cd apps/api && ruff format --check . && ruff check . && mypy .; else echo "apps/api absent - skipped"; fi
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run lint --if-present && npm run typecheck --if-present; else echo "apps/web absent - skipped"; fi

test: ## Run tests of what exists (contract + api: pytest; web: npm test); API integration tests expect `make db-up`
	@if [ -f packages/contract/pyproject.toml ]; then cd packages/contract && ../../packages/contract/.venv/bin/python -m pytest -q; else echo "packages/contract absent - skipped"; fi
	@if [ -f apps/api/pyproject.toml ]; then cd apps/api && python3 -m pytest; else echo "apps/api absent - skipped"; fi
	@if [ -f apps/web/package.json ]; then cd apps/web && npm test --if-present; else echo "apps/web absent - skipped"; fi

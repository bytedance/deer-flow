COMPOSE_FILE := docker-compose.yml
COMPOSE_PROJECT_NAME ?= chatly-ageny-v2
ATLAS_ENV ?= local
ATLAS_DB_URL ?= postgres://chatagent:chatagent@127.0.0.1:7753/chatagent?sslmode=disable
ATLAS_CONFIG_URI := file://$(abspath atlas.hcl)
ATLAS_MIGRATIONS_URI := file://$(abspath db/migrations)
ATLAS_SUM_FILE := db/migrations/atlas.sum
ATLAS_SCHEMA_FILE ?= db/schema.sql
ATLAS_SCHEMA_URI := file://$(abspath $(ATLAS_SCHEMA_FILE))
ATLAS_DEV_URL ?= docker://postgres/16/dev?search_path=public
MIGRATION_NAME ?=
.DEFAULT_GOAL := help

# Prefer local binaries; fall back to devbox runtime when available.
UV_CMD := $(shell if command -v uv >/dev/null 2>&1; then echo "uv"; elif command -v devbox >/dev/null 2>&1; then echo "devbox run -- uv"; else echo "uv"; fi)
ATLAS_CMD := $(shell if command -v atlas >/dev/null 2>&1; then echo "atlas"; elif command -v devbox >/dev/null 2>&1; then echo "devbox run -- atlas"; else echo "atlas"; fi)

check-uv:
	@command -v uv >/dev/null 2>&1 || command -v devbox >/dev/null 2>&1 || { \
		echo "Neither 'uv' nor 'devbox' is available in PATH."; \
		echo "Install uv: https://docs.astral.sh/uv/getting-started/installation/"; \
		echo "Or install devbox: https://www.jetify.com/docs/devbox/installing_devbox/"; \
		exit 127; \
	}

help:
	@echo "Backend Make targets:"
	@echo "  make install        - Sync Python dependencies (uv/devbox)"
	@echo "  make dev            - Start LangGraph dev server"
	@echo "  make gateway        - Start Gateway API server"
	@echo "  make test           - Run backend test suite"
	@echo "  make up             - Start backend docker dependencies"
	@echo "  make down           - Stop backend docker dependencies"
	@echo "  make clean          - Stop and remove backend docker volumes"
	@echo "  make atlas-diff     - Generate migration from db/schema.sql (set MIGRATION_NAME=...)"
	@echo "  make migrate        - Apply pending Atlas migrations"
	@echo "  make atlas-status   - Show Atlas migration status"
	@echo "  make atlas-apply    - Apply Atlas migrations"
	@echo "  make atlas-lint     - Lint latest Atlas migration"
	@echo "  make atlas-schema-apply - Apply db/schema.sql declaratively (no migration file)"
	@echo "  make memory-worker  - Run persisted memory worker"

install:
	@$(MAKE) check-uv
	$(UV_CMD) sync

dev:
	@$(MAKE) check-uv
	$(UV_CMD) run langgraph dev --no-browser --allow-blocking --no-reload

gateway:
	@$(MAKE) check-uv
	$(UV_CMD) run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001

test:
	@$(MAKE) check-uv
	PYTHONPATH=. $(UV_CMD) run pytest tests/ -v

lint:
	uvx ruff check .

format:
	uvx ruff check . --fix && uvx ruff format .

deps-up:
	docker compose -p $(COMPOSE_PROJECT_NAME) -f $(COMPOSE_FILE) up -d

deps: deps-up

up: deps-up

deps-down:
	docker compose -p $(COMPOSE_PROJECT_NAME) -f $(COMPOSE_FILE) down

down: deps-down

deps-clean:
	docker compose -p $(COMPOSE_PROJECT_NAME) -f $(COMPOSE_FILE) down -v --remove-orphans

clean: deps-clean

atlas-diff:
	@$(MAKE) atlas-check
	@if [ -z "$(MIGRATION_NAME)" ]; then \
		echo "Set MIGRATION_NAME, e.g. make atlas-diff MIGRATION_NAME=add_memory_profiles"; \
		exit 2; \
	fi
	@if [ ! -f $(ATLAS_SCHEMA_FILE) ]; then \
		echo "Schema file not found: $(ATLAS_SCHEMA_FILE)"; \
		echo "Create it first (desired state), then re-run atlas-diff."; \
		exit 2; \
	fi
	$(ATLAS_CMD) migrate diff $(MIGRATION_NAME) --env $(ATLAS_ENV) --config $(ATLAS_CONFIG_URI) --dir $(ATLAS_MIGRATIONS_URI) --to $(ATLAS_SCHEMA_URI) --dev-url "$(ATLAS_DEV_URL)" --var db_url=$(ATLAS_DB_URL)
	@$(MAKE) atlas-hash

atlas-status:
	@$(MAKE) atlas-check
	@$(MAKE) atlas-ensure-hash
	$(ATLAS_CMD) migrate status --env $(ATLAS_ENV) --config $(ATLAS_CONFIG_URI) --dir $(ATLAS_MIGRATIONS_URI) --var db_url=$(ATLAS_DB_URL)


atlas-apply:
	@$(MAKE) atlas-check
	@$(MAKE) atlas-ensure-hash
	$(ATLAS_CMD) migrate apply --env $(ATLAS_ENV) --config $(ATLAS_CONFIG_URI) --dir $(ATLAS_MIGRATIONS_URI) --var db_url=$(ATLAS_DB_URL)

migrate: atlas-apply

atlas-lint:
	@$(MAKE) atlas-check
	@$(MAKE) atlas-ensure-hash
	$(ATLAS_CMD) migrate lint --env $(ATLAS_ENV) --config $(ATLAS_CONFIG_URI) --dir $(ATLAS_MIGRATIONS_URI) --var db_url=$(ATLAS_DB_URL) --latest 1


atlas-schema-apply:
	@$(MAKE) atlas-check
	@if [ ! -f $(ATLAS_SCHEMA_FILE) ]; then \
		echo "Schema file not found: $(ATLAS_SCHEMA_FILE)"; \
		exit 2; \
	fi
	$(ATLAS_CMD) schema apply --env $(ATLAS_ENV) --config $(ATLAS_CONFIG_URI) --to $(ATLAS_SCHEMA_URI) --dev-url "$(ATLAS_DEV_URL)" --var db_url=$(ATLAS_DB_URL) --auto-approve

atlas-hash:
	@$(MAKE) atlas-check
	$(ATLAS_CMD) migrate hash --dir $(ATLAS_MIGRATIONS_URI)

atlas-ensure-hash:
	@if [ ! -f $(ATLAS_SUM_FILE) ]; then \
		echo "Atlas checksum file missing. Generating $(ATLAS_SUM_FILE)..."; \
		$(MAKE) atlas-hash; \
	fi

atlas-check:
	@command -v atlas >/dev/null 2>&1 || command -v devbox >/dev/null 2>&1 || { \
		echo "Neither 'atlas' nor 'devbox' is available in PATH."; \
		echo "Install atlas on macOS: brew install ariga/tap/atlas"; \
		echo "Or install devbox and use: devbox run atlas:status"; \
		exit 127; \
	}

memory-worker:
	@$(MAKE) check-uv
	@CFG="$$DEER_FLOW_CONFIG_PATH"; \
	if [ -z "$$CFG" ] && [ -f ../.vscode/config.local.yaml ]; then \
		CFG="$(abspath ../.vscode/config.local.yaml)"; \
	fi; \
	if [ -n "$$CFG" ]; then \
		echo "Using DEER_FLOW_CONFIG_PATH=$$CFG"; \
		DEER_FLOW_CONFIG_PATH="$$CFG" ./.venv/bin/python -m src.agents.memory.worker_cli; \
	else \
		echo "DEER_FLOW_CONFIG_PATH is not set; worker will use default config resolution."; \
		./.venv/bin/python -m src.agents.memory.worker_cli; \
	fi

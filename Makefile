# DeerFlow - Unified Development Environment

.PHONY: help config check install dev stop clean docker-init docker-start docker-stop docker-logs docker-logs-frontend docker-logs-gateway import-academic-eval build-academic-offline-benchmark-suite run-academic-offline-regression run-academic-online-regression

help:
	@echo "DeerFlow Development Commands:"
	@echo "  make config          - Generate local config files (aborts if config already exists)"
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make install         - Install all dependencies (frontend + backend)"
	@echo "  make setup-sandbox   - Pre-pull sandbox container image (recommended)"
	@echo "  make dev             - Start all services (frontend + backend + nginx on localhost:2026)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo ""
	@echo "Docker Development Commands:"
	@echo "  make docker-init     - Pull sandbox image required for local Docker workflow"
	@echo "  make docker-start    - Start Docker services (mode-aware from config.yaml, localhost:2026)"
	@echo "  make docker-stop     - Stop Docker development services"
	@echo "  make docker-logs     - View Docker development logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"
	@echo ""
	@echo "Academic Eval Import:"
	@echo "  make import-academic-eval RAW_DATA=<file_or_dir> DATASET_NAME=<name> [DATASET_VERSION=v1] [AUTOFIX=1] [AUTOFIX_LEVEL=balanced] [ANONYMIZE=1] [STRICT=0] [VALIDATE_ONLY=0] [FAIL_ON_VALIDATION_ERRORS=0]"
	@echo "  make build-academic-offline-benchmark-suite [CORE_DATASET=top_tier_accept_reject_v1] [FAILURE_MODE_DATASET=failure_mode_library_v1] [OUTPUT_DIR=src/evals/academic/templates/offline_benchmark_suite] [OVERWRITE=1]"
	@echo "  make run-academic-offline-regression [INPUT_DIR=src/evals/academic/templates/offline_benchmark_suite] [OUTPUT_DIR=src/evals/academic/datasets/offline_regression] [STRICT_GATE=1]"
	@echo "  make run-academic-online-regression [INPUT_DIR=src/evals/academic/templates/offline_benchmark_suite] [OUTPUT_DIR=src/evals/academic/datasets/online_regression] [STRICT_GATE=1] [BRANCH=<name>] [COMMIT_SHA=<sha>]"

config:
	@if [ -f config.yaml ] || [ -f config.yml ] || [ -f configure.yml ]; then \
		echo "Error: configuration file already exists (config.yaml/config.yml/configure.yml). Aborting."; \
		exit 1; \
	fi
	@cp config.example.yaml config.yaml
	@test -f .env || cp .env.example .env
	@test -f frontend/.env || cp frontend/.env.example frontend/.env
	@test -f extensions_config.json || (test -f extensions_config.example.json && cp extensions_config.example.json extensions_config.json || true)

# Check required tools
check:
	@echo "=========================================="
	@echo "  Checking Required Dependencies"
	@echo "=========================================="
	@echo ""
	@FAILED=0; \
	echo "Checking Node.js..."; \
	if command -v node >/dev/null 2>&1; then \
		NODE_VERSION=$$(node -v | sed 's/v//'); \
		NODE_MAJOR=$$(echo $$NODE_VERSION | cut -d. -f1); \
		if [ $$NODE_MAJOR -ge 22 ]; then \
			echo "  ✓ Node.js $$NODE_VERSION (>= 22 required)"; \
		else \
			echo "  ✗ Node.js $$NODE_VERSION found, but version 22+ is required"; \
			echo "    Install from: https://nodejs.org/"; \
			FAILED=1; \
		fi; \
	else \
		echo "  ✗ Node.js not found (version 22+ required)"; \
		echo "    Install from: https://nodejs.org/"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "Checking pnpm..."; \
	if command -v pnpm >/dev/null 2>&1; then \
		PNPM_VERSION=$$(pnpm -v); \
		echo "  ✓ pnpm $$PNPM_VERSION"; \
	else \
		echo "  ✗ pnpm not found"; \
		echo "    Install: npm install -g pnpm"; \
		echo "    Or visit: https://pnpm.io/installation"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "Checking uv..."; \
	if command -v uv >/dev/null 2>&1; then \
		UV_VERSION=$$(uv --version | awk '{print $$2}'); \
		echo "  ✓ uv $$UV_VERSION"; \
	else \
		echo "  ✗ uv not found"; \
		echo "    Install: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo "    Or visit: https://docs.astral.sh/uv/getting-started/installation/"; \
		FAILED=1; \
	fi; \
	echo ""; \
	echo "Checking nginx..."; \
	if command -v nginx >/dev/null 2>&1; then \
		NGINX_VERSION=$$(nginx -v 2>&1 | awk -F'/' '{print $$2}'); \
		echo "  ✓ nginx $$NGINX_VERSION"; \
	else \
		echo "  ✗ nginx not found"; \
		echo "    macOS:   brew install nginx"; \
		echo "    Ubuntu:  sudo apt install nginx"; \
		echo "    Or visit: https://nginx.org/en/download.html"; \
		FAILED=1; \
	fi; \
	echo ""; \
	if [ $$FAILED -eq 0 ]; then \
		echo "=========================================="; \
		echo "  ✓ All dependencies are installed!"; \
		echo "=========================================="; \
		echo ""; \
		echo "You can now run:"; \
		echo "  make install  - Install project dependencies"; \
		echo "  make dev      - Start development server"; \
	else \
		echo "=========================================="; \
		echo "  ✗ Some dependencies are missing"; \
		echo "=========================================="; \
		echo ""; \
		echo "Please install the missing tools and run 'make check' again."; \
		exit 1; \
	fi

# Install all dependencies
install:
	@echo "Installing backend dependencies..."
	@cd backend && uv sync
	@echo "Installing frontend dependencies..."
	@cd frontend && pnpm install
	@echo "✓ All dependencies installed"
	@echo ""
	@echo "=========================================="
	@echo "  Optional: Pre-pull Sandbox Image"
	@echo "=========================================="
	@echo ""
	@echo "If you plan to use Docker/Container-based sandbox, you can pre-pull the image:"
	@echo "  make setup-sandbox"
	@echo ""

# Pre-pull sandbox Docker image (optional but recommended)
setup-sandbox:
	@echo "=========================================="
	@echo "  Pre-pulling Sandbox Container Image"
	@echo "=========================================="
	@echo ""
	@IMAGE=$$(grep -A 20 "# sandbox:" config.yaml 2>/dev/null | grep "image:" | awk '{print $$2}' | head -1); \
	if [ -z "$$IMAGE" ]; then \
		IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"; \
		echo "Using default image: $$IMAGE"; \
	else \
		echo "Using configured image: $$IMAGE"; \
	fi; \
	echo ""; \
	if command -v container >/dev/null 2>&1 && [ "$$(uname)" = "Darwin" ]; then \
		echo "Detected Apple Container on macOS, pulling image..."; \
		container pull "$$IMAGE" || echo "⚠ Apple Container pull failed, will try Docker"; \
	fi; \
	if command -v docker >/dev/null 2>&1; then \
		echo "Pulling image using Docker..."; \
		docker pull "$$IMAGE"; \
		echo ""; \
		echo "✓ Sandbox image pulled successfully"; \
	else \
		echo "✗ Neither Docker nor Apple Container is available"; \
		echo "  Please install Docker: https://docs.docker.com/get-docker/"; \
		exit 1; \
	fi

# Start all services
dev:
	@./scripts/start.sh

# Stop all services
stop:
	@./scripts/start.sh --stop

# Clean up
clean: stop
	@echo "Cleaning up..."
	@-rm -rf logs/*.log 2>/dev/null || true
	@echo "✓ Cleanup complete"

# ==========================================
# Docker Development Commands
# ==========================================

# Initialize Docker containers and install dependencies
docker-init:
	@./scripts/docker.sh init

# Start Docker development environment
docker-start:
	@./scripts/docker.sh start

# Stop Docker development environment
docker-stop:
	@./scripts/docker.sh stop

# View Docker development logs
docker-logs:
	@./scripts/docker.sh logs

# View Docker development logs
docker-logs-frontend:
	@./scripts/docker.sh logs --frontend
docker-logs-gateway:
	@./scripts/docker.sh logs --gateway

# Import raw accept/reject datasets into normalized eval datasets
import-academic-eval:
	@if [ -z "$(RAW_DATA)" ] || [ -z "$(DATASET_NAME)" ]; then \
		echo "Usage: make import-academic-eval RAW_DATA=<file_or_dir> DATASET_NAME=<name> [DATASET_VERSION=v1] [AUTOFIX=1] [AUTOFIX_LEVEL=balanced] [ANONYMIZE=1] [STRICT=0] [VALIDATE_ONLY=0] [FAIL_ON_VALIDATION_ERRORS=0] [BATCH_PATTERN=*.json] [OUTPUT_DIR=src/evals/academic/datasets]"; \
		exit 1; \
	fi
	@AUTOFIX_FLAG=""; if [ "$(AUTOFIX)" = "1" ]; then AUTOFIX_FLAG="--autofix"; fi; \
	ANON_FLAG=""; if [ "$(ANONYMIZE)" = "0" ]; then ANON_FLAG="--no-anonymize"; else ANON_FLAG="--anonymize"; fi; \
	STRICT_FLAG=""; if [ "$(STRICT)" = "1" ]; then STRICT_FLAG="--strict"; fi; \
	VALIDATE_ONLY_FLAG=""; if [ "$(VALIDATE_ONLY)" = "1" ]; then VALIDATE_ONLY_FLAG="--validate-only"; fi; \
	FAIL_VALIDATION_FLAG=""; if [ "$(FAIL_ON_VALIDATION_ERRORS)" = "1" ]; then FAIL_VALIDATION_FLAG="--fail-on-validation-errors"; fi; \
	cd backend && uv run python scripts/import_academic_eval_dataset.py \
		--input "$(abspath $(RAW_DATA))" \
		--dataset-name "$(DATASET_NAME)" \
		--dataset-version "$(if $(DATASET_VERSION),$(DATASET_VERSION),v1)" \
		--autofix-level "$(if $(AUTOFIX_LEVEL),$(AUTOFIX_LEVEL),balanced)" \
		--batch-pattern "$(if $(BATCH_PATTERN),$(BATCH_PATTERN),*.json)" \
		--output-dir "$(if $(OUTPUT_DIR),$(OUTPUT_DIR),src/evals/academic/datasets)" \
		$$AUTOFIX_FLAG $$ANON_FLAG $$STRICT_FLAG $$VALIDATE_ONLY_FLAG $$FAIL_VALIDATION_FLAG $(if $(SOURCE_NAME),--source-name "$(SOURCE_NAME)",) $(if $(BENCHMARK_SPLIT),--benchmark-split "$(BENCHMARK_SPLIT)",)

# Build layered offline benchmark raw templates (core/failure-mode/domain-splits)
build-academic-offline-benchmark-suite:
	@OVERWRITE_FLAG=""; if [ "$(OVERWRITE)" = "1" ]; then OVERWRITE_FLAG="--overwrite"; fi; \
	cd backend && uv run python scripts/build_academic_offline_benchmark_suite.py \
		--core-dataset "$(if $(CORE_DATASET),$(CORE_DATASET),top_tier_accept_reject_v1)" \
		--failure-mode-dataset "$(if $(FAILURE_MODE_DATASET),$(FAILURE_MODE_DATASET),failure_mode_library_v1)" \
		--output-dir "$(if $(OUTPUT_DIR),$(OUTPUT_DIR),src/evals/academic/templates/offline_benchmark_suite)" \
		$$OVERWRITE_FLAG

# Run layered offline benchmark regression (core calibration + red-team + domain splits)
run-academic-offline-regression:
	@STRICT_FLAG=""; if [ "$(STRICT_GATE)" = "1" ]; then STRICT_FLAG="--strict-gate"; fi; \
	OVERWRITE_FLAG=""; if [ "$(OVERWRITE)" = "1" ]; then OVERWRITE_FLAG="--overwrite"; fi; \
	cd backend && uv run python scripts/run_academic_offline_regression.py \
		--input-dir "$(if $(INPUT_DIR),$(INPUT_DIR),src/evals/academic/templates/offline_benchmark_suite)" \
		--output-dir "$(if $(OUTPUT_DIR),$(OUTPUT_DIR),src/evals/academic/datasets/offline_regression)" \
		--dataset-version "$(if $(DATASET_VERSION),$(DATASET_VERSION),v1)" \
		$$STRICT_FLAG $$OVERWRITE_FLAG

# Run online regression drift checks (commit-to-commit + week-to-week)
run-academic-online-regression:
	@STRICT_FLAG=""; if [ "$(STRICT_GATE)" = "1" ]; then STRICT_FLAG="--strict-gate"; fi; \
	OVERWRITE_FLAG=""; if [ "$(OVERWRITE)" = "1" ]; then OVERWRITE_FLAG="--overwrite"; fi; \
	BRANCH_ARG=""; if [ -n "$(BRANCH)" ]; then BRANCH_ARG="--branch \"$(BRANCH)\""; fi; \
	COMMIT_ARG=""; if [ -n "$(COMMIT_SHA)" ]; then COMMIT_ARG="--commit-sha \"$(COMMIT_SHA)\""; fi; \
	RUN_LABEL_ARG=""; if [ -n "$(RUN_LABEL)" ]; then RUN_LABEL_ARG="--run-label \"$(RUN_LABEL)\""; fi; \
	cd backend && uv run python scripts/run_academic_online_regression.py \
		--input-dir "$(if $(INPUT_DIR),$(INPUT_DIR),src/evals/academic/templates/offline_benchmark_suite)" \
		--output-dir "$(if $(OUTPUT_DIR),$(OUTPUT_DIR),src/evals/academic/datasets/online_regression)" \
		--history-file "$(if $(HISTORY_FILE),$(HISTORY_FILE),online-regression-history.json)" \
		--dataset-version "$(if $(DATASET_VERSION),$(DATASET_VERSION),v1)" \
		$$BRANCH_ARG $$COMMIT_ARG $$RUN_LABEL_ARG \
		$$STRICT_FLAG $$OVERWRITE_FLAG
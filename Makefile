# DeerFlow - Unified Development Environment

.PHONY: help config config-upgrade check install dev dev-pro dev-daemon dev-daemon-pro start start-pro start-daemon start-daemon-pro stop up up-pro down clean docker-init docker-start docker-start-pro docker-stop docker-logs docker-logs-frontend docker-logs-gateway

BASH ?= bash

# Detect OS for Windows compatibility
ifeq ($(OS),Windows_NT)
    SHELL := cmd.exe
    PYTHON ?= python
else
    PYTHON ?= python3
endif

help:
	@echo "DeerFlow Development Commands:"
	@echo "  make config          - Generate local config files (aborts if config already exists)"
	@echo "  make config-upgrade  - Merge new fields from config.example.yaml into config.yaml"
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make install         - Install all dependencies (frontend + backend)"
	@echo "  make setup-sandbox   - Pre-pull sandbox container image (recommended)"
	@echo "  make dev             - Start all services in development mode (with hot-reloading)"
	@echo "  make dev-pro         - Start in dev + Gateway mode (experimental, no LangGraph server)"
	@echo "  make dev-daemon      - Start dev services in background (daemon mode)"
	@echo "  make dev-daemon-pro  - Start dev daemon + Gateway mode (experimental)"
	@echo "  make start           - Start all services in production mode (optimized, no hot-reloading)"
	@echo "  make start-pro       - Start in prod + Gateway mode (experimental)"
	@echo "  make start-daemon    - Start prod services in background (daemon mode)"
	@echo "  make start-daemon-pro - Start prod daemon + Gateway mode (experimental)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo ""
	@echo "Docker Production Commands:"
	@echo "  make up              - Build and start production Docker services (localhost:2026)"
	@echo "  make up-pro          - Build and start production Docker in Gateway mode (experimental)"
	@echo "  make down            - Stop and remove production Docker containers"
	@echo ""
	@echo "Docker Development Commands:"
	@echo "  make docker-init     - Pull the sandbox image"
	@echo "  make docker-start    - Start Docker services (mode-aware from config.yaml, localhost:2026)"
	@echo "  make docker-start-pro - Start Docker in Gateway mode (experimental, no LangGraph container)"
	@echo "  make docker-stop     - Stop Docker development services"
	@echo "  make docker-logs     - View Docker development logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"

config:
	@$(PYTHON) ./scripts/configure.py

config-upgrade:
	@./scripts/config-upgrade.sh

# Check required tools
check:
	@$(PYTHON) ./scripts/check.py

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
		if docker pull "$$IMAGE"; then \
			echo ""; \
			echo "✓ Sandbox image pulled successfully"; \
		else \
			echo ""; \
			echo "⚠ Failed to pull sandbox image (this is OK for local sandbox mode)"; \
		fi; \
	else \
		echo "✗ Neither Docker nor Apple Container is available"; \
		echo "  Please install Docker: https://docs.docker.com/get-docker/"; \
		exit 1; \
	fi

# Start all services in development mode (with hot-reloading)
dev:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --dev
else
	@./scripts/serve.sh --dev
endif

# Start all services in dev + Gateway mode (experimental: agent runtime embedded in Gateway)
dev-pro:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --dev --gateway
else
	@./scripts/serve.sh --dev --gateway
endif

# Start all services in production mode (with optimizations)
start:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --prod
else
	@./scripts/serve.sh --prod
endif

# Start all services in prod + Gateway mode (experimental)
start-pro:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --prod --gateway
else
	@./scripts/serve.sh --prod --gateway
endif

# Start all services in daemon mode (background)
dev-daemon:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --dev --daemon
else
	@./scripts/serve.sh --dev --daemon
endif

# Start daemon + Gateway mode (experimental)
dev-daemon-pro:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --dev --gateway --daemon
else
	@./scripts/serve.sh --dev --gateway --daemon
endif

# Start prod services in daemon mode (background)
start-daemon:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --prod --daemon
else
	@./scripts/serve.sh --prod --daemon
endif

# Start prod daemon + Gateway mode (experimental)
start-daemon-pro:
	@$(PYTHON) ./scripts/check.py
ifeq ($(OS),Windows_NT)
	@call scripts\run-with-git-bash.cmd ./scripts/serve.sh --prod --gateway --daemon
else
	@./scripts/serve.sh --prod --gateway --daemon
endif

# Stop all services
stop:
	@./scripts/serve.sh --stop

# Clean up
clean: stop
	@echo "Cleaning up..."
	@-rm -rf backend/.deer-flow 2>/dev/null || true
	@-rm -rf backend/.langgraph_api 2>/dev/null || true
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

# Start Docker in Gateway mode (experimental)
docker-start-pro:
	@./scripts/docker.sh start --gateway

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

# ==========================================
# Production Docker Commands
# ==========================================

# Build and start production services
up:
	@./scripts/deploy.sh

# Build and start production services in Gateway mode
up-pro:
	@./scripts/deploy.sh --gateway

# Stop and remove production containers
down:
	@./scripts/deploy.sh down

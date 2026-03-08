# DeerFlow - Unified Development Environment

.PHONY: help config check install dev stop clean docker-init docker-start docker-stop docker-logs docker-logs-frontend docker-logs-gateway

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
	@echo "  make docker-init     - Build the custom k3s image (with pre-cached sandbox image)"
	@echo "  make docker-start    - Start Docker services (mode-aware from config.yaml, localhost:2026)"
	@echo "  make docker-stop     - Stop Docker development services"
	@echo "  make docker-logs     - View Docker development logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"

config:
	@if [ -f config.yaml ] || [ -f config.yml ] || [ -f configure.yml ]; then \
		echo "Error: configuration file already exists (config.yaml/config.yml/configure.yml). Aborting."; \
		exit 1; \
	fi
	@cp config.example.yaml config.yaml
	@test -f .env || cp .env.example .env
	@test -f frontend/.env || cp frontend/.env.example frontend/.env

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
	@echo "Stopping existing services if any..."
	@-pkill -f "langgraph dev" 2>/dev/null || true
	@-pkill -f "uvicorn src.gateway.app:app" 2>/dev/null || true
	@-pkill -f "next dev" 2>/dev/null || true
	@-nginx -c $(PWD)/docker/nginx/nginx.local.conf -p $(PWD) -s quit 2>/dev/null || true
	@sleep 1
	@-pkill -9 nginx 2>/dev/null || true
	@-./scripts/cleanup-containers.sh deer-flow-sandbox 2>/dev/null || true
	@sleep 1
	@echo ""
	@echo "=========================================="
	@echo "  Starting DeerFlow Development Server"
	@echo "=========================================="
	@echo ""
	@echo "Services starting up..."
	@echo "  → Backend: LangGraph + Gateway"
	@echo "  → Frontend: Next.js"
	@echo "  → Nginx: Reverse Proxy"
	@echo ""
	@if ! { \
			[ -n "$$DEER_FLOW_CONFIG_PATH" ] && [ -f "$$DEER_FLOW_CONFIG_PATH" ] || \
			[ -f backend/config.yaml ] || \
			[ -f config.yaml ]; \
		}; then \
		echo "✗ No DeerFlow config file found."; \
		echo "  Checked these locations:"; \
		echo "    - $$DEER_FLOW_CONFIG_PATH (when DEER_FLOW_CONFIG_PATH is set)"; \
		echo "    - backend/config.yaml"; \
		echo "    - ./config.yaml"; \
		echo ""; \
		echo "  Run 'make config' from the repo root to generate ./config.yaml, then set required model API keys in .env or your config file."; \
		exit 1; \
	fi
	@cleanup() { \
		trap - INT TERM; \
		echo ""; \
		echo "Shutting down services..."; \
		pkill -f "langgraph dev" 2>/dev/null || true; \
		pkill -f "uvicorn src.gateway.app:app" 2>/dev/null || true; \
		pkill -f "next dev" 2>/dev/null || true; \
		nginx -c $(PWD)/docker/nginx/nginx.local.conf -p $(PWD) -s quit 2>/dev/null || true; \
		sleep 1; \
		pkill -9 nginx 2>/dev/null || true; \
		echo "Cleaning up sandbox containers..."; \
		./scripts/cleanup-containers.sh deer-flow-sandbox 2>/dev/null || true; \
		echo "✓ All services stopped"; \
		exit 0; \
	}; \
	trap cleanup INT TERM; \
	mkdir -p logs; \
	echo "Starting LangGraph server..."; \
	cd backend && NO_COLOR=1 uv run langgraph dev --no-browser --allow-blocking --no-reload > ../logs/langgraph.log 2>&1 & \
	sleep 3; \
	echo "✓ LangGraph server started on localhost:2024"; \
	echo "Starting Gateway API..."; \
	cd backend && uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > ../logs/gateway.log 2>&1 & \
	sleep 3; \
	if ! lsof -i :8001 -sTCP:LISTEN -t >/dev/null 2>&1; then \
		echo "✗ Gateway API failed to start. Last log output:"; \
		tail -60 logs/gateway.log; \
		echo ""; \
		echo "Likely configuration errors:"; \
		grep -E "Failed to load configuration|Environment variable .* not found|config\.yaml.*not found" logs/gateway.log | tail -5 || true; \
		cleanup; \
	fi; \
	echo "✓ Gateway API started on localhost:8001"; \
	echo "Starting Frontend..."; \
	cd frontend && pnpm run dev > ../logs/frontend.log 2>&1 & \
	sleep 3; \
	echo "✓ Frontend started on localhost:3000"; \
	echo "Starting Nginx reverse proxy..."; \
	mkdir -p logs && nginx -g 'daemon off;' -c $(PWD)/docker/nginx/nginx.local.conf -p $(PWD) > logs/nginx.log 2>&1 & \
	sleep 2; \
	echo "✓ Nginx started on localhost:2026"; \
	echo ""; \
	echo "=========================================="; \
	echo "  DeerFlow is ready!"; \
	echo "=========================================="; \
	echo ""; \
	echo "  🌐 Application: http://localhost:2026"; \
	echo "  📡 API Gateway: http://localhost:2026/api/*"; \
	echo "  🤖 LangGraph:   http://localhost:2026/api/langgraph/*"; \
	echo ""; \
	echo "  📋 Logs:"; \
	echo "     - LangGraph: logs/langgraph.log"; \
	echo "     - Gateway:   logs/gateway.log"; \
	echo "     - Frontend:  logs/frontend.log"; \
	echo "     - Nginx:     logs/nginx.log"; \
	echo ""; \
	echo "Press Ctrl+C to stop all services"; \
	echo ""; \
	wait

# Stop all services
stop:
	@echo "Stopping all services..."
	@-pkill -f "langgraph dev" 2>/dev/null || true
	@-pkill -f "uvicorn src.gateway.app:app" 2>/dev/null || true
	@-pkill -f "next dev" 2>/dev/null || true
	@-nginx -c $(PWD)/docker/nginx/nginx.local.conf -p $(PWD) -s quit 2>/dev/null || true
	@sleep 1
	@-pkill -9 nginx 2>/dev/null || true
	@echo "Cleaning up sandbox containers..."
	@-./scripts/cleanup-containers.sh deer-flow-sandbox 2>/dev/null || true
	@echo "✓ All services stopped"

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
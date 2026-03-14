# Thinktank - Unified Development Environment

.PHONY: help config check install dev stop clean db-start db-stop db-migrate db-reset erp-setup docker-init docker-start docker-stop docker-logs docker-logs-frontend docker-logs-gateway build-frontend build-prod prod-start prod-stop prod-logs prod-status prod-health prod-test

# Default DATABASE_URL for the local PostgreSQL container
DB_URL ?= postgresql://thinktank:matterhorn@localhost:5432/thinktank

help:
	@echo "Thinktank Development Commands:"
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make install         - Install all dependencies (frontend + backend)"
	@echo "  make setup-sandbox   - Pre-pull sandbox container image (recommended)"
	@echo "  make dev             - Start all services (frontend + backend + nginx on localhost:2026)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo ""
	@echo "Database Commands:"
	@echo "  make db-start        - Start PostgreSQL in Docker (localhost:5432)"
	@echo "  make db-stop         - Stop PostgreSQL container"
	@echo "  make db-migrate      - Run Alembic migrations against local PostgreSQL"
	@echo "  make db-reset        - Drop and recreate the database (destructive!)"
	@echo "  make erp-setup       - Set up ERP sample database for deep research"
	@echo ""
	@echo "Docker Development Commands:"
	@echo "  make docker-init     - Build the custom k3s image (with pre-cached sandbox image)"
	@echo "  make docker-start    - Start Docker services (mode-aware from config.yaml, localhost:2026)"
	@echo "  make docker-stop     - Stop Docker development services"
	@echo "  make docker-logs     - View Docker development logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"
	@echo ""
	@echo "Production Commands:"
	@echo "  make build-frontend  - Build frontend for web deployment (outputs to frontend/dist/renderer/)"
	@echo "  make build-prod      - Build all production Docker images (nginx+frontend, backend)"
	@echo "  make prod-start      - Start production environment (Docker Compose)"
	@echo "  make prod-stop       - Stop production environment"
	@echo "  make prod-logs       - View production logs"
	@echo "  make prod-status     - Show production service status"
	@echo "  make prod-health     - Run health checks against production stack"
	@echo "  make prod-test       - Run Playwright E2E tests against production stack"
	@echo ""
	@echo "Quick start (production):"
	@echo "  ./scripts/prod.sh start   - Build and start everything"
	@echo "  ./scripts/prod.sh help    - Show all production commands"

config:
	@test -f config.yaml || cp config.example.yaml config.yaml
	@test -f .env || cp .env.example .env
	@test -f frontend/.env || cp frontend/.env.example frontend/.env
	@test -f extensions_config.json || cp extensions_config.example.json extensions_config.json

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

# ==========================================
# Database Commands
# ==========================================

# Start PostgreSQL in a Docker container
db-start:
	@if docker ps --format '{{.Names}}' | grep -q '^thinktank-postgres$$'; then \
		echo "✓ PostgreSQL is already running"; \
	else \
		echo "Starting PostgreSQL..."; \
		docker run -d \
			--name thinktank-postgres \
			-e POSTGRES_USER=thinktank \
			-e POSTGRES_PASSWORD=matterhorn \
			-e POSTGRES_DB=thinktank \
			-p 5432:5432 \
			-v thinktank-pgdata:/var/lib/postgresql/data \
			postgres:16-alpine >/dev/null; \
		echo "Waiting for PostgreSQL to be ready..."; \
		for i in $$(seq 1 30); do \
			if docker exec thinktank-postgres pg_isready -U thinktank >/dev/null 2>&1; then \
				echo "✓ PostgreSQL is ready on localhost:5432"; \
				echo "  DATABASE_URL=$(DB_URL)"; \
				break; \
			fi; \
			sleep 1; \
		done; \
	fi

# Stop PostgreSQL container
db-stop:
	@echo "Stopping PostgreSQL..."
	@-docker stop thinktank-postgres 2>/dev/null || true
	@-docker rm thinktank-postgres 2>/dev/null || true
	@echo "✓ PostgreSQL stopped"

# Run Alembic migrations
db-migrate: db-start
	@echo "Running database migrations..."
	@cd backend && DATABASE_URL=$(DB_URL) uv run alembic upgrade head
	@echo "✓ Migrations complete"

# Set up ERP sample database for deep research
erp-setup: db-start
	@echo "Setting up ERP sample database..."
	@docker exec thinktank-postgres psql -U thinktank -tc "SELECT 1 FROM pg_database WHERE datname='erp_sample'" | grep -q 1 || docker exec thinktank-postgres psql -U thinktank -c "CREATE DATABASE erp_sample"
	@docker cp docker/erp-sample/init-erp.sql thinktank-postgres:/tmp/init-erp.sql
	@docker exec thinktank-postgres psql -U thinktank -d erp_sample -f /tmp/init-erp.sql -q
	@echo "✓ ERP sample database ready (postgresql://localhost:5432/erp_sample)"

# Reset database (destructive!)
db-reset:
	@echo "Resetting database..."
	@-docker stop thinktank-postgres 2>/dev/null || true
	@-docker rm thinktank-postgres 2>/dev/null || true
	@-docker volume rm thinktank-pgdata 2>/dev/null || true
	@echo "✓ Database reset. Run 'make db-start && make db-migrate' to recreate."

# Start all services
dev:
	@echo "Stopping existing services if any..."
	@-pkill -f "langgraph dev" 2>/dev/null || true
	@-pkill -f "uvicorn src.gateway.app:app" 2>/dev/null || true
	@-pkill -f "next dev" 2>/dev/null || true
	@-nginx -c $(PWD)/docker/nginx/nginx.local.conf -p $(PWD) -s quit 2>/dev/null || true
	@sleep 1
	@-pkill -9 nginx 2>/dev/null || true
	@-./scripts/cleanup-containers.sh thinktank-sandbox 2>/dev/null || true
	@sleep 1
	@echo ""
	@echo "=========================================="
	@echo "  Starting Thinktank Development Server"
	@echo "=========================================="
	@echo ""
	@# Start PostgreSQL if Docker is available
	@if command -v docker >/dev/null 2>&1; then \
		if docker ps --format '{{.Names}}' | grep -q '^thinktank-postgres$$'; then \
			echo "✓ PostgreSQL already running"; \
		else \
			if docker ps -a --format '{{.Names}}' | grep -q '^thinktank-postgres$$'; then \
				docker start thinktank-postgres >/dev/null; \
			else \
				docker run -d \
					--name thinktank-postgres \
					-e POSTGRES_USER=thinktank \
					-e POSTGRES_PASSWORD=matterhorn \
					-e POSTGRES_DB=thinktank \
					-p 5432:5432 \
					-v thinktank-pgdata:/var/lib/postgresql/data \
					postgres:16-alpine >/dev/null; \
			fi; \
			for i in $$(seq 1 30); do \
				if docker exec thinktank-postgres pg_isready -U thinktank >/dev/null 2>&1; then \
					break; \
				fi; \
				sleep 1; \
			done; \
			echo "✓ PostgreSQL ready on localhost:5432"; \
		fi; \
		echo "Running database migrations..."; \
		cd backend && DATABASE_URL=$(DB_URL) uv run alembic upgrade head 2>&1 | tail -1; \
		echo "✓ Database migrations applied"; \
		echo "Setting up ERP sample database..."; \
		docker exec thinktank-postgres psql -U thinktank -tc "SELECT 1 FROM pg_database WHERE datname='erp_sample'" | grep -q 1 || docker exec thinktank-postgres psql -U thinktank -c "CREATE DATABASE erp_sample" >/dev/null; \
		docker cp docker/erp-sample/init-erp.sql thinktank-postgres:/tmp/init-erp.sql >/dev/null; \
		docker exec thinktank-postgres psql -U thinktank -d erp_sample -f /tmp/init-erp.sql -q 2>&1 | tail -1; \
		echo "✓ ERP sample database ready"; \
	else \
		echo "⚠ Docker not found — running without PostgreSQL (file-based storage)"; \
	fi
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
		echo ""; \
		echo "Shutting down services..."; \
		pkill -f "langgraph dev" 2>/dev/null || true; \
		pkill -f "uvicorn src.gateway.app:app" 2>/dev/null || true; \
		pkill -f "next dev" 2>/dev/null || true; \
		nginx -c $(PWD)/docker/nginx/nginx.local.conf -p $(PWD) -s quit 2>/dev/null || true; \
		sleep 1; \
		pkill -9 nginx 2>/dev/null || true; \
		echo "Cleaning up sandbox containers..."; \
		./scripts/cleanup-containers.sh thinktank-sandbox 2>/dev/null || true; \
		echo "✓ All services stopped (PostgreSQL container kept running)"; \
		exit 0; \
	}; \
	trap cleanup INT TERM; \
	mkdir -p logs; \
	DB_AVAILABLE=0; \
	if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^thinktank-postgres$$'; then \
		DB_AVAILABLE=1; \
	fi; \
	echo "Starting LangGraph server..."; \
	if [ $$DB_AVAILABLE -eq 1 ]; then \
		cd backend && DATABASE_URL=$(DB_URL) NO_COLOR=1 uv run langgraph dev --no-browser --allow-blocking --no-reload > ../logs/langgraph.log 2>&1 & \
	else \
		cd backend && NO_COLOR=1 uv run langgraph dev --no-browser --allow-blocking --no-reload > ../logs/langgraph.log 2>&1 & \
	fi; \
	sleep 3; \
	echo "✓ LangGraph server started on localhost:2024"; \
	echo "Starting Gateway API..."; \
	if [ $$DB_AVAILABLE -eq 1 ]; then \
		cd backend && DATABASE_URL=$(DB_URL) uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > ../logs/gateway.log 2>&1 & \
	else \
		cd backend && uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > ../logs/gateway.log 2>&1 & \
	fi; \
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
	echo "  Thinktank is ready!"; \
	echo "=========================================="; \
	echo ""; \
	echo "  🌐 Application: http://localhost:2026"; \
	echo "  📡 API Gateway: http://localhost:2026/api/*"; \
	echo "  🤖 LangGraph:   http://localhost:2026/api/langgraph/*"; \
	if [ $$DB_AVAILABLE -eq 1 ]; then \
		echo "  🗄  Database:    postgresql://localhost:5432/thinktank"; \
	else \
		echo "  📁 Storage:     file-based (.think-tank/)"; \
	fi; \
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
	@-./scripts/cleanup-containers.sh thinktank-sandbox 2>/dev/null || true
	@echo "✓ All services stopped"
	@echo "  (PostgreSQL container is still running. Use 'make db-stop' to stop it.)"

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

# ==========================================
# Production Commands
# ==========================================

# Build frontend for web deployment
build-frontend:
	@echo "Building frontend for web deployment..."
	@cd frontend && pnpm run build:web
	@echo "✓ Frontend built to frontend/dist/renderer/"

# Build production Docker images (nginx+frontend, backend)
build-prod:
	@./scripts/prod.sh build

# Start production environment
prod-start:
	@./scripts/prod.sh start

# Stop production environment
prod-stop:
	@./scripts/prod.sh stop

# View production logs
prod-logs:
	@./scripts/prod.sh logs

# Show production service status
prod-status:
	@./scripts/prod.sh status

# Run production health checks
prod-health:
	@./scripts/prod.sh health

# Run E2E tests against production stack
prod-test:
	@./scripts/prod.sh test

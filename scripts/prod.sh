#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Thinktank.ai — Production Stack Management
# ─────────────────────────────────────────────────────────────────────────────
# Manages the full production Docker Compose stack:
#   postgres, redis, gateway, langgraph, worker, nginx (frontend + proxy)
#
# Usage:
#   ./scripts/prod.sh start          Start the full stack
#   ./scripts/prod.sh stop           Stop all services
#   ./scripts/prod.sh restart        Rebuild and restart
#   ./scripts/prod.sh reload         Restart backend services (config reload, no rebuild)
#   ./scripts/prod.sh status         Show service status
#   ./scripts/prod.sh logs [service] Tail logs (optionally for a single service)
#   ./scripts/prod.sh build          Build images without starting
#   ./scripts/prod.sh clean          Stop and remove volumes (destructive)
#   ./scripts/prod.sh test           Run Playwright E2E tests against the stack
#   ./scripts/prod.sh health         Check health of all services
#   ./scripts/prod.sh help           Show this help message
# ─────────────────────────────────────────────────────────────────────────────

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"
COMPOSE_FILE="$DOCKER_DIR/docker-compose-prod.yaml"

# Defaults (override via environment or .env)
export DB_PASSWORD="${DB_PASSWORD:-Qwen3.5-397B-A17B}"
export NGINX_HTTP_PORT="${NGINX_HTTP_PORT:-80}"
export GATEWAY_REPLICAS="${GATEWAY_REPLICAS:-1}"
export LANGGRAPH_REPLICAS="${LANGGRAPH_REPLICAS:-1}"
export WORKER_REPLICAS="${WORKER_REPLICAS:-1}"

# Load .env from project root if it exists
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# ── Helpers ──────────────────────────────────────────────────────────────────

compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_header()  { echo -e "\n${BOLD}$*${NC}\n"; }

wait_for_healthy() {
    local service="$1"
    local max_wait="${2:-60}"
    local elapsed=0

    while [[ $elapsed -lt $max_wait ]]; do
        local status
        status=$(compose ps --format json "$service" 2>/dev/null \
            | grep -o '"Health":"[^"]*"' \
            | head -1 \
            | cut -d'"' -f4) || true

        if [[ "$status" == "healthy" ]]; then
            return 0
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

wait_for_url() {
    local url="$1"
    local max_wait="${2:-60}"
    local elapsed=0

    while [[ $elapsed -lt $max_wait ]]; do
        if curl -sf -o /dev/null "$url" 2>/dev/null; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_build() {
    log_header "Building Production Images"
    compose build "$@"
    log_ok "All images built successfully"
}

cmd_start() {
    log_header "Starting Thinktank.ai Production Stack"

    if [[ "$DB_PASSWORD" == "Qwen3.5-397B-A17B" ]]; then
        log_warn "Using default DB_PASSWORD. Set DB_PASSWORD env var for real deployments."
    fi

    log_info "Configuration:"
    echo "       NGINX_HTTP_PORT         = $NGINX_HTTP_PORT"
    echo "       GATEWAY_REPLICAS   = $GATEWAY_REPLICAS"
    echo "       LANGGRAPH_REPLICAS = $LANGGRAPH_REPLICAS"
    echo "       WORKER_REPLICAS    = $WORKER_REPLICAS"
    echo ""

    # Build and start
    log_info "Building and starting services..."
    compose up --build -d

    # Wait for infrastructure
    log_info "Waiting for PostgreSQL to be healthy..."
    if wait_for_healthy postgres 30; then
        log_ok "PostgreSQL is healthy"
    else
        log_error "PostgreSQL did not become healthy in 30s"
        compose logs postgres --tail=10
        return 1
    fi

    log_info "Waiting for Redis to be healthy..."
    if wait_for_healthy redis 15; then
        log_ok "Redis is healthy"
    else
        log_error "Redis did not become healthy in 15s"
        return 1
    fi

    # Wait for gateway to respond
    log_info "Waiting for Gateway API to start (running migrations)..."
    if wait_for_url "http://localhost:${NGINX_HTTP_PORT}/health" 90; then
        log_ok "Gateway API is healthy"
    else
        log_warn "Gateway health check did not pass within 90s"
        log_info "Check gateway logs: $0 logs gateway"
    fi

    # Print summary
    log_header "Thinktank.ai is running!"
    echo "  Application:  http://localhost:${NGINX_HTTP_PORT}"
    echo "  API Gateway:  http://localhost:${NGINX_HTTP_PORT}/api/*"
    echo "  LangGraph:    http://localhost:${NGINX_HTTP_PORT}/api/langgraph/*"
    echo "  Health:       http://localhost:${NGINX_HTTP_PORT}/health"
    echo "  API Docs:     http://localhost:${NGINX_HTTP_PORT}/docs"
    echo ""
    echo "  Commands:"
    echo "    $0 status    Show service status"
    echo "    $0 logs      Follow all logs"
    echo "    $0 health    Check service health"
    echo "    $0 stop      Stop the stack"
    echo ""
}

cmd_stop() {
    log_header "Stopping Production Stack"
    compose down
    log_ok "All services stopped (volumes preserved)"
}

cmd_restart() {
    log_header "Restarting Production Stack"
    compose down
    cmd_start
}

cmd_reload() {
    log_header "Reloading Configuration"
    log_info "Restarting gateway, langgraph, and worker services (no rebuild)..."
    compose restart gateway langgraph worker
    log_ok "Services restarted. Config changes (config.yaml, extensions_config.json, .env) are now active."
}

cmd_status() {
    log_header "Service Status"
    compose ps
}

cmd_logs() {
    local service="${1:-}"
    if [[ -n "$service" ]]; then
        log_info "Following logs for: $service"
        compose logs -f "$service"
    else
        log_info "Following all logs (Ctrl+C to stop)"
        compose logs -f
    fi
}

cmd_clean() {
    log_header "Cleaning Up (removing volumes)"
    log_warn "This will DELETE all data (PostgreSQL, Redis)."
    read -rp "Are you sure? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        compose down -v
        log_ok "Stack stopped and volumes removed"
    else
        log_info "Cancelled"
    fi
}

cmd_health() {
    log_header "Health Check"

    local port="$NGINX_HTTP_PORT"
    local base="http://localhost:${port}"

    # Nginx / Frontend
    echo -n "  nginx (frontend)  ... "
    if curl -sf -o /dev/null "$base/"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}"
    fi

    # SPA fallback
    echo -n "  SPA fallback      ... "
    if curl -sf -o /dev/null "$base/login"; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}"
    fi

    # Health endpoint (gateway)
    echo -n "  gateway /health   ... "
    local health_body
    health_body=$(curl -sf "$base/health" 2>/dev/null) || true
    if echo "$health_body" | grep -q '"healthy"' 2>/dev/null; then
        echo -e "${GREEN}OK${NC}  $health_body"
    else
        local http_code
        http_code=$(curl -sf -o /dev/null -w "%{http_code}" "$base/health" 2>/dev/null) || http_code="000"
        echo -e "${RED}FAIL${NC}  (HTTP $http_code)"
    fi

    # API auth
    echo -n "  gateway /api/auth ... "
    local auth_code
    auth_code=$(curl -sf -o /dev/null -w "%{http_code}" "$base/api/auth/login" 2>/dev/null) || auth_code="000"
    if [[ "$auth_code" =~ ^(400|401|405|422)$ ]]; then
        echo -e "${GREEN}OK${NC}  (HTTP $auth_code — expected)"
    elif [[ "$auth_code" == "502" ]]; then
        echo -e "${RED}FAIL${NC}  (HTTP 502 — gateway down)"
    else
        echo -e "${YELLOW}WARN${NC}  (HTTP $auth_code)"
    fi

    # Cache headers
    echo -n "  asset caching     ... "
    local cache_header
    cache_header=$(curl -sf -I "$base/" 2>/dev/null | grep -i 'cache-control' | head -1) || true
    if echo "$cache_header" | grep -qi 'no-cache' 2>/dev/null; then
        echo -e "${GREEN}OK${NC}  (index.html: no-cache)"
    else
        echo -e "${YELLOW}WARN${NC}  ($cache_header)"
    fi

    echo ""
}

cmd_test() {
    log_header "Running Playwright E2E Tests"

    local port="$NGINX_HTTP_PORT"

    log_info "Testing against http://localhost:${port}"

    if ! curl -sf -o /dev/null "http://localhost:${port}/" 2>/dev/null; then
        log_error "Stack is not running on port $port. Start it first: $0 start"
        return 1
    fi

    cd "$PROJECT_ROOT/frontend" && \
        PLAYWRIGHT_WEB_URL="http://localhost:${port}" \
        pnpm test:e2e:web
}

cmd_help() {
    echo ""
    echo -e "${BOLD}Thinktank.ai Production Stack${NC}"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  start              Build images and start all services"
    echo "  stop               Stop all services (preserves data)"
    echo "  restart            Rebuild and restart all services"
    echo "  reload             Restart gateway, langgraph, worker (pick up config changes)"
    echo "  status             Show service status"
    echo "  logs [service]     Follow logs (all or specific service)"
    echo "                     Services: nginx, gateway, langgraph, worker, postgres, redis"
    echo "  build              Build images without starting"
    echo "  health             Run health checks against running stack"
    echo "  test               Run Playwright E2E tests against running stack"
    echo "  clean              Stop and delete all data (destructive!)"
    echo "  help               Show this message"
    echo ""
    echo "Environment variables (set in shell or .env):"
    echo "  DB_PASSWORD          PostgreSQL password        (default: Qwen3.5-397B-A17B)"
    echo "  NGINX_HTTP_PORT           Port for nginx             (default: 80)"
    echo "  GATEWAY_REPLICAS     Number of gateway replicas (default: 1)"
    echo "  LANGGRAPH_REPLICAS   Number of langgraph replicas (default: 1)"
    echo "  WORKER_REPLICAS      Number of worker replicas  (default: 1)"
    echo ""
    echo "Examples:"
    echo "  $0 start                               # Start with defaults on port 80"
    echo "  NGINX_HTTP_PORT=8080 $0 start               # Start on port 8080"
    echo "  DB_PASSWORD=Qwen3.5-397B-A17B NGINX_HTTP_PORT=8080 $0 start"
    echo "  $0 logs gateway                        # Follow gateway logs only"
    echo "  $0 test                                # Run E2E tests"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    case "${1:-help}" in
        start)   cmd_start ;;
        stop)    cmd_stop ;;
        restart) cmd_restart ;;
        reload)  cmd_reload ;;
        status)  cmd_status ;;
        logs)    shift; cmd_logs "$@" ;;
        build)   shift; cmd_build "$@" ;;
        health)  cmd_health ;;
        test)    cmd_test ;;
        clean)   cmd_clean ;;
        help|--help|-h) cmd_help ;;
        *)
            log_error "Unknown command: $1"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"

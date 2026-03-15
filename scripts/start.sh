#!/usr/bin/env bash
#
# start.sh - Start all DeerFlow development services
#
# Must be run from the repo root directory.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PID_DIR="$REPO_ROOT/.deer-flow/pids"
mkdir -p "$PID_DIR"

stop_pid_file() {
    local name="$1"
    local pid_file="$PID_DIR/${name}.pid"
    if [ ! -f "$pid_file" ]; then
        return 0
    fi

    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    rm -f "$pid_file"
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
}

stop_services() {
    stop_pid_file "langgraph"
    stop_pid_file "gateway"
    stop_pid_file "frontend"
    stop_pid_file "nginx"
    nginx -c "$REPO_ROOT/docker/nginx/nginx.local.conf" -p "$REPO_ROOT" -s quit 2>/dev/null || true
    ./scripts/cleanup-containers.sh deer-flow-sandbox 2>/dev/null || true
}

if [ "${1:-}" = "--stop" ]; then
    echo "Stopping DeerFlow services..."
    stop_services
    echo "✓ All services stopped"
    exit 0
fi

# ── Stop existing services ────────────────────────────────────────────────────

echo "Stopping existing services if any..."
stop_services
sleep 1

# ── Banner ────────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "  Starting DeerFlow Development Server"
echo "=========================================="
echo ""
echo "Services starting up..."
echo "  → Backend: LangGraph + Gateway"
echo "  → Frontend: Next.js"
echo "  → Nginx: Reverse Proxy"
echo ""

# ── Config check ─────────────────────────────────────────────────────────────

if ! { \
        [ -n "$DEER_FLOW_CONFIG_PATH" ] && [ -f "$DEER_FLOW_CONFIG_PATH" ] || \
        [ -f backend/config.yaml ] || \
        [ -f config.yaml ]; \
    }; then
    echo "✗ No DeerFlow config file found."
    echo "  Checked these locations:"
    echo "    - $DEER_FLOW_CONFIG_PATH (when DEER_FLOW_CONFIG_PATH is set)"
    echo "    - backend/config.yaml"
    echo "    - ./config.yaml"
    echo ""
    echo "  Run 'make config' from the repo root to generate ./config.yaml, then set required model API keys in .env or your config file."
    exit 1
fi

# ── Cleanup trap ─────────────────────────────────────────────────────────────

CLEANUP_EXIT_CODE=0
cleanup() {
    trap - INT TERM
    echo ""
    echo "Shutting down services..."
    stop_services
    echo "Cleaning up sandbox containers..."
    echo "✓ All services stopped"
    exit "$CLEANUP_EXIT_CODE"
}
trap cleanup INT TERM

# ── Start services ────────────────────────────────────────────────────────────

mkdir -p logs
# Fall back to logs.local/ if logs/ is not writable (e.g. created by Docker as root)
if touch logs/.write_test 2>/dev/null; then
    rm -f logs/.write_test
    LOGS_DIR=logs
else
    echo "⚠ logs/ is not writable, using logs.local/ instead"
    mkdir -p logs.local
    LOGS_DIR=logs.local
fi

# Load .env from project root so gateway/langgraph can pick up API keys
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    . "$REPO_ROOT/.env"
    set +a
fi

# Ensure pnpm is in PATH (make may not load full shell profile)
if ! command -v pnpm >/dev/null 2>&1; then
    for candidate in "$HOME/.local/share/pnpm" "$HOME/.nvm/versions/node/"*/bin "/usr/local/bin"; do
        if [ -n "$candidate" ] && [ -x "$candidate/pnpm" ] 2>/dev/null; then
            export PATH="$candidate:$PATH"
            break
        fi
    done
fi
if ! command -v pnpm >/dev/null 2>&1; then
    echo "✗ pnpm not found. Please install pnpm before running 'make dev'."
    echo "  Install using one of:"
    echo "    npm install -g pnpm"
    echo "    corepack enable && corepack prepare pnpm@latest"
    echo "  If already installed, verify with 'which pnpm' and add its path to PATH."
    exit 1
fi
# Fall back to user directories if ~/.local/share/pnpm is not writable (e.g. created by root)
if ! touch "$HOME/.local/share/pnpm/.write_test" 2>/dev/null; then
    rm -f "$HOME/.local/share/pnpm/.write_test" 2>/dev/null
    export PNPM_HOME="${PNPM_HOME:-$HOME/.pnpm-home}"
    export COREPACK_HOME="${COREPACK_HOME:-$HOME/.corepack}"
    export PNPM_STORE_DIR="${PNPM_STORE_DIR:-$HOME/.pnpm-store}"
    mkdir -p "$PNPM_HOME" "$COREPACK_HOME" "$PNPM_STORE_DIR"
fi

echo "Starting LangGraph server..."
(cd backend && NO_COLOR=1 uv run langgraph dev --no-browser --allow-blocking --no-reload > ../$LOGS_DIR/langgraph.log 2>&1) &
echo $! > "$PID_DIR/langgraph.pid"
./scripts/wait-for-port.sh 2024 60 "LangGraph" || {
    echo "  See $LOGS_DIR/langgraph.log for details"
    tail -20 $LOGS_DIR/langgraph.log
    CLEANUP_EXIT_CODE=1; cleanup
}
echo "✓ LangGraph server started on localhost:2024"

echo "Starting Gateway API..."
(cd backend && uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001 > ../$LOGS_DIR/gateway.log 2>&1) &
echo $! > "$PID_DIR/gateway.pid"
./scripts/wait-for-port.sh 8001 30 "Gateway API" || {
    echo "✗ Gateway API failed to start. Last log output:"
    tail -60 $LOGS_DIR/gateway.log
    echo ""
    echo "Likely configuration errors:"
    grep -E "Failed to load configuration|Environment variable .* not found|config\.yaml.*not found" $LOGS_DIR/gateway.log 2>/dev/null | tail -5 || true
    CLEANUP_EXIT_CODE=1; cleanup
}
echo "✓ Gateway API started on localhost:8001"

echo "Starting Frontend..."
(cd frontend && pnpm run dev > ../$LOGS_DIR/frontend.log 2>&1) &
echo $! > "$PID_DIR/frontend.pid"
./scripts/wait-for-port.sh 3000 120 "Frontend" || {
    echo "  See $LOGS_DIR/frontend.log for details"
    tail -20 $LOGS_DIR/frontend.log
    CLEANUP_EXIT_CODE=1; cleanup
}
echo "✓ Frontend started on localhost:3000"

echo "Starting Nginx reverse proxy..."
nginx -g 'daemon off;' -c "$REPO_ROOT/docker/nginx/nginx.local.conf" -p "$REPO_ROOT" > $LOGS_DIR/nginx.log 2>&1 &
echo $! > "$PID_DIR/nginx.pid"
./scripts/wait-for-port.sh 2026 10 "Nginx" || {
    echo "  See $LOGS_DIR/nginx.log for details"
    tail -10 $LOGS_DIR/nginx.log
    CLEANUP_EXIT_CODE=1; cleanup
}
echo "✓ Nginx started on localhost:2026"

# ── Ready ─────────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "  DeerFlow is ready!"
echo "=========================================="
echo ""
echo "  🌐 Application: http://localhost:2026"
echo "  📡 API Gateway: http://localhost:2026/api/*"
echo "  🤖 LangGraph:   http://localhost:2026/api/langgraph/*"
echo ""
echo "  📋 Logs:"
echo "     - LangGraph: $LOGS_DIR/langgraph.log"
echo "     - Gateway:   $LOGS_DIR/gateway.log"
echo "     - Frontend:  $LOGS_DIR/frontend.log"
echo "     - Nginx:     $LOGS_DIR/nginx.log"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

wait

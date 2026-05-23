#!/usr/bin/env bash
#
# start_docker_prd.sh — Start DeerFlow Docker production services from pre-built images
#
# 用法:
#   ./start_docker_prd.sh    # 启动（不重建）
#   ./start_docker_prd.sh down  # 停止并移除容器
#
# 前置条件:
#   - images 已通过 make build 构建完毕
#   - .env、config.yaml 已配置
#

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

DOCKER_DIR="$REPO_ROOT/docker"
COMPOSE_CMD=(docker compose -p deer-flow -f "$DOCKER_DIR/docker-compose.yaml")

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# ── DEER_FLOW_HOME ────────────────────────────────────────────────────────────
if [ -z "$DEER_FLOW_HOME" ]; then
    export DEER_FLOW_HOME="$REPO_ROOT/backend/.deer-flow"
fi
mkdir -p "$DEER_FLOW_HOME"
export DEER_FLOW_REPO_ROOT="$REPO_ROOT"
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$REPO_ROOT/config.yaml}"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$REPO_ROOT/extensions_config.json}"
export DEER_FLOW_DOCKER_SOCKET="${DEER_FLOW_DOCKER_SOCKET:-/var/run/docker.sock}"

echo -e "${BLUE}DEER_FLOW_HOME=$DEER_FLOW_HOME${NC}"

# ── BETTER_AUTH_SECRET ───────────────────────────────────────────────────────
# Required by Next.js in production. Generated once and persisted so auth
# sessions survive container restarts.
_secret_file="$DEER_FLOW_HOME/.better-auth-secret"
if [ -z "$BETTER_AUTH_SECRET" ]; then
    if [ -f "$_secret_file" ]; then
        export BETTER_AUTH_SECRET="$(cat "$_secret_file")"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET loaded from $_secret_file${NC}"
    else
        export BETTER_AUTH_SECRET
        if command -v openssl > /dev/null 2>&1; then
            BETTER_AUTH_SECRET="$(openssl rand -hex 32)"
        elif command -v python3 > /dev/null 2>&1; then
            BETTER_AUTH_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
        else
            echo -e "${RED}✗ Cannot generate BETTER_AUTH_SECRET: openssl and python3 are unavailable${NC}" >&2
            exit 1
        fi
        echo "$BETTER_AUTH_SECRET" > "$_secret_file"
        chmod 600 "$_secret_file"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET generated → $_secret_file${NC}"
    fi
fi

services="frontend gateway nginx"

# ── down ──────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "down" ]; then
    echo "Stopping and removing containers..."
    "${COMPOSE_CMD[@]}" down
    echo -e "${GREEN}✓ Containers stopped${NC}"
    exit 0
fi

# ── start ─────────────────────────────────────────────────────────────────────
echo "=========================================="
echo "  DeerFlow — Starting (no rebuild)"
echo "=========================================="
echo ""
echo "Starting containers from pre-built images..."
"${COMPOSE_CMD[@]}" up -d --remove-orphans $services

echo ""
echo "=========================================="
echo "  ✓ DeerFlow is running!"
echo "=========================================="
echo ""
echo "  🌐 Application: http://localhost:${PORT:-2026}"
echo ""
echo "  ./start_docker_prd.sh down  — stop containers"
echo ""
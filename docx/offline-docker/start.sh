#!/bin/bash
#
# DeerFlow 离线部署启动脚本
# 用法：./start.sh {start|down}
#

set -e

DEPLOY_DIR="/opt/deer-flow"
PORT="${PORT:-2026}"
COMPOSE_FILE="$DEPLOY_DIR/docker/docker-compose.yaml"

# ── Colors ────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# ── Command ──────────────────────────────────────────────────────────────────

CMD="${1:-start}"

case "$CMD" in
    start|down)
        ;;
    *)
        echo "用法: $0 {start|down}"
        echo "  start  — 启动 DeerFlow 服务"
        echo "  down   — 停止并移除 DeerFlow 容器"
        exit 1
        ;;
esac

# ── down ─────────────────────────────────────────────────────────────────────

if [ "$CMD" = "down" ]; then
    echo "=========================================="
    echo "  DeerFlow — 停止服务"
    echo "=========================================="
    echo ""

    export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$DEPLOY_DIR/.deer-flow}"
    export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$DEPLOY_DIR/config.yaml}"
    export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$DEPLOY_DIR/extensions_config.json}"
    export DEER_FLOW_DOCKER_SOCKET="${DEER_FLOW_DOCKER_SOCKET:-/var/run/docker.sock}"
    export DEER_FLOW_REPO_ROOT="${DEER_FLOW_REPO_ROOT:-$DEPLOY_DIR}"
    export BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-placeholder}"

    cd "$DEPLOY_DIR/docker"
    docker-compose -p deer-flow down

    echo ""
    echo "✓ 服务已停止并移除"
    exit 0
fi

# ── start ────────────────────────────────────────────────────────────────────

echo "=========================================="
echo "  DeerFlow 离线部署"
echo "=========================================="

# 检查镜像是否已加载
echo "==> 检查 Docker 镜像..."
IMAGES=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^deer-flow-frontend:|^deer-flow-gateway:|^nginx:alpine$" | wc -l)
if [ "$IMAGES" -lt 3 ]; then
    echo -e "${RED}✗ 镜像未完全加载，请先执行 docker load -i *.tar${NC}"
    echo "  当前镜像："
    docker images | grep -E "deer-flow|nginx"
    exit 1
fi
echo -e "${GREEN}✓ 3 个镜像已加载${NC}"

# 检查配置文件
echo "==> 检查配置文件..."
for f in "$DEPLOY_DIR/config.yaml" "$DEPLOY_DIR/extensions_config.json" "$COMPOSE_FILE" "$DEPLOY_DIR/docker/nginx.conf"; do
    if [ ! -f "$f" ]; then
        echo -e "${RED}✗ 缺少文件: $f${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ 配置文件完整${NC}"

# 创建目录
echo "==> 创建运行时目录..."
mkdir -p "$DEPLOY_DIR/.deer-flow"
mkdir -p "$DEPLOY_DIR/skills"

# 清理旧容器并重建网络
echo "==> 清理旧容器..."
cd "$DEPLOY_DIR/docker"
docker-compose down 2>/dev/null || true

echo "==> 创建 Docker 网络..."
docker network rm deer-flow 2>/dev/null || true
docker network create deer-flow 2>/dev/null || true

# 设置环境变量
export DEER_FLOW_HOME="$DEPLOY_DIR/.deer-flow"
export DEER_FLOW_CONFIG_PATH="$DEPLOY_DIR/config.yaml"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$DEPLOY_DIR/extensions_config.json"
export DEER_FLOW_DOCKER_SOCKET="/var/run/docker.sock"
export DEER_FLOW_REPO_ROOT="$DEPLOY_DIR"
export HOME=$(eval echo ~)

# 生成 BETTER_AUTH_SECRET 并持久化
_secret_file="$DEER_FLOW_HOME/.better-auth-secret"
if [ -z "$BETTER_AUTH_SECRET" ]; then
    if [ -f "$_secret_file" ]; then
        BETTER_AUTH_SECRET="$(cat "$_secret_file")"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET loaded from $_secret_file${NC}"
    else
        if command -v openssl >/dev/null 2>&1; then
            BETTER_AUTH_SECRET="$(openssl rand -hex 32)"
        elif command -v python3 >/dev/null 2>&1; then
            BETTER_AUTH_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
        else
            echo -e "${RED}✗ 无法生成 BETTER_AUTH_SECRET${NC}" >&2
            exit 1
        fi
        echo "$BETTER_AUTH_SECRET" > "$_secret_file"
        chmod 600 "$_secret_file"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET generated → $_secret_file${NC}"
    fi
    export BETTER_AUTH_SECRET
fi

# 追加到 .env（确保 docker-compose 能读取）
if ! grep -q "BETTER_AUTH_SECRET" "$DEPLOY_DIR/.env" 2>/dev/null; then
    echo "BETTER_AUTH_SECRET=$BETTER_AUTH_SECRET" >> "$DEPLOY_DIR/.env"
fi
export BETTER_AUTH_SECRET

# 启动服务
echo "==> 启动 DeerFlow 服务..."
docker-compose -p deer-flow up -d --remove-orphans

echo ""
echo "==> 容器状态..."
docker-compose -p deer-flow ps

echo ""
echo "=========================================="
echo "  DeerFlow 已启动"
echo "  🌐 访问地址: http://localhost:$PORT"
echo "=========================================="
echo ""
echo "  停止服务: $0 down"
echo "  查看日志: docker-compose -f $COMPOSE_FILE -p deer-flow logs -f"
echo ""
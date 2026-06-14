#!/usr/bin/env bash
#
# asuka.sh - DeerFlow 服务管理脚本
#
# 用法:
#   ./asuka.sh --start-all       启动所有服务
#   ./asuka.sh --restart-all     重启所有服务
#   ./asuka.sh --stop-all        停止所有服务
#   ./asuka.sh --start:FE        启动前端
#   ./asuka.sh --start:BE        启动后端
#   ./asuka.sh --start:LG        启动 LangGraph
#   ./asuka.sh --stop:FE         停止前端
#   ./asuka.sh --stop:BE         停止后端
#   ./asuka.sh --stop:LG         停止 LangGraph
#   ./asuka.sh --help            显示帮助

set -e

# ── 颜色定义 ─────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── 路径配置 ─────────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
LOGS_DIR="$REPO_ROOT/logs"
PID_DIR="$REPO_ROOT/.asuka_pids"

# 创建必要目录
mkdir -p "$LOGS_DIR" "$PID_DIR"

# ── 服务定义 ─────────────────────────────────────────────────────────────────

# FE: Frontend (Next.js)
SVC_FE_NAME="Frontend"
SVC_FE_PORT="3000"
SVC_FE_PATTERN="next dev|next-server|node.*next"

# BE: Backend (Gateway)
SVC_BE_NAME="Backend"
SVC_BE_PORT="8001"
SVC_BE_PATTERN="uvicorn app.gateway.app:app"

# LG: LangGraph
SVC_LG_NAME="LangGraph"
SVC_LG_PORT="2024"
SVC_LG_PATTERN="langgraph dev"

# NG: Nginx reverse proxy
SVC_NG_NAME="Nginx"
SVC_NG_PORT="2026"
SVC_NG_PATTERN="nginx"

# ── 帮助信息 ─────────────────────────────────────────────────────────────────

show_help() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                     DeerFlow 服务管理工具                    ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}━━━ 全部服务 ━━━${NC}"
    echo "  ./asuka.sh --start-all       启动所有服务"
    echo "  ./asuka.sh --restart-all     重启所有服务"
    echo "  ./asuka.sh --stop-all        停止所有服务"
    echo ""
    echo -e "${YELLOW}━━━ 单个服务 ━━━${NC}"
    echo "  ./asuka.sh --start:FE        启动前端 (Next.js)"
    echo "  ./asuka.sh --start:BE        启动后端 (Gateway)"
    echo "  ./asuka.sh --start:LG        启动 LangGraph"
    echo "  ./asuka.sh --start:NG        启动 Nginx 反向代理"
    echo ""
    echo "  ./asuka.sh --stop:FE         停止前端"
    echo "  ./asuka.sh --stop:BE         停止后端"
    echo "  ./asuka.sh --stop:LG         停止 LangGraph"
    echo "  ./asuka.sh --stop:NG         停止 Nginx"
    echo ""
    echo -e "${YELLOW}━━━ 其他 ━━━${NC}"
    echo "  ./asuka.sh --help            显示帮助"
    echo ""
    echo -e "${YELLOW}━━━ 服务端口 ━━━${NC}"
    echo "  FE (Frontend):  localhost:3000"
    echo "  BE (Backend):   localhost:8001"
    echo "  LG (LangGraph): localhost:2024"
    echo "  NG (Nginx):     localhost:2026"
    echo ""
    echo -e "${YELLOW}━━━ 日志位置 ━━━${NC}"
    echo "  $LOGS_DIR/frontend.log"
    echo "  $LOGS_DIR/gateway.log"
    echo "  $LOGS_DIR/langgraph.log"
    echo "  $LOGS_DIR/nginx.log"
    echo ""
}

# ── 工具函数 ─────────────────────────────────────────────────────────────────

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_port() {
    local port=$1
    if lsof -i -P 2>/dev/null | grep -q ":${port} (LISTEN)"; then
        return 0  # 端口被占用
    fi
    return 1  # 端口空闲
}

wait_for_port() {
    local service_name=$1
    local port=$2
    local timeout=${3:-60}
    local elapsed=0

    log_info "等待 $service_name 就绪 (端口 $port)..."
    while [ $elapsed -lt $timeout ]; do
        if check_port $port; then
            log_info "✓ $service_name 已就绪"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    log_error "$service_name 启动超时 (等待 ${timeout}s)"
    return 1
}

get_pid() {
    local service=$1
    local pid_file="$PID_DIR/${service}.pid"

    if [ -f "$pid_file" ]; then
        cat "$pid_file"
    else
        echo ""
    fi
}

save_pid() {
    local service=$1
    local pid=$2
    local pid_file="$PID_DIR/${service}.pid"
    echo "$pid" > "$pid_file"
}

clear_pid() {
    local service=$1
    local pid_file="$PID_DIR/${service}.pid"
    rm -f "$pid_file"
}

is_running() {
    local pattern=$1
    pgrep -f "$pattern" > /dev/null 2>&1
}

# ── 停止服务函数 ─────────────────────────────────────────────────────────────

stop_service() {
    local service=$1
    local name=$2
    local pattern=$3
    local port=$4

    log_info "停止 $name..."

    # 方法1: 通过 PID 文件
    local pid_file="$PID_DIR/${service}.pid"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi

    # 方法2: 通过进程名匹配
    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -TERM 2>/dev/null || true
        sleep 1
        echo "$pids" | xargs kill -9 2>/dev/null || true
    fi

    # 等待端口释放
    local wait_count=0
    while check_port "$port" && [ $wait_count -lt 10 ]; do
        sleep 1
        wait_count=$((wait_count + 1))
    done

    log_info "✓ $name 已停止"
}

# ── 启动服务函数 ─────────────────────────────────────────────────────────────

start_frontend() {
    if is_running "$SVC_FE_PATTERN"; then
        log_warn "$SVC_FE_NAME 已在运行"
        return 0
    fi

    if check_port "$SVC_FE_PORT"; then
        log_error "端口 $SVC_FE_PORT 已被占用，无法启动 $SVC_FE_NAME"
        return 1
    fi

    log_info "启动 $SVC_FE_NAME..."
    cd "$REPO_ROOT/frontend"

    nohup pnpm run dev > "$LOGS_DIR/frontend.log" 2>&1 &
    local pid=$!
    cd - > /dev/null

    save_pid "FE" "$pid"
    wait_for_port "$SVC_FE_NAME" "$SVC_FE_PORT" 120
}

start_backend() {
    if is_running "$SVC_BE_PATTERN"; then
        log_warn "$SVC_BE_NAME 已在运行"
        return 0
    fi

    if check_port "$SVC_BE_PORT"; then
        log_error "端口 $SVC_BE_PORT 已被占用，无法启动 $SVC_BE_NAME"
        return 1
    fi

    log_info "启动 $SVC_BE_NAME..."
    cd "$REPO_ROOT/backend"

    nohup env PYTHONPATH=. uv run uvicorn app.gateway.app:app \
        --host 0.0.0.0 --port 8001 \
        > "$LOGS_DIR/gateway.log" 2>&1 &
    local pid=$!
    cd - > /dev/null

    save_pid "BE" "$pid"
    wait_for_port "$SVC_BE_NAME" "$SVC_BE_PORT" 30
}

start_langgraph() {
    if is_running "$SVC_LG_PATTERN"; then
        log_warn "$SVC_LG_NAME 已在运行"
        return 0
    fi

    if check_port "$SVC_LG_PORT"; then
        log_error "端口 $SVC_LG_PORT 已被占用，无法启动 $SVC_LG_NAME"
        return 1
    fi

    log_info "启动 $SVC_LG_NAME..."
    cd "$REPO_ROOT/backend"

    nohup env NO_COLOR=1 uv run langgraph dev \
        --no-browser --allow-blocking \
        > "$LOGS_DIR/langgraph.log" 2>&1 &
    local pid=$!
    cd - > /dev/null

    save_pid "LG" "$pid"
    wait_for_port "$SVC_LG_NAME" "$SVC_LG_PORT" 60
}

start_nginx() {
    if is_running "$SVC_NG_PATTERN"; then
        log_warn "$SVC_NG_NAME 已在运行"
        return 0
    fi

    if check_port "$SVC_NG_PORT"; then
        log_error "端口 $SVC_NG_PORT 已被占用，无法启动 $SVC_NG_NAME"
        return 1
    fi

    log_info "启动 $SVC_NG_NAME..."
    local nginx_conf="$REPO_ROOT/docker/nginx/nginx.local.conf"

    if [ ! -f "$nginx_conf" ]; then
        log_error "Nginx 配置文件不存在: $nginx_conf"
        return 1
    fi

    nohup nginx -g "daemon off;" -c "$nginx_conf" -p "$REPO_ROOT" \
        > "$LOGS_DIR/nginx.log" 2>&1 &
    local pid=$!
    save_pid "NG" "$pid"
    wait_for_port "$SVC_NG_NAME" "$SVC_NG_PORT" 10
}

# ── 全部服务操作 ─────────────────────────────────────────────────────────────

start_all() {
    log_info "启动所有服务..."
    echo ""

    start_langgraph
    echo ""

    start_backend
    echo ""

    start_frontend
    echo ""

    start_nginx
    echo ""

    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  ✓ 所有服务已启动${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "  🌐 Frontend:   http://localhost:3000"
    echo "  📡 Backend:    http://localhost:8001"
    echo "  🤖 LangGraph:  http://localhost:2024"
    echo "  🌍 Nginx:      http://localhost:2026 (统一入口)"
    echo ""
}

stop_all() {
    log_info "停止所有服务..."
    echo ""

    stop_service "FE" "$SVC_FE_NAME" "$SVC_FE_PATTERN" "$SVC_FE_PORT"
    stop_service "BE" "$SVC_BE_NAME" "$SVC_BE_PATTERN" "$SVC_BE_PORT"
    stop_service "LG" "$SVC_LG_NAME" "$SVC_LG_PATTERN" "$SVC_LG_PORT"
    stop_service "NG" "$SVC_NG_NAME" "$SVC_NG_PATTERN" "$SVC_NG_PORT"

    echo ""
    log_info "✓ 所有服务已停止"
}

restart_all() {
    log_info "重启所有服务..."
    stop_all
    echo ""
    sleep 2
    start_all
}

# ── 解析命令 ─────────────────────────────────────────────────────────────────

parse_command() {
    local cmd=$1

    case "$cmd" in
        --help|-h)
            show_help
            ;;
        --start-all)
            start_all
            ;;
        --stop-all)
            stop_all
            ;;
        --restart-all)
            restart_all
            ;;
        --start:FE)
            start_frontend
            ;;
        --start:BE)
            start_backend
            ;;
        --start:LG)
            start_langgraph
            ;;
        --start:NG)
            start_nginx
            ;;
        --stop:FE)
            stop_service "FE" "$SVC_FE_NAME" "$SVC_FE_PATTERN" "$SVC_FE_PORT"
            ;;
        --stop:BE)
            stop_service "BE" "$SVC_BE_NAME" "$SVC_BE_PATTERN" "$SVC_BE_PORT"
            ;;
        --stop:LG)
            stop_service "LG" "$SVC_LG_NAME" "$SVC_LG_PATTERN" "$SVC_LG_PORT"
            ;;
        --stop:NG)
            stop_service "NG" "$SVC_NG_NAME" "$SVC_NG_PATTERN" "$SVC_NG_PORT"
            ;;
        *)
            log_error "未知命令: $cmd"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# ── 主入口 ───────────────────────────────────────────────────────────────────

main() {
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    for arg in "$@"; do
        parse_command "$arg"
    done
}

main "$@"

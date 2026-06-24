#!/bin/bash
# DeerFlow 后端服务管理脚本
# 用法: ./init.sh
# 功能:
#   - 如果服务未运行 → 启动所有服务
#   - 如果服务已运行 → 重启所有服务

set -e

DEER_FLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEER_FLOW_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查服务是否运行
check_service() {
    if pgrep -f "langgraph dev" > /dev/null 2>&1 || \
       pgrep -f "uvicorn app.gateway.app:app" > /dev/null 2>&1 || \
       pgrep -f "next dev" > /dev/null 2>&1; then
        return 0  # 服务运行中
    fi
    return 1  # 服务未运行
}

# 停止所有服务
stop_services() {
    echo -e "${YELLOW}停止所有服务...${NC}"
    pkill -f "langgraph dev" 2>/dev/null || true
    pkill -f "uvicorn app.gateway.app:app" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null || true
    pkill -f "next-server" 2>/dev/null || true
    pkill -f "nginx" 2>/dev/null || true
    sleep 2
    echo -e "${GREEN}所有服务已停止${NC}"
}

# 启动所有服务
start_services() {
    echo -e "${GREEN}启动 DeerFlow 后端服务...${NC}"
    
    # 确保 PATH 包含 uv
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    
    # 设置环境变量
    if [ -f "$DEER_FLOW_DIR/.env" ]; then
        set -a
        source "$DEER_FLOW_DIR/.env"
        set +a
    fi
    
    # 启动服务
    echo -e "${GREEN}启动 LangGraph Server, Gateway API, Frontend 和 nginx...${NC}"
    make dev &
    
    # 等待服务启动
    sleep 5
    
    # 检查服务是否成功启动
    if curl -s http://localhost:2026 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 所有服务已启动成功！${NC}"
        echo -e "${GREEN}访问地址: http://localhost:2026${NC}"
    else
        echo -e "${YELLOW}⚠ 服务可能未完全启动，请检查日志${NC}"
    fi
}

# 主逻辑
main() {
    echo "========================================"
    echo -e "${GREEN}DeerFlow 服务管理${NC}"
    echo "========================================"
    
    if check_service; then
        echo -e "${YELLOW}检测到服务正在运行${NC}"
        stop_services
        sleep 2
        start_services
    else
        echo -e "${YELLOW}检测到服务未运行${NC}"
        start_services
    fi
}

main "$@"

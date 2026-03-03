#!/usr/bin/env bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"

# Docker Compose command with project name
COMPOSE_CMD="docker compose -p deer-flow-dev -f docker-compose-dev.yaml"

# Cleanup function for Ctrl+C
cleanup() {
    echo ""
    echo -e "${YELLOW}Operation interrupted by user${NC}"
    exit 130
}

# Set up trap for Ctrl+C
trap cleanup INT TERM

# Start Docker development environment
start() {
    local services="frontend gateway langgraph nginx"

    echo "=========================================="
    echo "  Starting DeerFlow Docker Development"
    echo "=========================================="
    echo ""
    
    # Export HOST_SKILLS_PATH for docker-compose to use
    # This is required for the gateway container to know the host path for skills mounting
    export HOST_SKILLS_PATH="$PROJECT_ROOT/skills"
    echo "Setting HOST_SKILLS_PATH to: $HOST_SKILLS_PATH"
    
    echo -e "${BLUE}Using simplified configuration (Host Network Mode)${NC}"
    echo -e "${BLUE}Proxy settings are handled by system configuration (~/.docker/config.json)${NC}"
    echo ""

    echo "Building and starting containers..."
    
    cd "$DOCKER_DIR" && $COMPOSE_CMD up -d --build --remove-orphans $services
    
    echo ""
    echo "=========================================="
    echo "  DeerFlow Docker is starting!"
    echo "=========================================="
    echo ""
    echo "  🌐 Application: http://localhost:2026"
    echo "  📡 API Gateway: http://localhost:2026/api/*"
    echo "  🤖 LangGraph:   http://localhost:2026/api/langgraph/*"
    echo ""
    echo "  📋 View logs: make docker-logs"
    echo "  🛑 Stop:      make docker-stop"
    echo ""
}

# View Docker development logs
logs() {
    local service=""
    
    case "$1" in
        --frontend) service="frontend" ;;
        --gateway) service="gateway" ;;
        --nginx) service="nginx" ;;
        "") echo -e "${BLUE}Viewing all logs...${NC}" ;;
        *)
            echo -e "${YELLOW}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
    
    cd "$DOCKER_DIR" && $COMPOSE_CMD logs -f $service
}

# Stop Docker development environment
stop() {
    echo "Stopping Docker development services..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD down
    echo -e "${GREEN}✓ Docker services stopped${NC}"
}

# Restart Docker development environment
restart() {
    echo "========================================"
    echo "  Restarting DeerFlow Docker Services"
    echo "========================================"
    echo ""
    
    echo "Restarting containers..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD restart
    echo -e "${GREEN}✓ Docker services restarted${NC}"
    
    echo ""
    echo "  🌐 Application: http://localhost:2026"
    echo "  📋 View logs: make docker-logs"
}

# Main script logic
case "$1" in
    start)
        start
        ;;
    logs)
        logs "$2"
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    help|*)
        echo "DeerFlow Docker Management Script"
        echo ""
        echo "Usage: $0 <command> [options]"
        echo ""
        echo "Commands:"
        echo "  start         - Start Docker services"
        echo "  restart       - Restart all running Docker services"
        echo "  logs [option] - View logs (--frontend, --gateway, --nginx)"
        echo "  stop          - Stop Docker services"
        echo "  help          - Show this help message"
        ;;
esac

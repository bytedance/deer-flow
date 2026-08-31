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

# Docker Compose command with project name.
# Use a filename relative to DOCKER_DIR (we always `cd` there) so Windows
# Docker Desktop does not receive a Git Bash `/c/...` path it cannot open.
COMPOSE_FILE="docker-compose-dev.yaml"
# Selected by require_compose_version: prefer the V2 plugin, else hyphenated binary.
# Kept as an array so "docker compose" stays two words under set -u / quoting.
COMPOSE_BIN=(docker compose)

_refresh_compose_cmd() {
    COMPOSE_CMD="${COMPOSE_BIN[*]} -p deer-flow-dev -f ${COMPOSE_FILE}"
}
_refresh_compose_cmd

# docker-compose-dev.yaml marks its env_file entries optional with the long-form
# `- path: ... / required: false` syntax, understood by Compose v2.24.0 and up.
# Older clients abort while parsing the file, before any preflight below can run.
COMPOSE_MIN_VERSION="2.24.0"

ensure_from_example() {
    local dest="$1"
    local src="$2"
    local label="$3"

    if [ -f "$dest" ]; then
        return 0
    fi
    if [ -f "$src" ]; then
        cp "$src" "$dest"
        echo -e "${BLUE}Created ${label} from $(basename "$src")${NC}"
        return 0
    fi
    echo -e "${YELLOW}✗ ${label} not found and no $(basename "$src") to copy from.${NC}"
    echo "Create ${dest} before starting Docker."
    exit 1
}

require_compose_file() {
    if [ -f "$DOCKER_DIR/$COMPOSE_FILE" ]; then
        return 0
    fi
    echo -e "${YELLOW}✗ ${COMPOSE_FILE} not found at ${DOCKER_DIR}/${COMPOSE_FILE}${NC}"
    echo "Run this from the DeerFlow repository root, e.g. 'make docker-start'."
    echo "Do not run 'docker compose -f docker/${COMPOSE_FILE}' from inside docker/ — that resolves to docker/docker/${COMPOSE_FILE}."
    exit 1
}

# Prefer the Compose V2 plugin (`docker compose`); fall back to the legacy
# hyphenated binary (`docker-compose`) when the plugin is missing. Whatever
# binary answers is retained in COMPOSE_BIN / COMPOSE_CMD so start/logs/stop/
# restart use the same executable. Must run in the current shell (not $(...))
# so the COMPOSE_BIN assignment survives. Direct callers get no such check:
# see CONTRIBUTING.md.
_probe_compose() {
    local out

    out="$(docker compose version --short 2>/dev/null || true)"
    if [ -n "$out" ]; then
        COMPOSE_BIN=(docker compose)
        _refresh_compose_cmd
        COMPOSE_VERSION_RAW="$out"
        return 0
    fi
    out="$(docker-compose version --short 2>/dev/null || true)"
    if [ -n "$out" ]; then
        COMPOSE_BIN=(docker-compose)
        _refresh_compose_cmd
        COMPOSE_VERSION_RAW="$out"
        return 0
    fi
    COMPOSE_VERSION_RAW=""
    return 1
}

# Fail with an actionable message instead of the parser error an older client
# emits for the optional env_file syntax.
require_compose_version() {
    local raw major minor min_major min_minor

    min_major="${COMPOSE_MIN_VERSION%%.*}"
    min_minor="${COMPOSE_MIN_VERSION#*.}"
    min_minor="${min_minor%%.*}"

    COMPOSE_VERSION_RAW=""
    _probe_compose || true
    raw="${COMPOSE_VERSION_RAW#v}"
    major="${raw%%.*}"
    minor="${raw#*.}"
    minor="${minor%%.*}"
    major="${major//[!0-9]/}"
    minor="${minor//[!0-9]/}"

    if [ -z "$major" ] || [ -z "$minor" ]; then
        echo -e "${YELLOW}⚠ Could not determine the Docker Compose version; ${COMPOSE_MIN_VERSION} or newer is required.${NC}"
        return 0
    fi
    if [ "$major" -gt "$min_major" ] || { [ "$major" -eq "$min_major" ] && [ "$minor" -ge "$min_minor" ]; }; then
        return 0
    fi

    echo -e "${YELLOW}✗ Docker Compose ${raw} is too old — ${COMPOSE_MIN_VERSION} or newer is required.${NC}"
    echo "${COMPOSE_FILE} marks its env_file entries optional using the long-form"
    echo "'- path: ... / required: false' syntax, which your client cannot parse."
    echo "Update Docker Desktop, or install a current Compose v2 plugin:"
    echo "  https://docs.docker.com/compose/install/"
    exit 1
}

# Compose interpolates ${DEER_FLOW_ROOT} into host-side paths
# (DEER_FLOW_HOST_BASE_DIR, THREADS_HOST_PATH) that AIO/provisioner sandbox
# modes bind-mount. Unset, those render as /backend/.deer-flow — a plausible
# looking absolute path on the wrong root, so mounts silently miss the checkout.
ensure_deer_flow_root() {
    if [ -z "$DEER_FLOW_ROOT" ]; then
        export DEER_FLOW_ROOT="$PROJECT_ROOT"
    fi
}

# Read-only with respect to configuration; safe for logs/stop/restart.
compose_preflight() {
    require_compose_file
    require_compose_version
    ensure_deer_flow_root
}

# Only `start` may create files. Compose env_file entries fail closed on Windows
# when .env is missing ("The specified file cannot be found" /
# "Le fichier spécifique est introuvable").
ensure_env_files() {
    ensure_from_example "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.example" ".env"
    ensure_from_example "$PROJECT_ROOT/frontend/.env" "$PROJECT_ROOT/frontend/.env.example" "frontend/.env"
}

load_proxy_env_from_dotenv() {
    local env_file="$PROJECT_ROOT/.env"
    local var
    local line
    local value

    if [ ! -f "$env_file" ]; then
        return
    fi

    for var in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
        if [ -z "${!var+x}" ]; then
            line="$(grep -E "^[[:space:]]*${var}=" "$env_file" | tail -n 1 || true)"
            if [ -n "$line" ]; then
                value="${line#*=}"
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                value="${value%$'\r'}"
                export "${var}=${value}"
            fi
        fi
    done
}

detect_sandbox_mode() {
    local config_file="$PROJECT_ROOT/config.yaml"
    local sandbox_use=""
    local provisioner_url=""

    if [ ! -f "$config_file" ]; then
        echo "local"
        return
    fi

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*use:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    if [[ "$sandbox_use" == *"deerflow.sandbox.local:LocalSandboxProvider"* ]]; then
        echo "local"
    elif [[ "$sandbox_use" == *"deerflow.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

# Cleanup function for Ctrl+C
cleanup() {
    echo ""
    echo -e "${YELLOW}Operation interrupted by user${NC}"
    exit 130
}

# Set up trap for Ctrl+C
trap cleanup INT TERM

docker_available() {
    # Check that the docker CLI exists
    if ! command -v docker >/dev/null 2>&1; then
        return 1
    fi

    # Check that the Docker daemon is reachable
    if ! docker info >/dev/null 2>&1; then
        return 1
    fi

    return 0
}

# Initialize: pre-pull the sandbox image so first Pod startup is fast
init() {
    echo "=========================================="
    echo "  DeerFlow Init — Pull Sandbox Image"
    echo "=========================================="
    echo ""

    SANDBOX_IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"

    # Detect sandbox mode from config.yaml
    local sandbox_mode
    sandbox_mode="$(detect_sandbox_mode)"

    # Skip image pull for local sandbox mode (no container image needed)
    if [ "$sandbox_mode" = "local" ]; then
        echo -e "${GREEN}Detected local sandbox mode — no Docker image required.${NC}"
        echo ""

        if docker_available; then
            echo -e "${GREEN}✓ Docker environment is ready.${NC}"
            echo ""
            echo -e "${YELLOW}Next step: make docker-start${NC}"
        else
            echo -e "${YELLOW}Docker does not appear to be installed, or the Docker daemon is not reachable.${NC}"
            echo "Local sandbox mode itself does not require Docker, but Docker-based workflows (e.g., docker-start) will fail until Docker is available."
            echo ""
            echo -e "${YELLOW}Install and start Docker, then run: make docker-init && make docker-start${NC}"
        fi

        return 0
    fi

    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${SANDBOX_IMAGE}$"; then
        echo -e "${BLUE}Pulling sandbox image: $SANDBOX_IMAGE ...${NC}"
        echo ""

        if ! docker pull "$SANDBOX_IMAGE" 2>&1; then
            echo ""
            echo -e "${YELLOW}⚠ Failed to pull sandbox image.${NC}"
            echo ""
            echo "This is expected if:"
            echo "  1. You are using local sandbox mode (default — no image needed)"
            echo "  2. You are behind a corporate proxy or firewall"
            echo "  3. The registry requires authentication"
            echo ""
            echo -e "${GREEN}The Docker development environment can still be started.${NC}"
            echo "If you need AIO sandbox (container-based execution):"
            echo "  - Ensure you have network access to the registry"
            echo "  - Or configure a custom sandbox image in config.yaml"
            echo ""
            echo -e "${YELLOW}Next step: make docker-start${NC}"
            return 0
        fi
    else
        echo -e "${GREEN}Sandbox image already exists locally: $SANDBOX_IMAGE${NC}"
    fi

    echo ""
    echo -e "${GREEN}✓ Sandbox image is ready.${NC}"
    echo ""
    echo -e "${YELLOW}Next step: make docker-start${NC}"
}

# Start Docker development environment
start() {
    local sandbox_mode
    local services

    if [ "$#" -gt 0 ]; then
        echo -e "${YELLOW}Unknown option for start: $1${NC}"
        echo "Usage: $0 start"
        exit 1
    fi

    echo "=========================================="
    echo "  Starting DeerFlow Docker Development"
    echo "=========================================="
    echo ""

    # Validate the toolchain before creating any config files below.
    compose_preflight

    sandbox_mode="$(detect_sandbox_mode)"

    services="redis frontend gateway nginx"
    if [ "$sandbox_mode" = "provisioner" ]; then
        services="redis frontend gateway provisioner nginx"
    fi

    # Only aio mode (AioSandboxProvider without provisioner_url) needs the host
    # Docker socket. Mount it via the opt-in docker-compose.dood.yaml overlay so
    # the default (local) and provisioner modes never expose the host daemon.
    # Mounting the socket = root-equivalent host control; see SECURITY.md.
    if [ "$sandbox_mode" = "aio" ]; then
        local docker_socket="${DEER_FLOW_DOCKER_SOCKET:-/var/run/docker.sock}"
        if [ ! -S "$docker_socket" ]; then
            echo -e "${YELLOW}⚠ Docker socket not found at $docker_socket — AioSandboxProvider (DooD) will not work.${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Mounting host Docker socket into gateway (DooD = host root-equivalent). See SECURITY.md.${NC}"
        COMPOSE_CMD="$COMPOSE_CMD -f docker-compose.dood.yaml"
    fi

    echo -e "${BLUE}Runtime: Gateway embedded agent runtime${NC}"
    echo -e "${BLUE}Detected sandbox mode: $sandbox_mode${NC}"
    if [ "$sandbox_mode" = "provisioner" ]; then
        echo -e "${BLUE}Provisioner enabled (Kubernetes mode).${NC}"
    else
        echo -e "${BLUE}Provisioner disabled (not required for this sandbox mode).${NC}"
    fi
    echo ""
    
    # Set by compose_preflight above; shown because the provisioner turns it into
    # host-side bind-mount paths.
    echo -e "${BLUE}Using DEER_FLOW_ROOT=$DEER_FLOW_ROOT${NC}"
    echo ""

    # Ensure config.yaml exists before starting.
    if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
        if [ -f "$PROJECT_ROOT/config.example.yaml" ]; then
            cp "$PROJECT_ROOT/config.example.yaml" "$PROJECT_ROOT/config.yaml"
            echo ""
            echo -e "${YELLOW}============================================================${NC}"
            echo -e "${YELLOW}  config.yaml has been created from config.example.yaml.${NC}"
            echo -e "${YELLOW}  Please edit config.yaml to set your API keys and model   ${NC}"
            echo -e "${YELLOW}  configuration before starting DeerFlow.                  ${NC}"
            echo -e "${YELLOW}============================================================${NC}"
            echo ""
            echo -e "${YELLOW}  Recommended: run 'make setup' before starting Docker.    ${NC}"
            echo -e "${YELLOW}  Edit the file:  $PROJECT_ROOT/config.yaml${NC}"
            echo -e "${YELLOW}  Then run:        make docker-start${NC}"
            echo ""
            exit 0
        else
            echo -e "${YELLOW}✗ config.yaml not found and no config.example.yaml to copy from.${NC}"
            exit 1
        fi
    fi

    # Ensure extensions_config.json exists as a file before mounting.
    # Docker creates a directory when bind-mounting a non-existent host path.
    if [ ! -f "$PROJECT_ROOT/extensions_config.json" ]; then
        if [ -f "$PROJECT_ROOT/extensions_config.example.json" ]; then
            cp "$PROJECT_ROOT/extensions_config.example.json" "$PROJECT_ROOT/extensions_config.json"
            echo -e "${BLUE}Created extensions_config.json from example${NC}"
        else
            echo "{}" > "$PROJECT_ROOT/extensions_config.json"
            echo -e "${BLUE}Created empty extensions_config.json${NC}"
        fi
    fi

    ensure_env_files
    load_proxy_env_from_dotenv

    echo "Building and starting containers..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD up --build -d --remove-orphans $services
    echo ""
    echo "=========================================="
    echo "  DeerFlow Docker is starting!"
    echo "=========================================="
    echo ""
    echo "  🌐 Application: http://localhost:2026"
    echo "  📡 API Gateway: http://localhost:2026/api/*"
    echo "  🤖 Runtime:     Gateway embedded"
    echo "  API:            /api/langgraph/* → Gateway"
    echo ""
    echo "  📋 View logs: make docker-logs"
    echo "  🛑 Stop:      make docker-stop"
    echo ""
}

# View Docker development logs
logs() {
    local service=""

    compose_preflight

    case "$1" in
        --frontend)
            service="frontend"
            echo -e "${BLUE}Viewing frontend logs...${NC}"
            ;;
        --gateway)
            service="gateway"
            echo -e "${BLUE}Viewing gateway logs...${NC}"
            ;;
        --nginx)
            service="nginx"
            echo -e "${BLUE}Viewing nginx logs...${NC}"
            ;;
        --redis)
            service="redis"
            echo -e "${BLUE}Viewing redis logs...${NC}"
            ;;
        --provisioner)
            service="provisioner"
            echo -e "${BLUE}Viewing provisioner logs...${NC}"
            ;;
        "")
            echo -e "${BLUE}Viewing all logs...${NC}"
            ;;
        *)
            echo -e "${YELLOW}Unknown option: $1${NC}"
            echo "Usage: $0 logs [--frontend|--gateway|--nginx|--redis|--provisioner]"
            exit 1
            ;;
    esac
    
    cd "$DOCKER_DIR" && $COMPOSE_CMD logs -f $service
}

# Stop Docker development environment
stop() {
    compose_preflight
    echo "Stopping Docker development services..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD down
    echo "Cleaning up sandbox containers..."
    bash "$SCRIPT_DIR/cleanup-containers.sh" deer-flow-sandbox 2>/dev/null || true
    echo -e "${GREEN}✓ Docker services stopped${NC}"
}

# Restart Docker development environment
restart() {
    compose_preflight
    echo "========================================"
    echo "  Restarting DeerFlow Docker Services"
    echo "========================================"
    echo ""
    echo -e "${BLUE}Restarting containers...${NC}"
    cd "$DOCKER_DIR" && $COMPOSE_CMD restart
    echo ""
    echo -e "${GREEN}✓ Docker services restarted${NC}"
    echo ""
    echo "  🌐 Application: http://localhost:2026"
    echo "  📋 View logs: make docker-logs"
    echo ""
}

# Show help
help() {
    echo "DeerFlow Docker Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  init              - Pull the sandbox image (speeds up first Pod startup)"
    echo "  start             - Start Docker services (auto-detects sandbox mode from config.yaml)"
    echo "  restart           - Restart all running Docker services"
    echo "  logs [option] - View Docker development logs"
    echo "                  --frontend   View frontend logs only"
    echo "                  --gateway    View gateway logs only"
    echo "                  --nginx      View nginx logs only"
    echo "                  --redis      View redis logs only"
    echo "                  --provisioner View provisioner logs only"
    echo "  stop          - Stop Docker development services"
    echo "  help          - Show this help message"
    echo ""
}

main() {
    # Main command dispatcher
    case "$1" in
        init)
            init
            ;;
        start)
            shift
            start "$@"
            ;;
        restart)
            restart
            ;;
        logs)
            logs "$2"
            ;;
        stop)
            stop
            ;;
        help|--help|-h|"")
            help
            ;;
        *)
            echo -e "${YELLOW}Unknown command: $1${NC}"
            echo ""
            help
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi

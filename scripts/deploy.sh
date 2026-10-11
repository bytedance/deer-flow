#!/usr/bin/env bash
#
# deploy.sh - Build, start, or stop DeerFlow production services
#
# Commands:
#   deploy.sh                    — build + start
#   deploy.sh build              — build all images (mode-agnostic)
#   deploy.sh start              — start from pre-built images
#   deploy.sh down               — stop and remove containers
#
# Sandbox mode (local / aio / provisioner) is auto-detected from config.yaml.
#
# Examples:
#   deploy.sh                    # build + start
#   deploy.sh build              # build all images
#   deploy.sh start              # start pre-built images
#   deploy.sh down               # stop and remove containers
#
# Must be run from the repo root directory.

set -e

case "${1:-}" in
    build|start|down)
        CMD="$1"
        if [ -n "${2:-}" ]; then
            echo "Unknown argument: $2"
            echo "Usage: deploy.sh [build|start|down]"
            exit 1
        fi
        ;;
    "")
        CMD=""
        ;;
    *)
        echo "Unknown argument: $1"
        echo "Usage: deploy.sh [build|start|down]"
        exit 1
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${DEER_FLOW_COMPOSE_ENV_FILE:-$REPO_ROOT/.env}"
# Docker Compose's interpolation file and service env_file must select the same
# host file. Relative selectors are rooted at this checkout, not docker/.
if command -v cygpath >/dev/null 2>&1; then
    ENV_FILE="$(cygpath -au -- "$ENV_FILE")"
elif [[ "$ENV_FILE" != /* ]]; then
    ENV_FILE="$REPO_ROOT/$ENV_FILE"
fi
if [ -n "${DEER_FLOW_COMPOSE_ENV_FILE:-}" ] && [ "$CMD" != "down" ] && { [ ! -f "$ENV_FILE" ] || [ ! -r "$ENV_FILE" ]; }; then
    echo "DEER_FLOW_COMPOSE_ENV_FILE must name a readable file: $ENV_FILE" >&2
    exit 1
fi
export DEER_FLOW_COMPOSE_ENV_FILE="$ENV_FILE"
DOCKER_DIR="$REPO_ROOT/docker"
COMPOSE_ENV_FILE_ARGS=()
if [ -f "$ENV_FILE" ]; then
    COMPOSE_ENV_FILE_ARGS=(--env-file "$ENV_FILE")
fi
COMPOSE_CMD=(docker compose "${COMPOSE_ENV_FILE_ARGS[@]}" -p deer-flow -f "$DOCKER_DIR/docker-compose.yaml")

load_uv_extras_from_dotenv() {
    local line=""
    local value=""

    [ -f "$ENV_FILE" ] || return 0
    [ -z "${UV_EXTRAS+x}" ] || return 0

    line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?UV_EXTRAS[[:space:]]*=' "$ENV_FILE" | tail -n 1 || true)"
    [ -n "$line" ] || return 0

    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    case "$value" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    export UV_EXTRAS="$value"
}

load_uv_extras_from_dotenv

# Read one key from $ENV_FILE the way compose --env-file interpolates it, so the
# final summary reports the values the stack actually came up with. The shell
# does not source $ENV_FILE, so reading these from the environment alone would
# report "loopback only" for a stack that .env exposed to the network.
read_dotenv_value() {
    local key="$1"
    local line=""
    local value=""

    # An exported shell variable wins, matching compose precedence.
    if [ -n "${!key+x}" ]; then
        printf '%s' "${!key}"
        return 0
    fi

    [ -f "$ENV_FILE" ] || return 0

    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$ENV_FILE" | tail -n 1 || true)"
    [ -n "$line" ] || return 0

    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    case "$value" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    printf '%s' "$value"
}

# ── Colors ────────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ── DEER_FLOW_HOME ────────────────────────────────────────────────────────────

if [ -z "$DEER_FLOW_HOME" ]; then
    export DEER_FLOW_HOME="$REPO_ROOT/backend/.deer-flow"
fi
echo -e "${BLUE}DEER_FLOW_HOME=$DEER_FLOW_HOME${NC}"
mkdir -p "$DEER_FLOW_HOME"

# ── DEER_FLOW_HOME writability preflight ─────────────────────────────────────

# `make docker-start` bind-mounts the host `backend/` directory into the gateway
# container, whose process runs as root, so state it creates under
# backend/.deer-flow ends up owned by root on the host. A later `make up` runs
# this script as the invoking user and only fails deep into the run with a bare
# "Permission denied" while persisting generated secrets. Detect it up front and
# print the exact recovery command instead.
fail_home_permission() {
    echo -e "${RED}✗ $1 is not $2 by '$(id -un)'.${NC}" >&2
    echo -e "${RED}  This usually happens when the dev stack (make docker-start) created it as root.${NC}" >&2
    echo -e "${YELLOW}  Recover with: sudo chown -R $(id -u):$(id -g) '$DEER_FLOW_HOME'${NC}" >&2
    exit 1
}

if [ "$CMD" != "down" ] && [ ! -w "$DEER_FLOW_HOME" ]; then
    fail_home_permission "$DEER_FLOW_HOME" writable
fi

# ── DEER_FLOW_REPO_ROOT (for skills host path in DooD) ───────────────────────

export DEER_FLOW_REPO_ROOT="$REPO_ROOT"

# ── config.yaml ───────────────────────────────────────────────────────────────

if [ -z "$DEER_FLOW_CONFIG_PATH" ]; then
    export DEER_FLOW_CONFIG_PATH="$REPO_ROOT/config.yaml"
fi

if  [ "$CMD" != "down" ] && [ ! -f "$DEER_FLOW_CONFIG_PATH" ]; then
    # Try to seed from repo (config.example.yaml is the canonical template)
    if [ -f "$REPO_ROOT/config.example.yaml" ]; then
        cp "$REPO_ROOT/config.example.yaml" "$DEER_FLOW_CONFIG_PATH"
        echo -e "${GREEN}✓ Seeded config.example.yaml → $DEER_FLOW_CONFIG_PATH${NC}"
        echo -e "${YELLOW}⚠ config.yaml was seeded from the example template.${NC}"
        echo "  Run 'make setup' to generate a minimal config, or edit $DEER_FLOW_CONFIG_PATH manually before use."
    else
        echo -e "${RED}✗ No config.yaml found.${NC}"
        echo "  Run 'make setup' from the repo root (recommended),"
        echo "  or 'make config' for the full template, then set the required model API keys."
        exit 1
    fi
else
    echo -e "${GREEN}✓ config.yaml: $DEER_FLOW_CONFIG_PATH${NC}"
fi

# ── extensions_config.json ───────────────────────────────────────────────────

if [ -z "$DEER_FLOW_EXTENSIONS_CONFIG_PATH" ]; then
    export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$REPO_ROOT/extensions_config.json"
fi

if [ ! -f "$DEER_FLOW_EXTENSIONS_CONFIG_PATH" ]; then
    if [ -f "$REPO_ROOT/extensions_config.json" ]; then
        cp "$REPO_ROOT/extensions_config.json" "$DEER_FLOW_EXTENSIONS_CONFIG_PATH"
        echo -e "${GREEN}✓ Seeded extensions_config.json → $DEER_FLOW_EXTENSIONS_CONFIG_PATH${NC}"
    else
        # Create a minimal empty config so the gateway doesn't fail on startup
        echo '{"mcpServers":{},"skills":{}}' > "$DEER_FLOW_EXTENSIONS_CONFIG_PATH"
        echo -e "${YELLOW}⚠ extensions_config.json not found, created empty config at $DEER_FLOW_EXTENSIONS_CONFIG_PATH${NC}"
    fi
else
    echo -e "${GREEN}✓ extensions_config.json: $DEER_FLOW_EXTENSIONS_CONFIG_PATH${NC}"
fi


# Compose interpolates ${BETTER_AUTH_SECRET} and ${DEER_FLOW_INTERNAL_AUTH_TOKEN}
# from the shell environment first and --env-file second. A secret the operator
# wrote to $ENV_FILE therefore only reaches the stack while this script does not
# export a competing value: generating or reloading one here would silently
# replace it. Leave a dotenv-provided secret unexported so compose parses it
# from $ENV_FILE itself, and only fall back to the persisted/generated one
# when neither the shell nor $ENV_FILE provides it.
#
# "Provided" has to mean what Compose will see, not what a KEY=VALUE grep
# finds: Compose also accepts `KEY: VALUE` lines and interpolates `${VAR}`
# inside values, so `TOKEN: abc` is set and `TOKEN=${UNSET}` is empty. Ask
# Compose itself: render a stub project whose only environment entry is
# `${KEY}`, with the same --env-file and project directory as the real
# command, and read the interpolated value back. This works on every Compose
# v2 (unlike `config --environment`, which needs 2.28), needs no daemon, and
# cannot fail on the real compose file before the secrets are decided. An
# empty or unset variable renders as `""`.
compose_interpolated_value() {
    local key="$1"
    local rendered=""
    if ! rendered="$(printf 'services:\n  probe:\n    image: scratch\n    environment:\n      DEER_FLOW_PROBE_VALUE: ${%s}\n' "$key" \
        | docker compose "${COMPOSE_ENV_FILE_ARGS[@]}" --project-directory "$DOCKER_DIR" -f - config 2>&1)"; then
        echo -e "${RED}✗ docker compose could not resolve $key from the environment and $ENV_FILE:${NC}" >&2
        printf '%s\n' "$rendered" >&2
        exit 1
    fi
    printf '%s\n' "$rendered" | sed -n 's/^[[:space:]]*DEER_FLOW_PROBE_VALUE: //p' | head -n 1
}

dotenv_provides_secret() {
    local value=""
    # The probe runs in a subshell, so its exit 1 must be re-raised here.
    value="$(compose_interpolated_value "$1")" || exit 1
    [ -n "$value" ] && [ "$value" != '""' ]
}

# ── BETTER_AUTH_SECRET ───────────────────────────────────────────────────────
# Required by Next.js in production. Generated once and persisted so auth
# sessions survive container restarts.

_secret_file="$DEER_FLOW_HOME/.better-auth-secret"
if [ "$CMD" != "down" ] && [ -z "$BETTER_AUTH_SECRET" ] && dotenv_provides_secret BETTER_AUTH_SECRET; then
    echo -e "${GREEN}✓ BETTER_AUTH_SECRET loaded from $ENV_FILE${NC}"
elif [ "$CMD" != "down" ] && [ -z "$BETTER_AUTH_SECRET" ]; then
    if [ -f "$_secret_file" ]; then
        # A writable directory can still contain a root-owned, unreadable file.
        # Persisted secrets are only read; read-only files and overrides are valid.
        if [ ! -r "$_secret_file" ]; then
            fail_home_permission "$_secret_file" readable
        fi
        export BETTER_AUTH_SECRET
        BETTER_AUTH_SECRET="$(cat "$_secret_file")"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET loaded from $_secret_file${NC}"
    else
        export BETTER_AUTH_SECRET
        if command -v python3 > /dev/null 2>&1 && \
            BETTER_AUTH_SECRET="$(python3 -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_hex(32))' 2>/dev/null)"; then
            true
        elif command -v python > /dev/null 2>&1 && \
            BETTER_AUTH_SECRET="$(python -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_hex(32))' 2>/dev/null)"; then
            true
        elif command -v openssl > /dev/null 2>&1 && \
            BETTER_AUTH_SECRET="$(openssl rand -hex 32)"; then
            true
        else
            echo -e "${RED}✗ Cannot generate BETTER_AUTH_SECRET: python3, python, and openssl are all unavailable.${NC}" >&2
            echo -e "${RED}  Set BETTER_AUTH_SECRET manually before running make up.${NC}" >&2
            exit 1
        fi
        echo "$BETTER_AUTH_SECRET" > "$_secret_file"
        chmod 600 "$_secret_file"
        echo -e "${GREEN}✓ BETTER_AUTH_SECRET generated → $_secret_file${NC}"
    fi
fi

# ── DEER_FLOW_INTERNAL_AUTH_TOKEN ────────────────────────────────────────────
# Shared by all Gateway workers so channel workers can call internal Gateway
# APIs even when the request is handled by a different Uvicorn worker.

_internal_auth_token_file="$DEER_FLOW_HOME/.internal-auth-token"
if [ "$CMD" != "down" ] && [ -z "$DEER_FLOW_INTERNAL_AUTH_TOKEN" ] && dotenv_provides_secret DEER_FLOW_INTERNAL_AUTH_TOKEN; then
    echo -e "${GREEN}✓ DEER_FLOW_INTERNAL_AUTH_TOKEN loaded from $ENV_FILE${NC}"
elif [ "$CMD" != "down" ] && [ -z "$DEER_FLOW_INTERNAL_AUTH_TOKEN" ]; then
    if [ -f "$_internal_auth_token_file" ]; then
        if [ ! -r "$_internal_auth_token_file" ]; then
            fail_home_permission "$_internal_auth_token_file" readable
        fi
        export DEER_FLOW_INTERNAL_AUTH_TOKEN
        DEER_FLOW_INTERNAL_AUTH_TOKEN="$(cat "$_internal_auth_token_file")"
        echo -e "${GREEN}✓ DEER_FLOW_INTERNAL_AUTH_TOKEN loaded from $_internal_auth_token_file${NC}"
    else
        export DEER_FLOW_INTERNAL_AUTH_TOKEN
        if command -v python3 > /dev/null 2>&1 && \
            DEER_FLOW_INTERNAL_AUTH_TOKEN="$(python3 -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null)"; then
            true
        elif command -v python > /dev/null 2>&1 && \
            DEER_FLOW_INTERNAL_AUTH_TOKEN="$(python -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null)"; then
            true
        elif command -v openssl > /dev/null 2>&1 && \
            DEER_FLOW_INTERNAL_AUTH_TOKEN="$(openssl rand -hex 32)"; then
            true
        else
            echo -e "${RED}✗ Cannot generate DEER_FLOW_INTERNAL_AUTH_TOKEN: python3, python, and openssl are all unavailable.${NC}" >&2
            echo -e "${RED}  Set DEER_FLOW_INTERNAL_AUTH_TOKEN manually before running make up.${NC}" >&2
            exit 1
        fi
        echo "$DEER_FLOW_INTERNAL_AUTH_TOKEN" > "$_internal_auth_token_file"
        chmod 600 "$_internal_auth_token_file"
        echo -e "${GREEN}✓ DEER_FLOW_INTERNAL_AUTH_TOKEN generated → $_internal_auth_token_file${NC}"
    fi
fi

# ── DEER_FLOW_CREDENTIALS_KEY ────────────────────────────────────────────────
# At-rest Fernet key the Gateway encrypts stored credentials with. Losing it
# makes those credentials unreadable, so back the file up. It is persisted
# under the name the Gateway itself generates in its runtime home (the
# $DEER_FLOW_HOME bind mount), so a key either side created first is the one
# both keep. noclobber turns the redirection into an exclusive (O_EXCL)
# create: when a concurrent run wins, its key is read back instead of ours.

_credentials_key_file="$DEER_FLOW_HOME/.credentials_key"
if [ "$CMD" != "down" ] && [ -z "$DEER_FLOW_CREDENTIALS_KEY" ] && dotenv_provides_secret DEER_FLOW_CREDENTIALS_KEY; then
    echo -e "${GREEN}✓ DEER_FLOW_CREDENTIALS_KEY loaded from $ENV_FILE${NC}"
elif [ "$CMD" != "down" ] && [ -z "$DEER_FLOW_CREDENTIALS_KEY" ]; then
    _generated_credentials_key=""
    if [ ! -f "$_credentials_key_file" ]; then
        # urlsafe base64 of 32 random bytes, the Fernet key format.
        if command -v python3 > /dev/null 2>&1 && \
            _generated_credentials_key="$(python3 -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null)"; then
            true
        elif command -v python > /dev/null 2>&1 && \
            _generated_credentials_key="$(python -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1); import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null)"; then
            true
        elif command -v openssl > /dev/null 2>&1 && \
            _generated_credentials_key="$(openssl rand -base64 32 | tr '+/' '-_')"; then
            true
        else
            echo -e "${RED}✗ Cannot generate DEER_FLOW_CREDENTIALS_KEY: python3, python, and openssl are all unavailable.${NC}" >&2
            echo -e "${RED}  Set DEER_FLOW_CREDENTIALS_KEY manually before running make up.${NC}" >&2
            exit 1
        fi
        if ! ( umask 077; set -o noclobber; printf '%s\n' "$_generated_credentials_key" > "$_credentials_key_file" ) 2>/dev/null; then
            _generated_credentials_key=""
        fi
    fi
    if [ -n "$_generated_credentials_key" ]; then
        export DEER_FLOW_CREDENTIALS_KEY="$_generated_credentials_key"
        echo -e "${GREEN}✓ DEER_FLOW_CREDENTIALS_KEY generated → $_credentials_key_file (back it up)${NC}"
    else
        if [ ! -r "$_credentials_key_file" ]; then
            fail_home_permission "$_credentials_key_file" readable
        fi
        export DEER_FLOW_CREDENTIALS_KEY
        DEER_FLOW_CREDENTIALS_KEY="$(cat "$_credentials_key_file")"
        echo -e "${GREEN}✓ DEER_FLOW_CREDENTIALS_KEY loaded from $_credentials_key_file${NC}"
    fi
    unset _generated_credentials_key
fi

# ── UV_EXTRAS auto-detection ─────────────────────────────────────────────────
# The production Dockerfile accepts UV_EXTRAS as a single build-arg token and
# adds the --extra prefix itself. Convert the detector's uv flag string
# ("--extra postgres --extra discord") to a comma-joined name token.

if [ "$CMD" != "down" ] && [ -z "$UV_EXTRAS" ]; then
    _detect_python=""
    for _python in python3 python; do
        if command -v "$_python" >/dev/null 2>&1 && \
            "$_python" -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1)' >/dev/null 2>&1; then
            _detect_python="$_python"
            break
        fi
    done
fi

if [ "$CMD" != "down" ] && [ -z "$UV_EXTRAS" ] && [ -n "$_detect_python" ]; then
    _uv_extras_flags="$("$_detect_python" "$REPO_ROOT/scripts/detect_uv_extras.py" 2>/dev/null || true)"
    _uv_extras=""
    set -- $_uv_extras_flags
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "--extra" ] && [ "$#" -gt 1 ]; then
            if [ -z "$_uv_extras" ]; then
                _uv_extras="$2"
            else
                _uv_extras="$_uv_extras,$2"
            fi
            shift 2
        else
            shift
        fi
    done
    if [ -n "$_uv_extras" ]; then
        export UV_EXTRAS="$_uv_extras"
        echo -e "${GREEN}✓ Auto-detected UV_EXTRAS=${UV_EXTRAS} from config.yaml${NC}"
    fi
fi

# ── detect_sandbox_mode ───────────────────────────────────────────────────────

detect_sandbox_mode() {
    local sandbox_use=""
    local provisioner_url=""

    [ -f "$DEER_FLOW_CONFIG_PATH" ] || { echo "local"; return; }

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*use:[[:space:]]*/, "", line); print line; exit
        }
    ' "$DEER_FLOW_CONFIG_PATH")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line); print line; exit
        }
    ' "$DEER_FLOW_CONFIG_PATH")

    if [[ "$sandbox_use" == *"deerflow.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

# ── down ──────────────────────────────────────────────────────────────────────

if [ "$CMD" = "down" ]; then
    # Set minimal env var defaults so docker compose can parse the file without
    # warning about unset variables that appear in volume specs.
    export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$REPO_ROOT/backend/.deer-flow}"
    export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$DEER_FLOW_HOME/config.yaml}"
    export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$DEER_FLOW_HOME/extensions_config.json}"
    export DEER_FLOW_REPO_ROOT="${DEER_FLOW_REPO_ROOT:-$REPO_ROOT}"
    export BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-placeholder}"
    export DEER_FLOW_INTERNAL_AUTH_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-placeholder}"
    "${COMPOSE_CMD[@]}" down
    exit 0
fi

# ── build ────────────────────────────────────────────────────────────────────
# Build produces mode-agnostic images. No --gateway or sandbox detection needed.

if [ "$CMD" = "build" ]; then
    echo "=========================================="
    echo "  DeerFlow — Building Images"
    echo "=========================================="
    echo ""

    "${COMPOSE_CMD[@]}" build

    echo ""
    echo "=========================================="
    echo "  ✓ Images built successfully"
    echo "=========================================="
    echo ""
    echo "  Next: deploy.sh start"
    echo ""
    exit 0
fi

# ── Banner ────────────────────────────────────────────────────────────────────

echo "=========================================="
echo "  DeerFlow Production Deployment"
echo "=========================================="
echo ""

# ── Detect runtime configuration ────────────────────────────────────────────
# Only needed for start / up — determines whether provisioner is launched.

sandbox_mode="$(detect_sandbox_mode)"
echo -e "${BLUE}Sandbox mode: $sandbox_mode${NC}"

echo -e "${BLUE}Runtime: Gateway embedded agent runtime${NC}"

services="redis frontend gateway nginx"

if [ "$sandbox_mode" = "provisioner" ]; then
    services="$services provisioner"
fi

# ── DEER_FLOW_DOCKER_SOCKET (aio / pure-DooD mode only) ──────────────────────
# Only aio mode (AioSandboxProvider without provisioner_url) needs the host
# Docker socket. It is mounted via the opt-in docker-compose.dood.yaml overlay,
# appended here, so the default (local) and provisioner modes never expose the
# host daemon. Mounting the socket = root-equivalent host control; see SECURITY.md.

docker_socket="$(read_dotenv_value DEER_FLOW_DOCKER_SOCKET)"
docker_socket="${docker_socket:-/var/run/docker.sock}"

if [ "$sandbox_mode" = "aio" ]; then
    if [ ! -S "$docker_socket" ]; then
        # On Windows (Git Bash / MSYS), Docker Desktop mounts the default
        # /var/run/docker.sock into containers even though no host socket file exists.
        if [ "$docker_socket" = "/var/run/docker.sock" ] && [[ "$(uname -s)" =~ ^(MINGW|MSYS|CYGWIN) ]] && docker info >/dev/null 2>&1; then
            :
        else
            echo -e "${RED}⚠ Docker socket not found at $docker_socket${NC}"
            echo "  AioSandboxProvider (DooD) will not work."
            exit 1
        fi
    fi
    # On Windows (Git Bash / MSYS), exporting /var/run/docker.sock causes MSYS to
    # convert it to C:\Program Files\Git\var\run\docker.sock when invoking native
    # docker compose, triggering mkdir errors. Unsetting the default allows Compose
    # to evaluate its own default literal fallback (${DEER_FLOW_DOCKER_SOCKET:-/var/run/docker.sock}).
    if [[ "$(uname -s)" =~ ^(MINGW|MSYS|CYGWIN) ]] && [ "$DEER_FLOW_DOCKER_SOCKET" = "/var/run/docker.sock" ]; then
        unset DEER_FLOW_DOCKER_SOCKET
    fi
    echo -e "${GREEN}✓ Docker socket: $docker_socket${NC}"
    echo -e "${YELLOW}  Mounting host Docker socket into gateway (DooD = host root-equivalent). See SECURITY.md.${NC}"
    COMPOSE_CMD+=(-f "$DOCKER_DIR/docker-compose.dood.yaml")
fi

echo ""

# ── Start / Up ───────────────────────────────────────────────────────────────

report_startup_failure() {
    echo -e "${RED}✗ DeerFlow services failed to become ready.${NC}" >&2
    echo '  If Docker Compose reports "unknown flag: --wait", upgrade to a version that' >&2
    echo '  supports `docker compose up --wait`.' >&2
    echo '  If it reports "env_file.0 must be a string", upgrade to Docker Compose 2.24+.' >&2
    echo "  Container status:" >&2
    "${COMPOSE_CMD[@]}" ps >&2 || true
    echo "" >&2
    echo "  Recent Gateway logs:" >&2
    "${COMPOSE_CMD[@]}" logs --no-color --tail 100 gateway >&2 || true
}

if [ "$CMD" = "start" ]; then
    echo "Starting containers (no rebuild)..."
    echo ""
    # shellcheck disable=SC2086
    if ! "${COMPOSE_CMD[@]}" up -d --remove-orphans --wait --wait-timeout 180 $services; then
        report_startup_failure
        exit 1
    fi
else
    # Default: build + start
    echo "Building images and starting containers..."
    echo ""
    # shellcheck disable=SC2086
    if ! "${COMPOSE_CMD[@]}" up --build -d --remove-orphans --wait --wait-timeout 180 $services; then
        report_startup_failure
        exit 1
    fi
fi

echo ""
echo "=========================================="
echo "  DeerFlow is running!"
echo "=========================================="
echo ""
RESOLVED_PORT="$(read_dotenv_value PORT)"
RESOLVED_PORT="${RESOLVED_PORT:-2026}"
RESOLVED_BIND_HOST="$(read_dotenv_value BIND_HOST)"
RESOLVED_BIND_HOST="${RESOLVED_BIND_HOST:-127.0.0.1}"

echo "  🌐 Application: http://localhost:${RESOLVED_PORT}"
echo "  📡 API Gateway: http://localhost:${RESOLVED_PORT}/api/*"
echo "  🤖 Runtime:     Gateway embedded"
echo "  API:            /api/langgraph/* → Gateway"
echo ""
if [ "$RESOLVED_BIND_HOST" = "127.0.0.1" ] || [ "$RESOLVED_BIND_HOST" = "::1" ] || [ "$RESOLVED_BIND_HOST" = "localhost" ]; then
    echo "  🔒 Bound to ${RESOLVED_BIND_HOST} — reachable from this machine only."
    echo "     To expose it, set BIND_HOST in the selected dotenv file, put TLS/auth in front, and"
    echo "     create the admin account before the host becomes reachable."
else
    echo "  ⚠️  Bound to ${RESOLVED_BIND_HOST} — reachable from the network."
    echo "     Open http://localhost:${RESOLVED_PORT} and complete first-run"
    echo "     setup now, before anyone else reaches this host."
fi
echo ""
echo "  Manage:"
echo "    make down        — stop and remove containers"
echo "    make docker-logs — view logs"
echo ""

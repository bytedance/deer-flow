#!/usr/bin/env bash
#
# dev_multi_instance.sh — run two Gateways as one local multi-instance cluster.
#
# Starts throwaway Postgres and Redis containers, renders a multi-instance
# config.yaml from your own config (or config.example.yaml), and runs Gateway A
# and Gateway B on one shared DEER_FLOW_HOME with shared auth secrets, plus an
# optional round-robin nginx in front of both. Run with --help for commands.
#
# Config rendering, secrets, the nginx config and the checks live in
# dev_multi_instance.py (unit-tested); this file owns containers and processes.
# Everything lives under DEERFLOW_MI_STATE_DIR so it never collides with
# `make dev` state in backend/.deer-flow.

set -euo pipefail

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
BACKEND_DIR="$REPO_ROOT/backend"
HELPER="$REPO_ROOT/scripts/dev_multi_instance.py"

STATE_DIR="${DEERFLOW_MI_STATE_DIR:-$REPO_ROOT/.deer-flow/multi-instance}"
# Gateways run from backend/, so every path handed to them must be absolute.
case "$STATE_DIR" in
    /*) ;;
    *) STATE_DIR="$PWD/$STATE_DIR" ;;
esac
GATEWAY_A_PORT="${DEERFLOW_MI_GATEWAY_A_PORT:-8001}"
GATEWAY_B_PORT="${DEERFLOW_MI_GATEWAY_B_PORT:-8011}"
NGINX_PORT="${DEERFLOW_MI_NGINX_PORT:-2027}"
FRONTEND_PORT="${DEERFLOW_MI_FRONTEND_PORT:-3000}"
PG_PORT="${DEERFLOW_MI_POSTGRES_PORT:-55432}"
REDIS_PORT="${DEERFLOW_MI_REDIS_PORT:-56379}"
PG_CONTAINER="${DEERFLOW_MI_POSTGRES_CONTAINER:-deerflow-mi-postgres}"
REDIS_CONTAINER="${DEERFLOW_MI_REDIS_CONTAINER:-deerflow-mi-redis}"
PG_IMAGE="${DEERFLOW_MI_POSTGRES_IMAGE:-postgres:17-alpine}"
REDIS_IMAGE="${DEERFLOW_MI_REDIS_IMAGE:-redis:7-alpine}"
HEALTH_TIMEOUT="${DEERFLOW_MI_HEALTH_TIMEOUT:-180}"

LABEL_KEY="deerflow.harness"
LABEL_VALUE="dev-multi-instance"
# Container names are global, so each container also records the state dir
# that created it; only that state dir may remove it.
STATE_LABEL_KEY="deerflow.harness.state-dir"
STATE_MARKER=".dev-multi-instance"
RUN_DIR="$STATE_DIR/run"
LOG_DIR="$STATE_DIR/logs"
CONFIG_OUT="$STATE_DIR/config.yaml"
EXTENSIONS_OUT="$STATE_DIR/extensions_config.json"
SECRETS_FILE="$STATE_DIR/secrets.env"

usage() {
    cat <<EOF
Usage: scripts/dev_multi_instance.sh <command> [options]

Run two DeerFlow Gateways (A and B) on shared Postgres, Redis and
DEER_FLOW_HOME: the topology that deployment.multi_instance: true targets.

Commands:
  up [--skip-install] [--no-nginx]  Start containers, render the config, start A, then B, then nginx
  down                              Stop everything; delete the containers and harness data (logs are kept)
  status                            Show containers, Gateways and nginx
  logs [a|b|nginx|all] [-f]         Print the last 100 log lines (-f follows)
  check [--with-llm]                Run the cross-instance checks against the running pair
  stop <a|b> [--kill]               Stop one Gateway (SIGTERM; --kill sends SIGKILL to simulate a crash)
  start <a|b>                       Start a stopped Gateway again
  restart <a|b>                     stop + start
  help                              Show this help

Defaults:
  Gateway A  http://127.0.0.1:$GATEWAY_A_PORT    Gateway B  http://127.0.0.1:$GATEWAY_B_PORT
  nginx      http://localhost:$NGINX_PORT  (round-robin /api over A and B; / goes to a frontend on :$FRONTEND_PORT)
  Postgres   127.0.0.1:$PG_PORT ($PG_CONTAINER)   Redis  127.0.0.1:$REDIS_PORT ($REDIS_CONTAINER)
  State      $STATE_DIR

Environment overrides:
  DEERFLOW_MI_BASE_CONFIG     base config (default: \$DEER_FLOW_CONFIG_PATH, config.yaml,
                              backend/config.yaml, then config.example.yaml)
  DEERFLOW_MI_STATE_DIR       state directory
  DEERFLOW_MI_GATEWAY_A_PORT, DEERFLOW_MI_GATEWAY_B_PORT, DEERFLOW_MI_NGINX_PORT,
  DEERFLOW_MI_FRONTEND_PORT, DEERFLOW_MI_POSTGRES_PORT, DEERFLOW_MI_REDIS_PORT
  DEERFLOW_MI_POSTGRES_CONTAINER, DEERFLOW_MI_REDIS_CONTAINER,
  DEERFLOW_MI_POSTGRES_IMAGE, DEERFLOW_MI_REDIS_IMAGE
  DEERFLOW_MI_KEEP_CHANNELS=1 keep IM channels enabled (both Gateways then connect every bot)
  DEERFLOW_MI_HEALTH_TIMEOUT  seconds to wait for each Gateway's /health (default 180)

'make stop' and 'make dev' reclaim port 8001 and this checkout's Gateways, so
do not run them while the harness is up.
EOF
}

die() {
    echo "✗ $*" >&2
    exit 1
}

upper() {
    printf '%s' "$1" | tr '[:lower:]' '[:upper:]'
}

port_in_use() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

pid_file() {
    printf '%s/%s.pid' "$RUN_DIR" "$1"
}

# Print the pid recorded for $1 when that process is still the one we started
# ($2 is a fragment of its command line), so a reused pid is never signalled.
live_pid() {
    local pid command
    pid="$(cat "$(pid_file "$1")" 2>/dev/null || true)"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    case "$command" in
        *"$2"*) printf '%s' "$pid" ;;
        *) return 1 ;;
    esac
}

gateway_pid() {
    live_pid "gateway-$1" "app.gateway.app:app"
}

nginx_pid() {
    live_pid nginx "nginx"
}

gateway_port() {
    case "$1" in
        a) printf '%s' "$GATEWAY_A_PORT" ;;
        b) printf '%s' "$GATEWAY_B_PORT" ;;
        *) die "Unknown Gateway '$1' (expected a or b)" ;;
    esac
}

# Resolve the backend interpreter once (in this shell, not a subshell) and run
# it directly: `uv run` would sit between us and uvicorn, so the recorded pid
# would not be the process that serves (SIGKILL would orphan the server).
ensure_python() {
    if [ -z "${PYTHON_BIN:-}" ]; then
        PYTHON_BIN="$(uv run --no-sync --project "$BACKEND_DIR" python -c 'import sys; print(sys.executable)')" ||
            die "Cannot run the backend environment. Run 'make install' (or 'cd backend && uv sync') first."
    fi
}

run_helper() {
    ensure_python
    "$PYTHON_BIN" "$HELPER" "$@"
}

load_secrets() {
    [ -f "$SECRETS_FILE" ] || die "Missing $SECRETS_FILE; run 'up' first."
    set -a
    # shellcheck disable=SC1090
    . "$SECRETS_FILE"
    set +a
}

# ── State directory ──────────────────────────────────────────────────────────

ensure_state_dir() {
    if [ -d "$STATE_DIR" ] && [ ! -f "$STATE_DIR/$STATE_MARKER" ] && [ -n "$(ls -A "$STATE_DIR" 2>/dev/null)" ]; then
        die "$STATE_DIR is not empty and was not created by this harness; set DEERFLOW_MI_STATE_DIR to another directory."
    fi
    mkdir -p "$STATE_DIR" "$RUN_DIR" "$LOG_DIR"
    touch "$STATE_DIR/$STATE_MARKER"
}

# Delete everything the harness created except logs. Guarded by the marker so
# a mistyped DEERFLOW_MI_STATE_DIR can never point this at someone's data.
wipe_runtime_data() {
    [ -f "$STATE_DIR/$STATE_MARKER" ] || return 0
    find "$STATE_DIR" -mindepth 1 -maxdepth 1 ! -name logs ! -name "$STATE_MARKER" -exec rm -rf {} +
}

# ── Containers ───────────────────────────────────────────────────────────────

require_docker() {
    command -v docker >/dev/null 2>&1 || die "docker is not installed."
    docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop (or the daemon) and retry."
}

container_exists() {
    docker inspect "$1" >/dev/null 2>&1
}

container_label() {
    docker inspect -f "{{ index .Config.Labels \"$2\" }}" "$1" 2>/dev/null || true
}

# Remove container $1, with its anonymous volumes (both images declare a
# VOLUME), when this state dir created it. A container from another harness
# state dir, or from outside the harness, is never touched: returns 1.
remove_container() {
    local owner
    container_exists "$1" || return 0
    if [ "$(container_label "$1" "$LABEL_KEY")" != "$LABEL_VALUE" ]; then
        echo "  ! container $1 was not created by this harness; leaving it alone" >&2
        return 1
    fi
    owner="$(container_label "$1" "$STATE_LABEL_KEY")"
    if [ "$owner" != "$STATE_DIR" ]; then
        echo "  ! container $1 belongs to the harness state dir ${owner:-<unrecorded>}; leaving it alone" >&2
        echo "    (take that harness down from there, or 'docker rm -f -v $1' if it is stale)" >&2
        return 1
    fi
    docker rm -f -v "$1" >/dev/null
    echo "✓ Removed container $1 and its volumes"
}

wait_until() {
    local timeout=$1 waited=0
    shift
    until "$@" >/dev/null 2>&1; do
        [ "$waited" -lt "$timeout" ] || return 1
        sleep 1
        waited=$((waited + 1))
    done
}

redis_pong() {
    [ "$(docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null)" = "PONG" ]
}

start_containers() {
    echo "Starting Postgres ($PG_IMAGE) on 127.0.0.1:$PG_PORT..."
    POSTGRES_PASSWORD="$DEERFLOW_MI_POSTGRES_PASSWORD" docker run -d --name "$PG_CONTAINER" \
        --label "$LABEL_KEY=$LABEL_VALUE" --label "$STATE_LABEL_KEY=$STATE_DIR" \
        -e POSTGRES_USER=deerflow -e POSTGRES_DB=deerflow -e POSTGRES_PASSWORD \
        -p "127.0.0.1:$PG_PORT:5432" "$PG_IMAGE" >/dev/null || return 1
    echo "Starting Redis ($REDIS_IMAGE) on 127.0.0.1:$REDIS_PORT..."
    docker run -d --name "$REDIS_CONTAINER" --label "$LABEL_KEY=$LABEL_VALUE" --label "$STATE_LABEL_KEY=$STATE_DIR" \
        -p "127.0.0.1:$REDIS_PORT:6379" "$REDIS_IMAGE" >/dev/null || return 1

    # TCP readiness: the image's init-time server listens on the Unix socket only.
    if ! wait_until 90 docker exec "$PG_CONTAINER" pg_isready -h 127.0.0.1 -U deerflow -d deerflow; then
        docker logs --tail 30 "$PG_CONTAINER" >&2 || true
        echo "✗ Postgres did not become ready" >&2
        return 1
    fi
    echo "✓ Postgres ready"
    if ! wait_until 30 redis_pong; then
        docker logs --tail 30 "$REDIS_CONTAINER" >&2 || true
        echo "✗ Redis did not answer PING" >&2
        return 1
    fi
    echo "✓ Redis ready"
}

# ── Gateways and nginx ───────────────────────────────────────────────────────

start_gateway() {
    local name=$1 port log pid waited=0
    port="$(gateway_port "$name")"
    log="$LOG_DIR/gateway-$name.log"
    if pid="$(gateway_pid "$name")"; then
        echo "✗ Gateway $(upper "$name") is already running (pid $pid)." >&2
        return 1
    fi
    if port_in_use "$port"; then
        echo "✗ Port $port is in use; free it or set DEERFLOW_MI_GATEWAY_$(upper "$name")_PORT." >&2
        return 1
    fi
    if [ ! -f "$CONFIG_OUT" ]; then
        echo "✗ Missing $CONFIG_OUT; run 'up' first." >&2
        return 1
    fi
    load_secrets
    mkdir -p "$STATE_DIR/index/$name" "$STATE_DIR/home"
    ensure_python

    echo "Starting Gateway $(upper "$name") on 127.0.0.1:$port..."
    {
        echo ""
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') starting Gateway $(upper "$name") on 127.0.0.1:$port ====="
    } >>"$log"
    (
        cd "$BACKEND_DIR"
        # One worker per Gateway: the pid file must name the process that serves.
        export DEER_FLOW_CONFIG_PATH="$CONFIG_OUT" \
            DEER_FLOW_EXTENSIONS_CONFIG_PATH="$EXTENSIONS_OUT" \
            DEER_FLOW_HOME="$STATE_DIR/home" \
            DEER_FLOW_PROJECT_ROOT="$REPO_ROOT" \
            DEERFLOW_MI_RETRIEVAL_INDEX_PATH="$STATE_DIR/index/$name" \
            DEERFLOW_MI_DATABASE_URL="postgresql://deerflow:$DEERFLOW_MI_POSTGRES_PASSWORD@127.0.0.1:$PG_PORT/deerflow" \
            DEERFLOW_MI_REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0" \
            DEER_FLOW_CHANNELS_LANGGRAPH_URL="http://127.0.0.1:$port/api" \
            DEER_FLOW_CHANNELS_GATEWAY_URL="http://127.0.0.1:$port" \
            GATEWAY_WORKERS=1 WEB_CONCURRENCY=1 PYTHONPATH=. \
            AUTH_JWT_SECRET DEER_FLOW_INTERNAL_AUTH_TOKEN DEER_FLOW_CREDENTIALS_KEY
        exec nohup "$PYTHON_BIN" -m uvicorn app.gateway.app:app --host 127.0.0.1 --port "$port" </dev/null
    ) >>"$log" 2>&1 &
    pid=$!
    # The Gateway outlives this script: drop it from the job table so stopping
    # it later (teardown, stop/restart) prints no "Terminated" job notice.
    disown "$pid" 2>/dev/null || true
    echo "$pid" >"$(pid_file "gateway-$name")"

    while ! curl -fsS --noproxy '*' -o /dev/null --max-time 2 "http://127.0.0.1:$port/health" 2>/dev/null; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "✗ Gateway $(upper "$name") exited during startup. Last lines of $log:" >&2
            tail -n 40 "$log" >&2
            return 1
        fi
        if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
            echo "✗ Gateway $(upper "$name") did not answer /health within ${HEALTH_TIMEOUT}s. Last lines of $log:" >&2
            tail -n 40 "$log" >&2
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    echo "✓ Gateway $(upper "$name") ready on http://127.0.0.1:$port (pid $pid, ${waited}s)"
}

# stop_process NAME CMD_FRAGMENT SIGNAL
stop_process() {
    local name=$1 fragment=$2 signal=${3:-TERM} pid waited=0
    if pid="$(live_pid "$name" "$fragment")"; then
        kill "-$signal" "$pid" 2>/dev/null || true
        while kill -0 "$pid" 2>/dev/null; do
            if [ "$waited" -ge 30 ]; then
                echo "  ! $name (pid $pid) ignored SIG$signal for 30s; sending SIGKILL" >&2
                kill -KILL "$pid" 2>/dev/null || true
                break
            fi
            sleep 1
            waited=$((waited + 1))
        done
        echo "✓ Stopped $name (pid $pid, SIG$signal)"
    fi
    rm -f "$(pid_file "$name")"
}

start_nginx() {
    local conf="$STATE_DIR/nginx/nginx.conf" waited=0
    if ! command -v nginx >/dev/null 2>&1; then
        echo "  nginx not found; skipping the round-robin front (Gateways are still reachable directly)"
        return 0
    fi
    if port_in_use "$NGINX_PORT"; then
        echo "  ! port $NGINX_PORT is in use; skipping nginx (set DEERFLOW_MI_NGINX_PORT)" >&2
        return 0
    fi
    mkdir -p "$STATE_DIR/nginx/temp"
    run_helper nginx-conf --out "$conf" --state-dir "$STATE_DIR" --listen-port "$NGINX_PORT" \
        --gateway-port "$GATEWAY_A_PORT" --gateway-port "$GATEWAY_B_PORT" --frontend-port "$FRONTEND_PORT" || return 1
    echo "Starting nginx on 127.0.0.1:$NGINX_PORT..."
    if ! nginx -e "$LOG_DIR/nginx-error.log" -p "$STATE_DIR/nginx" -c "$conf" >>"$LOG_DIR/nginx.log" 2>&1; then
        tail -n 20 "$LOG_DIR/nginx.log" "$LOG_DIR/nginx-error.log" >&2 2>/dev/null || true
        echo "✗ nginx failed to start" >&2
        return 1
    fi
    until nginx_pid >/dev/null; do
        [ "$waited" -lt 10 ] || { echo "✗ nginx wrote no pid file" >&2; return 1; }
        sleep 1
        waited=$((waited + 1))
    done
    echo "✓ nginx ready on http://localhost:$NGINX_PORT (pid $(nginx_pid))"
}

# Stop processes and remove containers; keep config and logs for inspection.
teardown() {
    stop_process nginx "nginx" QUIT
    stop_process gateway-b "app.gateway.app:app" TERM
    stop_process gateway-a "app.gateway.app:app" TERM
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        remove_container "$PG_CONTAINER" || true
        remove_container "$REDIS_CONTAINER" || true
    else
        echo "  ! Docker is not reachable; containers $PG_CONTAINER / $REDIS_CONTAINER were not removed" >&2
    fi
}

fail_up() {
    echo "✗ $*" >&2
    exit 1
}

# EXIT trap while `up` starts things: any exit before the banner (fail_up, die,
# set -e, Ctrl+C) stops what was started instead of leaving it running.
UP_IN_PROGRESS=false
on_up_exit() {
    local status=$?
    trap - EXIT INT TERM
    if $UP_IN_PROGRESS; then
        echo "  Tearing down the partial start; logs stay in $LOG_DIR" >&2
        teardown
        [ "$status" -ne 0 ] || status=1
    fi
    exit "$status"
}

# ── Inputs ───────────────────────────────────────────────────────────────────

absolute_path() {
    printf '%s/%s' "$(builtin cd "$(dirname "$1")" >/dev/null 2>&1 && pwd -P)" "$(basename "$1")"
}

resolve_base_config() {
    local candidate
    if [ -n "${DEERFLOW_MI_BASE_CONFIG:-}" ]; then
        [ -f "$DEERFLOW_MI_BASE_CONFIG" ] || die "DEERFLOW_MI_BASE_CONFIG=$DEERFLOW_MI_BASE_CONFIG does not exist."
        BASE_CONFIG="$(absolute_path "$DEERFLOW_MI_BASE_CONFIG")"
        return 0
    fi
    for candidate in "${DEER_FLOW_CONFIG_PATH:-}" "$REPO_ROOT/config.yaml" "$REPO_ROOT/backend/config.yaml" "$REPO_ROOT/config.example.yaml"; do
        [ -n "$candidate" ] && [ -f "$candidate" ] || continue
        candidate="$(absolute_path "$candidate")"
        [ "$candidate" != "$CONFIG_OUT" ] || continue
        BASE_CONFIG="$candidate"
        return 0
    done
    die "No base config found (config.yaml or config.example.yaml)."
}

copy_extensions_config() {
    local candidate
    for candidate in "${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-}" "$REPO_ROOT/extensions_config.json" "$REPO_ROOT/backend/extensions_config.json"; do
        [ -n "$candidate" ] && [ -f "$candidate" ] && [ "$candidate" != "$EXTENSIONS_OUT" ] || continue
        cp "$candidate" "$EXTENSIONS_OUT"
        chmod 600 "$EXTENSIONS_OUT"
        echo "  extensions: copied $candidate (Gateway MCP/skill edits go to the copy)"
        return 0
    done
    printf '{\n  "mcpServers": {},\n  "skills": {}\n}\n' >"$EXTENSIONS_OUT"
    echo "  extensions: none found; using an empty extensions_config.json"
}

# Extras the base config needs (models, channels, ...) plus the two this
# topology always needs. The detector only emits validated extra names.
uv_extra_flags() {
    local detected="" token previous="" flags="--extra postgres --extra redis"
    if command -v python3 >/dev/null 2>&1; then
        detected="$(DEER_FLOW_CONFIG_PATH="$BASE_CONFIG" python3 "$REPO_ROOT/scripts/detect_uv_extras.py" 2>/dev/null || true)"
    fi
    for token in $detected; do
        if [ "$previous" = "--extra" ] && [ "$token" != postgres ] && [ "$token" != redis ]; then
            flags="$flags --extra $token"
        fi
        previous="$token"
    done
    printf '%s' "$flags"
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_up() {
    local skip_install=false with_nginx=true arg port extras
    for arg in "$@"; do
        case "$arg" in
            --skip-install) skip_install=true ;;
            --no-nginx) with_nginx=false ;;
            *) die "Unknown option for up: $arg" ;;
        esac
    done

    require_docker
    command -v uv >/dev/null 2>&1 || die "uv is not installed."
    command -v curl >/dev/null 2>&1 || die "curl is not installed."
    command -v lsof >/dev/null 2>&1 || die "lsof is not installed."
    if gateway_pid a >/dev/null || gateway_pid b >/dev/null || nginx_pid >/dev/null; then
        die "The harness is already running; run 'down' first (or 'status')."
    fi

    ensure_state_dir
    resolve_base_config

    # A previous session of this state dir that was not taken down: clear it
    # before the port checks. Containers of any other owner are refused.
    remove_container "$PG_CONTAINER" || die "Container name $PG_CONTAINER is taken; set DEERFLOW_MI_POSTGRES_CONTAINER (and the ports) to run a second harness."
    remove_container "$REDIS_CONTAINER" || die "Container name $REDIS_CONTAINER is taken; set DEERFLOW_MI_REDIS_CONTAINER (and the ports) to run a second harness."
    for port in "$GATEWAY_A_PORT" "$GATEWAY_B_PORT" "$PG_PORT" "$REDIS_PORT"; do
        if port_in_use "$port"; then
            die "Port $port is in use. Stop whatever holds it ('make stop' for make dev) or override the port (see --help)."
        fi
    done

    wipe_runtime_data
    mkdir -p "$RUN_DIR" "$LOG_DIR" "$STATE_DIR/home" "$STATE_DIR/index"
    : >"$LOG_DIR/gateway-a.log"
    : >"$LOG_DIR/gateway-b.log"
    rm -f "$LOG_DIR"/nginx*.log

    echo "Base config: $BASE_CONFIG"
    if ! $skip_install; then
        extras="$(uv_extra_flags)"
        echo "Syncing backend dependencies ($extras)..."
        # Intentionally unquoted: splats validated `--extra NAME` pairs.
        # shellcheck disable=SC2086
        (cd "$BACKEND_DIR" && uv sync --locked --quiet --all-packages $extras) || die "Backend dependency sync failed."
    fi

    run_helper secrets --out "$SECRETS_FILE" || die "Could not create $SECRETS_FILE."
    load_secrets
    echo "Rendering $CONFIG_OUT..."
    local keep_channels=""
    if [ "${DEERFLOW_MI_KEEP_CHANNELS:-}" = "1" ]; then
        keep_channels="--keep-channels"
    fi
    # The URLs stay $VAR references so the file holds no harness secret; each
    # Gateway process exports them (see start_gateway).
    # shellcheck disable=SC2016
    run_helper render-config --base "$BASE_CONFIG" --out "$CONFIG_OUT" --state-dir "$STATE_DIR" \
        --database-url '$DEERFLOW_MI_DATABASE_URL' --redis-url '$DEERFLOW_MI_REDIS_URL' $keep_channels ||
        die "Could not render the multi-instance config."
    copy_extensions_config

    UP_IN_PROGRESS=true
    trap on_up_exit EXIT
    trap 'echo ""; fail_up "Interrupted"' INT TERM
    start_containers || fail_up "Containers failed to start."
    # Sequential cold start: Alembic migrations are advisory-locked, but the
    # LangGraph checkpointer/store setup() is not, so B starts after A is up.
    start_gateway a || fail_up "Gateway A failed to start."
    start_gateway b || fail_up "Gateway B failed to start."
    if $with_nginx; then
        start_nginx || fail_up "nginx failed to start."
    fi
    UP_IN_PROGRESS=false
    trap - EXIT INT TERM

    echo ""
    echo "=========================================="
    echo "  ✓ Multi-instance harness is up"
    echo "=========================================="
    echo "  Gateway A   http://127.0.0.1:$GATEWAY_A_PORT  (log $LOG_DIR/gateway-a.log)"
    echo "  Gateway B   http://127.0.0.1:$GATEWAY_B_PORT  (log $LOG_DIR/gateway-b.log)"
    if nginx_pid >/dev/null; then
        echo "  nginx       http://localhost:$NGINX_PORT  (round-robin; start the frontend on :$FRONTEND_PORT for the UI)"
    fi
    echo "  Postgres    127.0.0.1:$PG_PORT  ($PG_CONTAINER, user/db deerflow, password in $SECRETS_FILE)"
    echo "  Redis       127.0.0.1:$REDIS_PORT  ($REDIS_CONTAINER)"
    echo "  Shared home $STATE_DIR/home"
    echo "  Config      $CONFIG_OUT"
    echo ""
    echo "  Next:  scripts/dev_multi_instance.sh check"
    echo "         scripts/dev_multi_instance.sh stop b --kill   (crash B), then: start b"
    echo "         scripts/dev_multi_instance.sh down"
}

cmd_down() {
    [ $# -eq 0 ] || die "down takes no options"
    teardown
    wipe_runtime_data
    echo "✓ Harness is down (logs kept in $LOG_DIR)"
}

cmd_status() {
    local name pid port code container
    echo "State dir: $STATE_DIR"
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        for container in "$PG_CONTAINER" "$REDIS_CONTAINER"; do
            if container_exists "$container"; then
                echo "  $container: $(docker inspect -f '{{.State.Status}}' "$container")"
            else
                echo "  $container: absent"
            fi
        done
    else
        echo "  containers: Docker is not reachable"
    fi
    for name in a b; do
        port="$(gateway_port "$name")"
        if pid="$(gateway_pid "$name")"; then
            code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$port/health/ready" || true)"
            echo "  Gateway $(upper "$name"): running (pid $pid) http://127.0.0.1:$port, /health/ready $code"
        else
            echo "  Gateway $(upper "$name"): stopped"
        fi
    done
    if pid="$(nginx_pid)"; then
        echo "  nginx: running (pid $pid) http://localhost:$NGINX_PORT"
    else
        echo "  nginx: stopped"
    fi
}

cmd_logs() {
    local follow=false arg files=""
    for arg in "$@"; do
        case "$arg" in
            a | b) files="$files gateway-$arg.log" ;;
            nginx) files="$files nginx-error.log nginx-access.log" ;;
            all) files="$files gateway-a.log gateway-b.log" ;;
            -f | --follow) follow=true ;;
            *) die "Unknown option for logs: $arg" ;;
        esac
    done
    [ -n "$files" ] || files="gateway-a.log gateway-b.log"
    [ -d "$LOG_DIR" ] || die "No logs yet in $LOG_DIR."
    cd "$LOG_DIR"
    if $follow; then
        # shellcheck disable=SC2086
        exec tail -n 100 -F $files
    fi
    for arg in $files; do
        if [ -f "$arg" ]; then
            echo "==> $LOG_DIR/$arg <=="
            tail -n 100 "$arg"
        fi
    done
}

cmd_check() {
    local arg nginx_url=""
    for arg in "$@"; do
        case "$arg" in
            --with-llm) ;;
            *) die "Unknown option for check: $arg" ;;
        esac
    done
    if ! gateway_pid a >/dev/null || ! gateway_pid b >/dev/null; then
        die "Both Gateways must be running; run 'up' (or 'start a|b')."
    fi
    if nginx_pid >/dev/null; then
        nginx_url="http://127.0.0.1:$NGINX_PORT"
    fi
    run_helper check --gateway "A=http://127.0.0.1:$GATEWAY_A_PORT" --gateway "B=http://127.0.0.1:$GATEWAY_B_PORT" \
        ${nginx_url:+--nginx "$nginx_url"} --state-dir "$STATE_DIR" "$@"
}

cmd_stop() {
    local name="${1:-}" signal=TERM
    [ -n "$name" ] || die "Usage: stop <a|b> [--kill]"
    gateway_port "$name" >/dev/null
    shift
    case "${1:-}" in
        "") ;;
        --kill) signal=KILL ;;
        *) die "Unknown option for stop: $1" ;;
    esac
    gateway_pid "$name" >/dev/null || die "Gateway $(upper "$name") is not running."
    stop_process "gateway-$name" "app.gateway.app:app" "$signal"
}

cmd_start() {
    local name="${1:-}"
    [ -n "$name" ] && [ $# -eq 1 ] || die "Usage: start <a|b>"
    gateway_port "$name" >/dev/null
    start_gateway "$name"
}

cmd_restart() {
    local name="${1:-}"
    [ -n "$name" ] && [ $# -eq 1 ] || die "Usage: restart <a|b>"
    gateway_port "$name" >/dev/null
    stop_process "gateway-$name" "app.gateway.app:app" TERM
    start_gateway "$name"
}

main() {
    local command="${1:-help}"
    [ $# -eq 0 ] || shift
    case "$command" in
        up) cmd_up "$@" ;;
        down) cmd_down "$@" ;;
        status) cmd_status ;;
        logs) cmd_logs "$@" ;;
        check) cmd_check "$@" ;;
        stop) cmd_stop "$@" ;;
        start) cmd_start "$@" ;;
        restart) cmd_restart "$@" ;;
        help | -h | --help) usage ;;
        *)
            echo "Unknown command: $command" >&2
            usage >&2
            exit 2
            ;;
    esac
}

main "$@"

#!/usr/bin/env bash
#
# wait-for-port.sh - Wait for a TCP port to become available
#
# Usage: ./scripts/wait-for-port.sh <port> [timeout_seconds] [service_name]
#
# Arguments:
#   port             - TCP port to wait for (required)
#   timeout_seconds  - Max seconds to wait (default: 60)
#   service_name     - Display name for messages (default: "Service")
#
# Exit codes:
#   0 - Port is listening
#   1 - Timed out waiting

PORT="${1:?Usage: wait-for-port.sh <port> [timeout] [service_name]}"
TIMEOUT="${2:-60}"
SERVICE="${3:-Service}"

case "$PORT" in
    ''|*[!0-9]*)
        echo "Port must be a numeric TCP port: $PORT" >&2
        exit 1
        ;;
esac

if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "Port must be between 1 and 65535: $PORT" >&2
    exit 1
fi

interval=1

_remaining() {
    local left=$((deadline - SECONDS))
    if [ "$left" -gt 0 ]; then
        printf '%s' "$left"
    else
        printf '0'
    fi
}

# Bash parameter expansion, not dirname(1). From make on Windows the launcher is
# cmd → Git Bash, and an external dirname in this script never returns, so the
# deadline below never starts.
_script="${BASH_SOURCE[0]}"
case "$_script" in
    */*) SCRIPT_DIR="${_script%/*}" ;;
    *) SCRIPT_DIR="." ;;
esac
# shellcheck source=scripts/port-listening.sh
source "$SCRIPT_DIR/port-listening.sh"

_fail_timed_out() {
    echo ""
    echo "✗ $SERVICE failed to start on port $PORT after ${TIMEOUT}s"
    exit 1
}

# Stop the coproc once. Exit, INT and TERM all use this, as does a read timeout.
# The worker's process group comes from `set -m`, so the signal reaches netstat
# and sleep. KILL follows TERM: a probe that ignores TERM must not leave `wait` stuck.
_probe_stopped=0
_stop_probe() {
    local pid=$1
    [ -n "$pid" ] || return 0
    [ "$_probe_stopped" = 0 ] || return 0
    _probe_stopped=1
    kill -TERM -- "-${pid}" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    kill -KILL -- "-${pid}" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
}

_cleanup_probe() {
    _stop_probe "${_probe_worker_PID:-}"
}

# One worker for every poll. Forking a shell per probe makes the simulated
# startup waits exceed their own timeout on Windows. `read -t` bounds each
# probe by the time left; an external timeout(1) can hang the same way dirname
# did under make → cmd → Git Bash.
set -m
coproc _probe_worker {
    while IFS= read -r _request; do
        if port_is_listening "$PORT"; then
            printf '0\n'
        else
            printf '1\n'
        fi
    done
}
set +m
trap _cleanup_probe EXIT
trap '_cleanup_probe; exit 130' INT
trap '_cleanup_probe; exit 143' TERM

# One deadline for this process, starting once the worker is ready. serve.sh
# starts a separate wait for each service, so the Gateway (30s, or
# DEER_FLOW_GATEWAY_STARTUP_TIMEOUT), the Frontend (300s) and Nginx (10s) do
# not share it. With no argument the budget is 60s. Probes and sleeps both use
# deadline minus SECONDS; neither restarts it.
started=$SECONDS
deadline=$((started + TIMEOUT))

_probe_within_deadline() {
    local remaining status
    remaining=$(_remaining)
    if [ "$remaining" -le 0 ]; then
        return 1
    fi
    printf '\n' >&"${_probe_worker[1]}"
    if ! read -r -t "$remaining" status <&"${_probe_worker[0]}"; then
        _stop_probe "${_probe_worker_PID}"
        _fail_timed_out
    fi
    if [ "$(_remaining)" -le 0 ]; then
        return 1
    fi
    [ "$status" = "0" ]
}

while ! _probe_within_deadline; do
    remaining=$(_remaining)
    if [ "$remaining" -le 0 ]; then
        _fail_timed_out
    fi
    printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$PORT" "$((SECONDS - started))"
    # The poll stays 1s, but the last sleep cannot run past this service's deadline.
    if [ "$interval" -lt "$remaining" ]; then
        sleep "$interval"
    else
        sleep "$remaining"
    fi
done

printf "\r  %-60s\r" ""   # clear the waiting line

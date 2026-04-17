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
OS_NAME="$(uname -s 2>/dev/null || echo unknown)"

elapsed=0
interval=1

http_probe_localhost() {
    if command -v curl >/dev/null 2>&1; then
        curl -sf --max-time 1 "http://127.0.0.1:$PORT/" >/dev/null 2>&1
        return $?
    fi
    return 1
}

tcp_probe_localhost() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 1 bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT" >/dev/null 2>&1
        return $?
    fi
    bash -c "exec 3<>/dev/tcp/127.0.0.1/$PORT" >/dev/null 2>&1
    return $?
}

is_port_listening() {
    if [ "$OS_NAME" = "Darwin" ]; then
        http_probe_localhost && return 0
        tcp_probe_localhost && return 0
    fi

    if command -v ss >/dev/null 2>&1; then
        if ss -ltn "( sport = :$PORT )" 2>/dev/null | tail -n +2 | grep -q .; then
            return 0
        fi
    fi

    if command -v netstat >/dev/null 2>&1; then
        if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[.:])${PORT}$"; then
            return 0
        fi
    fi

    if [ "$OS_NAME" != "Darwin" ] && command -v lsof >/dev/null 2>&1; then
        if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
            return 0
        fi
    fi

    tcp_probe_localhost
    return $?
}

if [ "${DEER_FLOW_WAIT_FOR_PORT_SINGLE_CHECK:-0}" = "1" ]; then
    is_port_listening
    exit $?
fi

while ! is_port_listening; do
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo ""
        echo "✗ $SERVICE failed to start on port $PORT after ${TIMEOUT}s"
        exit 1
    fi
    printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$PORT" "$elapsed"
    sleep "$interval"
    elapsed=$((elapsed + interval))
done

printf "\r  %-60s\r" ""   # clear the waiting line

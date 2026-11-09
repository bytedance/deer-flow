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

# --- Validate the port argument -------------------------------------------
case "$PORT" in
    ''|*[!0-9]*)
        echo "Port must be a numeric TCP port: $PORT" >&2
        exit 1
        ;;
esac

# Strip ALL leading zeros so the value used for the range check AND the
# actual port probe is the canonical integer (e.g. "0000001" -> "1").
# `${PORT%%[1-9]*}` keeps only the leading zeros; removing that prefix from
# $PORT yields the zero-stripped number. This avoids `${PORT##0}`, which only
# removes a single leading zero and wrongly rejects zero-padded valid ports.
port_num="${PORT#"${PORT%%[1-9]*}"}"
[ -z "$port_num" ] && port_num=0

# Values longer than 5 digits exceed the maximum TCP port (65535) and would
# overflow Bash's integer range in the comparison below; reject them up front.
if [ "${#port_num}" -gt 5 ]; then
    echo "Port must be between 1 and 65535: $PORT" >&2
    exit 1
fi

if [ "$port_num" -lt 1 ] || [ "$port_num" -gt 65535 ]; then
    echo "Port must be between 1 and 65535: $PORT" >&2
    exit 1
fi

# --- Validate the timeout argument ----------------------------------------
case "$TIMEOUT" in
    ''|*[!0-9]*)
        echo "Timeout must be a non-negative integer: $TIMEOUT" >&2
        exit 1
        ;;
esac

# Strip ALL leading zeros (same canonicalization as the port above).
timeout_num="${TIMEOUT#"${TIMEOUT%%[1-9]*}"}"
[ -z "$timeout_num" ] && timeout_num=0
if [ "${#timeout_num}" -gt 18 ]; then
    echo "Timeout out of range: $TIMEOUT" >&2
    exit 1
fi

elapsed=0
interval=1

is_port_listening() {
    if command -v powershell.exe >/dev/null 2>&1; then
        if WAIT_FOR_PORT_PORT="$port_num" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\$ErrorActionPreference='SilentlyContinue'; \$Port = [int]\$env:WAIT_FOR_PORT_PORT; if (Get-NetTCPConnection -LocalPort \$Port -State Listen) { exit 0 } else { exit 1 }" >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v lsof >/dev/null 2>&1; then
        if lsof -nP -iTCP:"$port_num" -sTCP:LISTEN -t >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v ss >/dev/null 2>&1; then
        if ss -ltn "( sport = :$port_num )" 2>/dev/null | tail -n +2 | grep -q .; then
            return 0
        fi
    fi

    if command -v netstat >/dev/null 2>&1; then
        if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[.:])${port_num}$"; then
            return 0
        fi
    fi

    return 1
}

while ! is_port_listening; do
    if [ "$elapsed" -ge "$timeout_num" ]; then
        echo ""
        echo "✗ $SERVICE failed to start on port $port_num after ${TIMEOUT}s"
        exit 1
    fi
    printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$port_num" "$elapsed"
    sleep "$interval"
    elapsed=$((elapsed + interval))
done

printf "\r  %-60s\r" ""   # clear the waiting line

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

# Resolve probe commands once. Repeated PATH probing is especially slow under
# Windows/Git Bash and can dominate short readiness checks.
HAVE_POWERSHELL=false
HAVE_LSOF=false
HAVE_SS=false
HAVE_NETSTAT=false
command -v powershell.exe >/dev/null 2>&1 && HAVE_POWERSHELL=true
command -v lsof >/dev/null 2>&1 && HAVE_LSOF=true
command -v ss >/dev/null 2>&1 && HAVE_SS=true
command -v netstat >/dev/null 2>&1 && HAVE_NETSTAT=true

elapsed=0
interval=1

is_port_listening() {
    if $HAVE_POWERSHELL; then
        if WAIT_FOR_PORT_PORT="$PORT" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\$ErrorActionPreference='SilentlyContinue'; \$Port = [int]\$env:WAIT_FOR_PORT_PORT; if (Get-NetTCPConnection -LocalPort \$Port -State Listen) { exit 0 } else { exit 1 }" >/dev/null 2>&1; then
            return 0
        fi
    fi

    if $HAVE_LSOF; then
        if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
            return 0
        fi
    fi

    if $HAVE_SS; then
        if ss -ltn "( sport = :$PORT )" 2>/dev/null | tail -n +2 | grep -q .; then
            return 0
        fi
    fi

    if $HAVE_NETSTAT; then
        if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[.:])${PORT}$"; then
            return 0
        fi
    fi

    return 1
}

while ! is_port_listening; do
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo ""
        echo "✗ $SERVICE failed to start on port $PORT after ${TIMEOUT}s"
        exit 1
    fi
    if [ -t 1 ]; then
        printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$PORT" "$elapsed"
    fi
    sleep "$interval"
    elapsed=$((elapsed + interval))
done

if [ -t 1 ]; then
    printf "\r  %-60s\r" ""   # clear the waiting line
fi

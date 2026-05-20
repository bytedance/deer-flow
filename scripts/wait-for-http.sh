#!/usr/bin/env bash
#
# wait-for-http.sh - Wait for an HTTP endpoint to become ready
#
# Usage: ./scripts/wait-for-http.sh <url> [timeout_seconds] [service_name]
#
# Arguments:
#   url              - HTTP/HTTPS URL to probe (required)
#   timeout_seconds  - Max seconds to wait (default: 60)
#   service_name     - Display name for messages (default: "Service")
#
# Exit codes:
#   0 - Endpoint responded successfully
#   1 - Timed out waiting
#   2 - No supported HTTP client found

set -euo pipefail

URL="${1:?Usage: wait-for-http.sh <url> [timeout] [service_name]}"
TIMEOUT="${2:-60}"
SERVICE="${3:-Service}"

elapsed=0
interval=1
HTTP_CLIENT=""

detect_http_client() {
    if command -v curl >/dev/null 2>&1; then
        HTTP_CLIENT="curl"
        return 0
    fi

    if command -v wget >/dev/null 2>&1; then
        HTTP_CLIENT="wget"
        return 0
    fi

    if command -v python3 >/dev/null 2>&1; then
        HTTP_CLIENT="python3"
        return 0
    fi

    if command -v python >/dev/null 2>&1; then
        HTTP_CLIENT="python"
        return 0
    fi

    echo "✗ No HTTP client available. Install curl, wget, or python3." >&2
    return 1
}

probe_with_python() {
    "$HTTP_CLIENT" - "$URL" >/dev/null 2>&1 <<'PY'
import sys
try:
    import urllib.request as urllib_request
except ImportError:
    import urllib2 as urllib_request

resp = None
try:
    resp = urllib_request.urlopen(sys.argv[1], timeout=2)
finally:
    if resp is not None:
        resp.close()
PY
}

probe_http() {
    case "$HTTP_CLIENT" in
        curl)
            if curl --silent --fail --connect-timeout 2 --max-time 2 --output /dev/null "$URL" >/dev/null 2>&1; then
                return 0
            fi
            ;;
        wget)
            if wget --quiet --timeout=2 --tries=1 --spider "$URL" >/dev/null 2>&1; then
                return 0
            fi
            ;;
        python3|python)
            if probe_with_python; then
                return 0
            fi
            ;;
    esac

    return 1
}

if ! detect_http_client; then
    exit 2
fi

while ! probe_http; do
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo ""
        echo "✗ $SERVICE failed readiness check at $URL after ${TIMEOUT}s"
        exit 1
    fi
    printf "\r  Waiting for %s readiness at %s... %ds" "$SERVICE" "$URL" "$elapsed"
    sleep "$interval"
    elapsed=$((elapsed + interval))
done

printf "\r  %-60s\r" ""

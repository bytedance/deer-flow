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

# Bash older than 4 runs each probe as a background subshell in its own process
# group. The parent supervises that group against one deadline. A finished probe
# is reaped with wait. A probe that is still running is signaled as a group, so
# netstat or sleep forked by the subshell dies with it, and only then does wait
# run.
_compat_probe_pid=

_compat_reap() {
    local pid=$1
    [ -n "$pid" ] || return 0
    [ "$pid" != "$$" ] || return 0
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM -- "-${pid}" 2>/dev/null || true
        kill -TERM "$pid" 2>/dev/null || true
        kill -KILL -- "-${pid}" 2>/dev/null || true
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}

_compat_cleanup() {
    local pid=${_compat_probe_pid:-}
    _compat_probe_pid=
    _compat_reap "$pid"
    rm -f "${_compat_status:-}" "${_compat_status:-}.partial"
}

_wait_for_port_compat() {
    local left status slept
    # Same budget start as the bash 4 path: after port-listening.sh is sourced,
    # before the first probe. Sourcing that file is a local read. Probes and
    # sleeps share this deadline and do not restart it.
    started=$SECONDS
    deadline=$((started + TIMEOUT))
    _compat_status="${TMPDIR:-/tmp}/deerflow-wait-port-$$.status"
    trap _compat_cleanup EXIT
    trap '_compat_cleanup; exit 130' INT
    trap '_compat_cleanup; exit 143' TERM

    while true; do
        left=$(_remaining)
        if [ "$left" -le 0 ]; then
            _fail_timed_out
        fi
        rm -f "$_compat_status" "${_compat_status}.partial"
        slept=0
        # set -m gives this subshell its own process group before it forks.
        set -m
        (
            # Stay in the group created above. A nested background command must
            # not become its own group, or the timeout cannot signal netstat/sleep.
            set +m
            if port_is_listening "$PORT"; then
                printf '0\n' > "${_compat_status}.partial"
            else
                printf '1\n' > "${_compat_status}.partial"
            fi
            mv "${_compat_status}.partial" "$_compat_status"
        ) &
        _compat_probe_pid=$!
        set +m

        while [ ! -s "$_compat_status" ]; do
            left=$(_remaining)
            if [ "$left" -le 0 ]; then
                _compat_reap "$_compat_probe_pid"
                _compat_probe_pid=
                _fail_timed_out
            fi
            if [ "$interval" -lt "$left" ]; then
                sleep "$interval"
            else
                sleep "$left"
            fi
            slept=1
        done
        _compat_reap "$_compat_probe_pid"
        _compat_probe_pid=
        status=$(cat "$_compat_status" 2>/dev/null || printf '%s' '')
        rm -f "$_compat_status"
        # A listener that arrives after the deadline is still a timeout.
        left=$(_remaining)
        if [ "$left" -le 0 ]; then
            _fail_timed_out
        fi
        if [ "$status" = 0 ]; then
            break
        fi
        # A fast miss is noticed before this loop sleeps, so the 1s poll still
        # has to happen. A slow miss already consumed that time while we waited.
        if [ "$slept" = 0 ]; then
            printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$PORT" "$((SECONDS - started))"
            left=$(_remaining)
            if [ "$left" -le 0 ]; then
                _fail_timed_out
            fi
            if [ "$interval" -lt "$left" ]; then
                sleep "$interval"
            else
                sleep "$left"
            fi
        fi
    done

    printf "\r  %-60s\r" ""   # clear the waiting line
}

_note_wait_branch() {
    [ -n "${DEER_FLOW_WAIT_PORT_BRANCH_LOG:-}" ] || return 0
    printf '%s %s\n' "$1" "$BASH_VERSION" >> "$DEER_FLOW_WAIT_PORT_BRANCH_LOG"
}

# Major version >= 4 keeps the coproc wait. The coproc file is loaded only
# then, so bash 3.2 parses and runs this script without seeing that statement.
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    _note_wait_branch compat
    _wait_for_port_compat
else
    # shellcheck source=scripts/wait-for-port-bash4.sh
    source "$SCRIPT_DIR/wait-for-port-bash4.sh"
    _note_wait_branch bash4
    _wait_for_port_bash4
fi

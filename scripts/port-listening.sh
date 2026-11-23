#!/usr/bin/env bash
#
# port-listening.sh — return 0 when a TCP socket is listening on a port.
#
# Sourced by serve.sh and wait-for-port.sh. Running it directly also works:
#   scripts/port-listening.sh PORT
#
# Git Bash has no lsof or ss. Get-NetTCPConnection does not return when
# powershell.exe stdout is redirected, which freezes the wait loop before its
# timeout can start. Windows netstat -ano reports the listener directly: the
# local address is column 2 and the state is column 4.
#
# Detect Windows from $OSTYPE and parse netstat in the shell. uname(1) and
# awk(1) are MSYS programs, and the same make → cmd → Git Bash session that
# deadlocks on dirname also fails to return from those helpers.

_is_windows_shell() {
    case "${OSTYPE:-}" in
        msys*|mingw*|cygwin*)
            return 0
            ;;
    esac
    return 1
}

# Windows columns: Proto Local Foreign State PID. Match the local port only,
# so an established connection to :8001 or a listener on :18001 does not count.
_windows_netstat_listening() {
    local port="$1" line state addr listing
    # Capture netstat in one substitution. A process substitution here never
    # returns under the Git Bash that `make` starts from cmd.exe.
    listing="$(netstat -ano 2>/dev/null || true)"
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        [ -n "$line" ] || continue
        # shellcheck disable=SC2086
        set -- $line
        [ "$1" = "TCP" ] || [ "$1" = "TCP6" ] || continue
        state=$4
        case "$state" in
            [Ll][Ii][Ss][Tt][Ee][Nn]|[Ll][Ii][Ss][Tt][Ee][Nn][Ii][Nn][Gg]) ;;
            *) continue ;;
        esac
        addr=$2
        if [ "${addr##*:}" = "$port" ]; then
            return 0
        fi
    done <<EOF
$listing
EOF
    return 1
}

port_is_listening() {
    local port=$1

    case "$port" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        return 1
    fi

    # lsof and ss answer on their own. Falling through to netstat on every
    # miss makes the startup wait pay for a full netstat scan per second, and
    # on Git Bash that scan is slow enough to blow the launcher's real timeout.
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
        return $?
    fi

    if command -v ss >/dev/null 2>&1; then
        if ss -ltn "( sport = :$port )" 2>/dev/null | tail -n +2 | grep -q .; then
            return 0
        fi
        return 1
    fi

    if command -v netstat >/dev/null 2>&1; then
        if _is_windows_shell; then
            if _windows_netstat_listening "$port"; then
                return 0
            fi
            return 1
        fi
        if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[.:])${port}$"; then
            return 0
        fi
    fi

    return 1
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    port_is_listening "${1:?usage: port-listening.sh PORT}"
    exit $?
fi

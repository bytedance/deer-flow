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

# Bash older than 4 has no coproc and no timed wait. Each probe is a background
# subshell. The parent waits on that pid. A second process, started after
# set +m, sleeps the whole seconds still left and is the deadline. The 1s poll
# runs only after a probe has already reported that the port is down.
_compat_probe_pid=
_compat_sleeper_pid=
_compat_sleep_pid=
_compat_hold_sleep=

# Optional test log, same idea as DEER_FLOW_WAIT_PORT_BRANCH_LOG. Unset in normal runs.
_compat_note_pid() {
    [ -n "${DEER_FLOW_WAIT_PORT_PID_LOG:-}" ] || return 0
    printf '%s %s\n' "$1" "$2" >> "$DEER_FLOW_WAIT_PORT_PID_LOG"
}

# GNU and BSD ps accept -o. Git Bash does not, and its ps -l columns are
# PID, PPID, PGID. An unreadable group id is empty, and the caller then
# signals only the pid.
_compat_pgid() {
    local pid=$1 raw data
    [ -n "$pid" ] || return 0
    raw=$(ps -o pgid= -p "$pid" 2>/dev/null) || raw=
    set -f
    # shellcheck disable=SC2086
    set -- $raw
    set +f
    case "${1:-}" in
        ''|*[!0-9]*) ;;
        *) printf '%s' "$1"; return 0 ;;
    esac
    raw=$(ps -l -p "$pid" 2>/dev/null) || return 0
    case "$raw" in
        *PID*PPID*PGID*) ;;
        *) return 0 ;;
    esac
    data=${raw#*$'\n'}
    data=${data%%$'\n'*}
    set -f
    # shellcheck disable=SC2086
    set -- $data
    set +f
    if [ "${1:-}" = "$pid" ]; then
        printf '%s' "${3:-}"
    fi
}

# pid only. Used for the sleeper shell and for a probe that is not its own group.
_compat_signal_pid() {
    local pid=$1
    [ -n "$pid" ] || return 0
    [ "$pid" != "$$" ] || return 0
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

# Empty, or every non-blank line's first field is a pid. A header or a UID
# in that field is not acceptable.
_compat_lines_are_pids() {
    local raw=$1 line field
    [ -n "$raw" ] || return 0
    while IFS= read -r line; do
        set -f
        # shellcheck disable=SC2086
        set -- $line
        set +f
        field=${1:-}
        [ -n "$field" ] || continue
        case "$field" in
            *[!0-9]*) return 1 ;;
        esac
    done <<EOF
$raw
EOF
    return 0
}

# The first field of the first non-blank line.
_compat_first_field_is() {
    local raw=$1 want=$2 line field
    while IFS= read -r line; do
        set -f
        # shellcheck disable=SC2086
        set -- $line
        set +f
        field=${1:-}
        [ -n "$field" ] || continue
        [ "$field" = "$want" ]
        return $?
    done <<EOF
$raw
EOF
    return 1
}

# Git Bash ps -l starts with PID PPID PGID. Only that header line counts.
# A data line or an Apple header (UID PID PPID) does not.
_compat_header_is_gitbash() {
    local raw=$1 header
    header=${raw%%$'\n'*}
    set -f
    # shellcheck disable=SC2086
    set -- $header
    set +f
    [ "${1:-}" = PID ] && [ "${2:-}" = PPID ] && [ "${3:-}" = PGID ]
}

# Print pids whose ppid field equals $1. skip_header drops the first line.
_compat_emit_ppid_matches() {
    local pid=$1 raw=$2 skip_header=$3 line child ppid
    if [ "$skip_header" = 1 ]; then
        raw=${raw#*$'\n'}
    fi
    while IFS= read -r line; do
        set -f
        # shellcheck disable=SC2086
        set -- $line
        set +f
        child=${1:-}
        ppid=${2:-}
        case "$child" in
            ''|*[!0-9]*) continue ;;
        esac
        case "$ppid" in
            ''|*[!0-9]*) continue ;;
        esac
        if [ "$ppid" = "$pid" ]; then
            printf '%s\n' "$child"
        fi
    done <<EOF
$raw
EOF
}

# Direct children of one pid. GNU ps may select them with --ppid. macOS ps
# has no --ppid, and its ps -l starts with UID PID PPID, so those positions
# are never read. BSD ps is asked for pid and ppid of every process, including
# ones with no controlling terminal. Git Bash ps -l is read by position only
# when its own header line is PID PPID PGID.
_compat_child_pids() {
    local pid=$1 raw status line
    [ -n "$pid" ] || return 0
    # GNU --ppid. Exit 0 with only numeric pids (or no rows) is the answer.
    # A non-numeric row is not this format; do not parse it by position.
    raw=$(ps -o pid= --ppid "$pid" 2>/dev/null)
    status=$?
    if [ "$status" -eq 0 ] && _compat_lines_are_pids "$raw"; then
        while IFS= read -r line; do
            set -f
            # shellcheck disable=SC2086
            set -- $line
            set +f
            case "${1:-}" in
                ''|*[!0-9]*) continue ;;
            esac
            printf '%s\n' "$1"
        done <<EOF
$raw
EOF
        return 0
    fi
    # Named columns are real only when -o prints this shell's own pid.
    # Exit status alone is not enough: a ps that ignores -o can still return 0.
    raw=$(ps -o pid= -p "$$" 2>/dev/null)
    status=$?
    if [ "$status" -eq 0 ] && _compat_first_field_is "$raw" "$$"; then
        # -p would list the parent, not its children. -A/-ax includes
        # processes that have no controlling terminal.
        raw=$(ps -A -o pid=,ppid= 2>/dev/null)
        status=$?
        if [ "$status" -ne 0 ]; then
            raw=$(ps -ax -o pid=,ppid= 2>/dev/null)
            status=$?
        fi
        [ "$status" -eq 0 ] || return 0
        _compat_emit_ppid_matches "$pid" "$raw" 0
        return 0
    fi
    # Git Bash has no working -o. Read ps -l by position only for its header.
    raw=$(ps -l 2>/dev/null)
    status=$?
    [ "$status" -eq 0 ] || return 0
    _compat_header_is_gitbash "$raw" || return 0
    _compat_emit_ppid_matches "$pid" "$raw" 1
}

# True when this pid is already the sleep binary. Git Bash leaves a shell at
# $! and the binary is its child; a replacing exec is the binary itself.
_compat_pid_is_sleep() {
    local pid=$1 raw line cmd
    [ -n "$pid" ] || return 1
    if ps -o comm= -p "$pid" >/dev/null 2>&1; then
        cmd=$(ps -o comm= -p "$pid" 2>/dev/null) || return 1
        case "$cmd" in
            *sleep*) return 0 ;;
        esac
        return 1
    fi
    raw=$(ps -l 2>/dev/null) || return 1
    cmd=
    while IFS= read -r line; do
        set -f
        # shellcheck disable=SC2086
        set -- $line
        set +f
        if [ "${1:-}" = "$pid" ]; then
            cmd=${line##* }
            break
        fi
    done <<EOF
$raw
EOF
    case "$cmd" in
        *sleep*) return 0 ;;
    esac
    return 1
}

# `command sleep &` is not the sleep binary on Git Bash. Exec there spawns a
# child and waits, so $! is a shell and the real sleep is its child. Killing
# the shell before that child exists orphans the sleep and leaves it holding
# the caller's stdout. Wait until the child is visible, or until this pid is
# already the sleep binary, and only then signal it. One extra level covers a
# sleeper whose child is that shell. A replacing exec has no child. After 30
# looks with no child and a pid that is still not sleep, signal that pid anyway.
_compat_signal_sleep_pid() {
    local pid=$1 kids child grand tries=0
    [ -n "$pid" ] || return 0
    [ "$pid" != "$$" ] || return 0
    while [ "$tries" -lt 30 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        kids=$(_compat_child_pids "$pid")
        if [ -n "$kids" ]; then
            for child in $kids; do
                [ "$child" = "$$" ] && continue
                [ "$child" = "$pid" ] && continue
                for grand in $(_compat_child_pids "$child"); do
                    [ "$grand" = "$$" ] && continue
                    [ "$grand" = "$pid" ] && continue
                    [ "$grand" = "$child" ] && continue
                    _compat_signal_pid "$grand"
                done
                _compat_signal_pid "$child"
            done
            _compat_signal_pid "$pid"
            return 0
        fi
        if _compat_pid_is_sleep "$pid"; then
            _compat_signal_pid "$pid"
            return 0
        fi
        tries=$((tries + 1))
    done
    _compat_signal_pid "$pid"
}

_compat_stop_probe() {
    local pid=$1 pgid parent_pgid
    [ -n "$pid" ] || return 0
    [ "$pid" != "$$" ] || return 0
    pgid=$(_compat_pgid "$pid")
    parent_pgid=$(_compat_pgid "$$")
    # Group id equals the probe pid only when this process leads its own group.
    # That group must not be the parent's: set -m did that on Git Bash 5.2, and
    # macOS Bash 3.2 has not been checked. Otherwise a group signal could hit
    # the shell that is running this script.
    if [ -n "$pgid" ] && [ "$pgid" = "$pid" ] && [ -n "$parent_pgid" ] && [ "$pgid" != "$parent_pgid" ]; then
        kill -TERM -- "-${pid}" 2>/dev/null || true
        kill -KILL -- "-${pid}" 2>/dev/null || true
    fi
    _compat_signal_pid "$pid"
    wait "$pid" 2>/dev/null || true
}

# The sleeper is started with monitor mode off, so its group may be the
# parent's. Never signal that group.
_compat_reap_sleeper() {
    local sleeper=$1 sleep_pid=$2
    if [ -n "$sleep_pid" ]; then
        # The pid was published. Kill that sleep first so the shell's wait
        # returns, then reap the shell.
        _compat_signal_sleep_pid "$sleep_pid"
        if [ -n "$sleeper" ]; then
            _compat_signal_pid "$sleeper"
            wait "$sleeper" 2>/dev/null || true
        fi
        return 0
    fi
    # The fifo has not been read yet, so only the shell pid is known. KILL is
    # not catchable: TERM-then-KILL here would skip the shell's own trap and
    # leave its sleep child holding the caller's stdout. TERM, let that trap
    # reap the child, and KILL only if the shell is still alive afterwards.
    [ -n "$sleeper" ] || return 0
    [ "$sleeper" != "$$" ] || return 0
    if kill -0 "$sleeper" 2>/dev/null; then
        kill -TERM "$sleeper" 2>/dev/null || true
    fi
    wait "$sleeper" 2>/dev/null || true
    if kill -0 "$sleeper" 2>/dev/null; then
        # The trap did not run. KILL cannot catch, so take the sleep child
        # of this shell before the shell itself.
        _compat_signal_sleep_pid "$sleeper"
        kill -KILL "$sleeper" 2>/dev/null || true
        wait "$sleeper" 2>/dev/null || true
    fi
}

_compat_cleanup() {
    local sleeper sleep_pid probe hold_sleep
    # A test may be sleeping in the fifo hold. Drop that child so it cannot
    # keep the caller's stdout open after this shell exits.
    hold_sleep=${_compat_hold_sleep:-}
    _compat_hold_sleep=
    _compat_signal_sleep_pid "$hold_sleep"
    # A sleeper that wakes during cleanup must not kill a pid the parent owns.
    if [ -n "${_compat_owned:-}" ]; then
        : > "$_compat_owned"
    fi
    sleeper=${_compat_sleeper_pid:-}
    sleep_pid=${_compat_sleep_pid:-}
    probe=${_compat_probe_pid:-}
    _compat_sleeper_pid=
    _compat_sleep_pid=
    _compat_probe_pid=
    _compat_reap_sleeper "$sleeper" "$sleep_pid"
    _compat_stop_probe "$probe"
    rm -f "${_compat_status:-}" "${_compat_status:-}.partial" "${_compat_sleep_fifo:-}" "${_compat_owned:-}" "${_compat_fired:-}"
}

# Sleep is our grandchild. Publish its pid with a printf that opens and closes
# the fifo itself. Redirecting the whole sleeper onto the fifo leaves that
# write block-buffered, and the parent then sits in read until the sleep ends.
# Bash 3.2 runs an inherited EXIT trap inside this subshell; clear it before
# installing a trap that reaps only this sleep child.
_compat_start_sleeper() {
    local left=$1 probe_pid
    probe_pid=${_compat_probe_pid:-}
    rm -f "$_compat_sleep_fifo"
    mkfifo "$_compat_sleep_fifo" 2>/dev/null || return 1
    (
        # Drop the parent's cleanup first. The trap installed next must not
        # call it, delete its status files, or signal the parent or the probe.
        trap - EXIT INT TERM
        _watch_sleep=
        _reap_watch_sleep() {
            local pid=${_watch_sleep:-}
            _watch_sleep=
            [ -n "$pid" ] || return 0
            [ "$pid" != "$$" ] || return 0
            [ "$pid" != "$probe_pid" ] || return 0
            _compat_signal_sleep_pid "$pid"
            wait "$pid" 2>/dev/null || true
        }
        trap _reap_watch_sleep EXIT
        trap '_reap_watch_sleep; exit 143' TERM
        trap '_reap_watch_sleep; exit 130' INT
        # builtin skips a test's command() or sleep() function. Production
        # command and sleep are the same binary. The poll interval still calls
        # sleep, so an exported stub advances only that clock.
        builtin command sleep "$left" &
        _watch_sleep=$!
        _compat_note_pid sleep "$_watch_sleep"
        printf '%s\n' "$_watch_sleep" > "$_compat_sleep_fifo"
        wait "$_watch_sleep"
        _watch_sleep=
        # Parent creates the owned file as soon as it has the probe result.
        # A sleeper that reaches here first is the deadline.
        if [ ! -f "$_compat_owned" ]; then
            : > "$_compat_fired"
            _compat_stop_probe "$probe_pid"
        fi
    ) &
    _compat_sleeper_pid=$!
    _compat_note_pid sleeper "$_compat_sleeper_pid"
    # Test-only. Unset in production. Holds the parent before it learns the
    # sleep pid, so a signal can arrive in that window. Semantics otherwise
    # stay the same: the read still publishes that pid before wait returns.
    if [ -n "${DEER_FLOW_WAIT_PORT_HOLD_FIFO:-}" ]; then
        : > "$DEER_FLOW_WAIT_PORT_HOLD_FIFO"
        while [ -e "$DEER_FLOW_WAIT_PORT_HOLD_FIFO" ]; do
            sleep 1 &
            _compat_hold_sleep=$!
            wait "$_compat_hold_sleep" 2>/dev/null || true
            _compat_hold_sleep=
        done
    fi
    IFS= read -r _compat_sleep_pid < "$_compat_sleep_fifo" || _compat_sleep_pid=
    case "$_compat_sleep_pid" in
        ''|*[!0-9]*)
            _compat_reap_sleeper "$_compat_sleeper_pid" ""
            _compat_sleeper_pid=
            _compat_sleep_pid=
            return 1
            ;;
    esac
    _compat_note_pid sleep "$_compat_sleep_pid"
    return 0
}

_wait_for_port_compat() {
    local left status late budget
    # Same budget start as the bash 4 path: after port-listening.sh is sourced,
    # before the first probe. Sourcing that file is a local read. Probes and
    # sleeps share this deadline and do not restart it.
    started=$SECONDS
    deadline=$((started + TIMEOUT))
    _compat_status="${TMPDIR:-/tmp}/deerflow-wait-port-$$.status"
    _compat_sleep_fifo="${_compat_status}.fifo"
    _compat_owned="${_compat_status}.owned"
    _compat_fired="${_compat_status}.fired"
    trap _compat_cleanup EXIT
    trap '_compat_cleanup; exit 130' INT
    trap '_compat_cleanup; exit 143' TERM

    while true; do
        left=$(_remaining)
        if [ "$left" -le 0 ]; then
            _fail_timed_out
        fi
        rm -f "$_compat_status" "${_compat_status}.partial" "$_compat_owned" "$_compat_fired" "$_compat_sleep_fifo"
        budget=$left
        # set -m gives this subshell its own process group before it forks.
        set -m
        (
            trap - EXIT INT TERM
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
        _compat_note_pid probe "$_compat_probe_pid"
        set +m
        # Whole seconds left after the fork. SECONDS is a wall-clock count, so
        # it can step once during this fork even though the fork itself did not
        # take a second. sleep(1) also has no fraction, so a sleeper can return
        # almost a second after that count. A probe that already finished is
        # late only when this sleeper has fired. Nothing busy-waits the gap.
        left=$(_remaining)
        if [ "$left" -le 0 ]; then
            left=$budget
        fi
        if ! _compat_start_sleeper "$left"; then
            _compat_stop_probe "$_compat_probe_pid"
            _compat_probe_pid=
            echo "wait-for-port: cannot arm the deadline sleeper" >&2
            exit 1
        fi
        wait "$_compat_probe_pid"
        # Snapshot the deadline before telling the sleeper that the parent owns
        # the result. SECONDS can already read 0 while this sleeper is still
        # inside its whole-second sleep.
        if [ -f "$_compat_fired" ]; then
            late=1
        else
            late=0
        fi
        : > "$_compat_owned"
        _compat_reap_sleeper "$_compat_sleeper_pid" "$_compat_sleep_pid"
        _compat_sleeper_pid=
        _compat_sleep_pid=
        _compat_probe_pid=
        if [ ! -s "$_compat_status" ] || [ "$late" = 1 ]; then
            _fail_timed_out
        fi
        status=$(cat "$_compat_status" 2>/dev/null || printf '%s' '')
        rm -f "$_compat_status"
        if [ "$status" = 0 ]; then
            break
        fi
        # The status is a miss. Sleep the poll only now, and only with time left.
        left=$(_remaining)
        if [ "$left" -le 0 ]; then
            _fail_timed_out
        fi
        printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$PORT" "$((SECONDS - started))"
        if [ "$interval" -lt "$left" ]; then
            sleep "$interval"
        else
            sleep "$left"
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

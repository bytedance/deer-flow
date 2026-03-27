#!/usr/bin/env bash
#
# stop-local-services.sh - Stop DeerFlow local development services
#
# This stops only the local dev services started by this repository. It avoids
# blindly killing unrelated listeners by first checking whether the processes
# bound to a port look like DeerFlow services.

set +e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

port_listener_pids() {
    local port="$1"

    if command -v lsof >/dev/null 2>&1; then
        lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
        return
    fi

    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "( sport = :$port )" 2>/dev/null             | grep -o 'pid=[0-9]\+'             | cut -d= -f2             | sort -u
    fi
}

wait_for_port_to_close() {
    local port="$1"
    local timeout="${2:-5}"
    local elapsed=0

    while [ "$elapsed" -lt "$timeout" ]; do
        if ! port_listener_pids "$port" | grep -q .; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    ! port_listener_pids "$port" | grep -q .
}

any_pid_matches() {
    local expected_regex="$1"
    shift

    local pid
    local cmd

    for pid in "$@"; do
        cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
        if [[ -n "$cmd" && "$cmd" =~ $expected_regex ]]; then
            return 0
        fi
    done

    return 1
}

stop_listeners_on_port() {
    local port="$1"
    local expected_regex="$2"
    local -a pids=()

    mapfile -t pids < <(port_listener_pids "$port")
    if [ "${#pids[@]}" -eq 0 ]; then
        return 0
    fi

    if ! any_pid_matches "$expected_regex" "${pids[@]}"; then
        return 0
    fi

    kill -TERM "${pids[@]}" 2>/dev/null || true
    if wait_for_port_to_close "$port" 5; then
        return 0
    fi

    mapfile -t pids < <(port_listener_pids "$port")
    if [ "${#pids[@]}" -eq 0 ]; then
        return 0
    fi

    if any_pid_matches "$expected_regex" "${pids[@]}"; then
        kill -KILL "${pids[@]}" 2>/dev/null || true
        wait_for_port_to_close "$port" 3 || true
    fi
}

stop_matching_processes() {
    local pattern="$1"

    if ! pgrep -f "$pattern" >/dev/null 2>&1; then
        return 0
    fi

    pkill -TERM -f "$pattern" 2>/dev/null || true
    sleep 1

    if pgrep -f "$pattern" >/dev/null 2>&1; then
        pkill -KILL -f "$pattern" 2>/dev/null || true
    fi
}

nginx -c "$REPO_ROOT/docker/nginx/nginx.local.conf" -p "$REPO_ROOT" -s quit 2>/dev/null || true

stop_listeners_on_port 2024 '(^|/)langgraph([[:space:]]|$)|langgraph_api'
stop_matching_processes '(^|/)langgraph$'
stop_matching_processes 'uv run langgraph'

stop_listeners_on_port 8001 '(^|/)uvicorn([[:space:]]|$)|app\.gateway\.app:app'
stop_matching_processes '(^|/)uvicorn$'
stop_matching_processes 'uv run uvicorn'

stop_listeners_on_port 3000 'next-server|(^|/)next([[:space:]]|$)'
stop_matching_processes 'next-server'
stop_matching_processes '(^|/)next$'
stop_matching_processes 'node_modules/.bin/next'

stop_listeners_on_port 2026 '^nginx:|(^|/)nginx([[:space:]]|$)'
stop_matching_processes '^nginx:'

"$REPO_ROOT/scripts/cleanup-containers.sh" deer-flow-sandbox 2>/dev/null || true

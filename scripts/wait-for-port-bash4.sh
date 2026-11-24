# Sourced by wait-for-port.sh when bash is 4.0 or newer. Bash 3.2 has no coproc,
# and this file is not loaded there: a coproc statement in the entry script is
# parsed as an external command followed by a brace group that reads stdin.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "wait-for-port-bash4.sh is sourced by wait-for-port.sh" >&2
    exit 1
fi

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
_wait_for_port_bash4() {
    set -m
    coproc _probe_worker {
        # This worker is already its own process group. Keep probe children in it.
        set +m
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
}

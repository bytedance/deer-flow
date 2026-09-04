#!/usr/bin/env bash
# Regression test for the liveness-aware wait in scripts/wait-for-port.sh.
#
# Locks in the behavior reviewed in #5180 so a future change fails here
# rather than regressing the launcher UX again:
#   - a child that exits before listening -> exit 2 immediately (well under
#     the timeout), instead of burning the whole timeout budget on a dead
#     launcher;
#   - a live child that takes several polls to open the port -> exit 0, and
#     the per-second "Waiting for ..." progress output is preserved while
#     the port is still closed;
#   - the timeout path keeps working with and without a child_pid (exit 1
#     plus the "failed to start on port" message), so the new optional
#     argument stays backward compatible for other callers.
#
# Usage:
#   scripts/check_wait_for_port_liveness.sh
#
# Requires bash and a Python interpreter (any of python3/python) to spawn
# real listeners on 127.0.0.1.
#
# Exit status is 0 when all assertions pass, 1 otherwise.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WAIT="$ROOT/scripts/wait-for-port.sh"

TMP="$(mktemp -d)"
# kill: on Windows, rm would block on files a still-running child keeps open
trap 'kill $dead_pid $slow_pid 2>/dev/null; rm -rf "$TMP"' EXIT

fail() {
    echo "::error::$1" >&2
    exit 1
}

# Pick the first Python that actually runs (a bare `command -v` hit is not
# enough: e.g. the Windows Store python3 stub exists but produces nothing).
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'print(1)' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [ -z "$PY" ]; then
    fail "python is required to run this check"
fi

# A port number that is (almost certainly) not listening right now.
# tr strips the CRLF that native Windows Python appends to pipe output.
closed_port() {
    "$PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()' | tr -d '\r\n '
}

progress_count() {
    printf '%s' "$1" | grep -o "Waiting for" | wc -l
}

# ── Case 1: child exits before listening -> exit 2, well under the timeout ──

closed="$(closed_port)"
sh -c 'sleep 0.3; exit 0' &
dead_pid=$!
sleep 0.6 # let the launcher exit and be reaped before we start watching

start=$SECONDS
bash "$WAIT" "$closed" 15 DeadService "$dead_pid" >/dev/null 2>&1
status=$?
duration=$((SECONDS - start))

[ "$status" -eq 2 ] || fail "case 1: expected exit 2 for a child that died before listening, got $status"
[ "$duration" -le 5 ] || fail "case 1: fail-fast took ${duration}s; it should not approach the 15s timeout"

# ── Case 2: live child, port opens after several polls -> exit 0 + progress ──

"$PY" -c '
import socket, time
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
print(port, flush=True)
time.sleep(6)  # stay alive but not yet listening: forces multiple polls
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port))
srv.listen()
time.sleep(15)
' >"$TMP/slow.port" 2>"$TMP/slow.err" &
slow_pid=$!

for _ in $(seq 1 50); do
    [ -s "$TMP/slow.port" ] && break
    sleep 0.1
done
[ -s "$TMP/slow.port" ] || fail "case 2: slow launcher did not report its port"
open_port="$(tr -d '\r\n ' <"$TMP/slow.port")"

out="$(bash "$WAIT" "$open_port" 20 SlowService "$slow_pid")"
status=$?

# One progress emission is guaranteed (the 6s delay spans at least one poll
# cycle); more depend on how long each probe takes, e.g. a powershell.exe
# cold start on Windows turns the 1s poll interval into several seconds.
[ "$status" -eq 0 ] || fail "case 2: expected exit 0 once the live child opened the port, got $status"
[ "$(progress_count "$out")" -ge 1 ] || fail "case 2: expected progress output while waiting, got: $out"

# ── Case 3: no child_pid, unreachable port -> exit 1 with the timeout message ──

closed="$(closed_port)"
out="$(bash "$WAIT" "$closed" 1 NoPidService 2>&1)"
status=$?

[ "$status" -eq 1 ] || fail "case 3: expected exit 1 on timeout without child_pid, got $status"
printf '%s' "$out" | grep -q "failed to start on port" || fail "case 3: missing timeout message, got: $out"

# ── Case 4: live child_pid but timeout elapses -> still exit 1 ──

closed="$(closed_port)"
out="$(bash "$WAIT" "$closed" 1 AliveService "$$" 2>&1)"
status=$?

[ "$status" -eq 1 ] || fail "case 4: expected exit 1 on timeout with a live child_pid, got $status"
printf '%s' "$out" | grep -q "failed to start on port" || fail "case 4: missing timeout message, got: $out"

echo "check_wait_for_port_liveness: all 4 cases passed"

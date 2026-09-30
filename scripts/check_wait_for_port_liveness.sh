#!/usr/bin/env bash
# Regression test for the liveness-aware wait in scripts/wait-for-port.sh.
#
# Locks in the behavior reviewed in #5180 so a future change fails here
# rather than regressing the launcher UX again:
#   - a child that exits before listening -> exit 2 immediately (well under
#     the timeout), instead of burning the whole timeout budget on a dead
#     launcher;
#   - a live child that opens its port only after the wait has been observed
#     emitting progress -> exit 0, with the "Waiting for ..." progress output
#     asserted deterministically: the listener is released by handshake once
#     a progress line shows up, so a slow first probe (cold powershell.exe +
#     Get-NetTCPConnection on windows-latest can take many seconds) can no
#     longer outlast the launcher delay, open the listener mid-probe, and
#     finish without ever printing a progress line;
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

# PIDs are assigned further down, and early-failure paths (missing Python, a
# failing case 1) exit before reaching them: initialize all three before
# installing the trap, and kill only assigned PIDs, so `set -u` cannot abort
# the trap and skip the temporary-directory cleanup.
dead_pid=""
slow_pid=""
wf_pid=""
TMP="$(mktemp -d)"
# kill: on Windows, rm would block on files a still-running child keeps open
trap 'kill ${dead_pid:+"$dead_pid"} ${slow_pid:+"$slow_pid"} ${wf_pid:+"$wf_pid"} 2>/dev/null; rm -rf "$TMP"' EXIT

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
bash "$ROOT/scripts/wait-for-port.sh" "$closed" 15 DeadService "$dead_pid" >/dev/null 2>&1
status=$?
duration=$((SECONDS - start))

[ "$status" -eq 2 ] || fail "case 1: expected exit 2 for a child that died before listening, got $status"
# The bound only has to catch a regression to the full 15s timeout (which line
# 79's exit-code check would also catch). wait-for-port.sh checks liveness
# before any port probe, so this path never pays a probe cycle — even a cold
# windows-latest runner (slow powershell.exe + CIM start) cannot push the
# duration near the timeout. The bound stays generous for runner scheduling
# noise only.
[ "$duration" -le 10 ] || fail "case 1: fail-fast took ${duration}s; it should not approach the 15s timeout"

# ── Case 2: live child, port opens after observed progress -> exit 0 + progress ──
#
# Handshake: the launcher prints its port, then waits for a go-file before it
# starts listening. The wait runs in the background with output redirected to
# a file, and the test releases the listener only after a "Waiting for" line
# is observed. The 6s fixed delay this replaces could lose the race against a
# cold first probe on windows-latest: if that probe outlasts the delay, the
# listener opens mid-probe and wait-for-port.sh exits successfully without
# ever printing a progress line.

"$PY" -c '
import os, socket, sys, time
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
print(port, flush=True)
go, deadline = sys.argv[1], time.time() + 120
while not os.path.exists(go):
    if time.time() > deadline:
        sys.exit(3)
    time.sleep(0.1)
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port))
srv.listen()
time.sleep(30)
' "$TMP/go" >"$TMP/slow.port" 2>"$TMP/slow.err" &
slow_pid=$!

for _ in $(seq 1 50); do
    [ -s "$TMP/slow.port" ] && break
    sleep 0.1
done
[ -s "$TMP/slow.port" ] || fail "case 2: slow launcher did not report its port"
open_port="$(tr -d '\r\n ' <"$TMP/slow.port")"

wf_out="$TMP/wf.out"
bash "$ROOT/scripts/wait-for-port.sh" "$open_port" 60 SlowService "$slow_pid" >"$wf_out" 2>&1 &
wf_pid=$!

# Budget ordering: the 90s observation window below (450 x 0.2s) stays under
# the launcher's 120s go-file deadline, so a failed observation is never the
# launcher timing out; wait-for-port's 60s timeout is the inner net for a
# stall after the go-file.

observed=""
for _ in $(seq 1 450); do
    kill -0 "$wf_pid" 2>/dev/null || break
    if grep -q "Waiting for" "$wf_out" 2>/dev/null; then
        observed=1
        break
    fi
    sleep 0.2
done
[ -n "$observed" ] || fail "case 2: no progress line within the observation window; wait output: $(head -c 300 "$wf_out" 2>/dev/null), launcher stderr: $(head -c 300 "$TMP/slow.err" 2>/dev/null)"

: > "$TMP/go"   # observed progress -> release the listener

wait "$wf_pid"   # bounded by wait-for-port's own timeout
status=$?

[ "$status" -eq 0 ] || fail "case 2: expected exit 0 once the live child opened the port, got $status (wait output: $(head -c 300 "$wf_out" 2>/dev/null))"
[ "$(progress_count "$(cat "$wf_out")")" -ge 1 ] || fail "case 2: expected progress output while waiting, got: $(cat "$wf_out")"

# ── Case 3: no child_pid, unreachable port -> exit 1 with the timeout message ──

closed="$(closed_port)"
out="$(bash "$ROOT/scripts/wait-for-port.sh" "$closed" 1 NoPidService 2>&1)"
status=$?

[ "$status" -eq 1 ] || fail "case 3: expected exit 1 on timeout without child_pid, got $status"
printf '%s' "$out" | grep -q "failed to start on port" || fail "case 3: missing timeout message, got: $out"

# ── Case 4: live child_pid but timeout elapses -> still exit 1 ──

closed="$(closed_port)"
out="$(bash "$ROOT/scripts/wait-for-port.sh" "$closed" 1 AliveService "$$" 2>&1)"
status=$?

[ "$status" -eq 1 ] || fail "case 4: expected exit 1 on timeout with a live child_pid, got $status"
printf '%s' "$out" | grep -q "failed to start on port" || fail "case 4: missing timeout message, got: $out"

echo "check_wait_for_port_liveness: all 4 cases passed"

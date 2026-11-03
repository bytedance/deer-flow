# Durable MCP control-call leases

The protocol-neutral task runtime polls remote work and sends cancellation
requests outside the Agent loop. `mcp_tasks.lease_seconds` (default 120) is a
crash-recovery window; it does not impose that duration as a remote-call timeout.
The server's existing `tool_call_timeout` still controls remote-call deadlines.

## Why the full operation needs ownership

Without renewal, a status/cancel request taking longer than the claim duration
returns an outcome that the database rejects as expired. Repeating that slow
request can discard every terminal result. Another worker can also reclaim the
row while the original remote request is still running. Separately, SQLite
ignores `SELECT FOR UPDATE`: two deferred transactions can read the same due
row and both return it as claimed.

Poll claims retain the upstream conditional UPDATE that rechecks every eligibility
predicate after reading candidates, including cancellation and lease ownership.
Cancel claim transactions reserve SQLite's writer with `BEGIN IMMEDIATE` before
reading candidates. PostgreSQL continues using `FOR UPDATE SKIP LOCKED`.
These transactions contain only claim bookkeeping, never remote calls.

Each control operation verifies and extends its claim before calling the driver,
then renews every one third of the lease duration. Each renewal has its own
one-third-duration deadline, so a database stall cannot leave a live remote
call unmonitored indefinitely. The heartbeat covers the driver, normalization,
and the existing snapshot/retry persistence boundary. A renewal matches the
row ID, worker, claim token, unexpired lease, nonterminal state and poll/cancel
phase. It cannot renew a replaced generation or a poll superseded by cancellation.
It changes no task activity timestamp or attempt/error counters. Backward clock
corrections cannot shorten the stored expiry.

## Loss, cancellation and cleanup

A failed, timed-out, or rejected renewal stops the local operation. The existing
token-fenced cancellation release preserves task status and diagnostics for
recovery. A task-local ownership-loss fence prevents a driver that swallows
cancellation from subsequently saving a snapshot or recording a retry failure.
Stopping a local status request does not itself cancel the remote task.

The batch supervisor retains ownership of operation, heartbeat and renewal
cleanup through repeated cancellation. Caller cancellation uses its existing
bounded batch handoff; autonomous completion or ownership loss uses the same
bounded drain mechanism. Unfinished cleanup remains service-owned in the background. Draining
control calls keep their local capacity slots and are excluded from later
poll/cancel claims until their children actually settle. Other tasks can proceed
when capacity remains. If all control slots are occupied by uncooperative cleanup,
new control calls wait rather than accumulating more abandoned calls.

This is not exactly-once remote execution. Process death, loss of the event loop,
or a transport that ignores cancellation can still overlap a peer's recovered
request after expiry. Servers must keep status queries safe to repeat and
cancellation idempotent. Notification delivery retains its separate existing
claim/idempotency state machine. No schema migration or new configuration is
required.

## Verification

Run from `backend/`:

```sh
PYTHONPATH=packages/harness:packages/extension-api:. uv run --no-sync pytest \
  tests/test_mcp_task_lease_lifecycle.py \
  tests/test_mcp_task_repository.py tests/test_mcp_task_service.py -q
```

The lifecycle matrix uses the production SQLite repository with a controlled
durable clock and event-gated remote calls. It covers slow poll/cancel results,
interleaved claims, expiry/token/phase fences, ownership loss, unavailable or
hung renewal, persistence after remote completion, delayed admission, repeated
cancellation, late cleanup, spare-capacity progress and concurrent scan admission.
No live MCP service or provider key is needed.

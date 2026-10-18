# AIO Sandbox

## Stdin contracts per transport

AIO has two distinct stdin contracts: the persistent `/v1/shell` transport is a
PTY, while `/v1/bash` uses a subprocess pipe that stays open for writes. Keep
persistent shell commands unchanged: the Lark broker shim already ignores TTY
input. Only fresh `_run_bash_exec` calls prefix the original command with
`exec < /dev/null` so default stdin gets immediate EOF; explicit
pipes/heredocs/files still override fd0. Those sessions are created and
released per invocation, so the prefix never closes a reusable terminal or
alters its state. Avoid brace-group/eval wrappers: they shift top-level
parsing (alias/extglob timing), disturb `PIPESTATUS` across calls, can fire an
`ERR` trap an extra time, or append a delimiter a trailing backslash consumes.

The broker shim forwards pipe/file input only after EOF: an idle pipe exits
124 without a broker request, and read errors fail rather than becoming empty
input. Window overrides must be finite positive seconds, at most 600. Broker
INFO logs contain argc/exit/elapsed only, never argument values.

Regressions: `tests/test_aio_sandbox.py`, `tests/test_lark_broker.py`.


Scoped native C workers install an execution-local physical capture observer only
around receiver adoption. The SQL-adopted Run binds that observer before task
creation. AIO acquisition and identity-checked reuse capture the actual immutable
container ID, retained across warm release; ordinary `get()` reads do not capture.
`destroy_captured` reuses local teardown reservations, ownership and teardown
leases, validates active/warm user-thread identity, and strictly inspects the
captured ID after STOP. It never derives STOP identity from live skills paths.
Missing/ambiguous capture and failed or in-flight acquisition retain capacity.
A text-only NoStart proof requires the same bound native task to have drained
without any acquisition/reuse; sealing capture refuses later acquisitions.
Created and discovered Docker resources preserve immutable container IDs.
These receipts are process-private; restart without a receipt stays unknown,
and this component does not open tenant activation or remote physical acceptance.

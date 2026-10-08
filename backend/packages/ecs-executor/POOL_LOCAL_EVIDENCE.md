# Local outbound pool evidence

Date: 2026-10-09. Task3 implementation, no cloud deployment or push.

RED: `test_shared_budget_resident_overhead_unknown_and_c_eligibility` failed with
`ModuleNotFoundError: No module named ecs_executor.nodes` before implementation.
GREEN: the shared budget test passed after nodes/scheduling implementation.

Actual acceptance command (isolated executor worktree backend environment):

```bash
ECS_EXECUTOR_POOL_TEST=1 backend/.venv/bin/python -m pytest \
  backend/tests/test_ecs_executor_dispatch_main.py \
  backend/tests/test_ecs_executor_b_main.py \
  backend/tests/test_ecs_executor_scope.py -q
```

Observed: exit 0, **20 passed, 1 skipped**, 90 upstream MCP client deprecation
warnings, 20.90 seconds. The skipped test is the separate original B Docker
opt-in test; the pool test in this command ran real Docker jobs.

The test generated a private random PostgreSQL secret in process, started only
a UUID-named `postgres:16-alpine` container on random loopback TCP port, and
started a TCP MCP central plus two independent outbound worker OS processes.
Three actual `alpine:3.20` jobs were submitted and polled through unchanged
`McpTaskService`, ordinary driver, task repository and native scope interceptor.
Two nodes each reserved one 500-mCPU/128-MiB job while retaining resident
500-mCPU/128-MiB Gateway overhead. The third job was observed queued and later
completed after capacity was released. Ledger assertions included terminal jobs
still awaiting removal, verified distinct node assignments, single attempt,
all three native completions and exact Docker stdout. Every job was physically
removed and had durable `physical_stopped=true` before teardown finished.

The small shared-ledger test additionally checks unknown outcome retention,
worker-owner report fencing, C admission through the same budget, and persistent
resident overhead. The real TCP path denies cross-node credentials and protocol/
mount mismatch before admission. C has no runtime execution in Task3.

The fixture terminated its processes, disposed database engines and removed
only its own PostgreSQL and deterministic owned job containers. No secrets or
connection URLs were printed. No cloud, cross-host NAS, C runtime, or native
Goal behavior is established by this evidence. A SPEC regression extension observed RED when expired C reservations were
returned to B recovery. After filtering recovery by kind before adoption, the
focused shared-ledger test passed: B recovery leaves C reservation/ownership
unchanged, while explicitly trusted C recovery can adopt it. Outbound HTTP fixes
both claim and recovery to B. Spec and quality review remain required before
committing Task3.


Quality follow-up: the original shared-ledger unit was extended with a completed
historical row and SQL instrumentation. It observed RED before SQL aggregates
existed, then GREEN after claim switched to SQL COUNT/SUM for unreleased B/C
resource scalars, SQL-filtered FIFO queued candidates with LIMIT 1, and owned
recovery filtered by node/kind/unreleased before payload materialization.
Global advisory serialization and version CAS are unchanged.

Final actual command after both review fixes:

```bash
ECS_EXECUTOR_POOL_TEST=1 backend/.venv/bin/python -m pytest \
  backend/tests/test_ecs_executor_dispatch_main.py -q
```

Observed: exit 0, **2 passed**, 96 upstream MCP client deprecation warnings,
19.90 seconds. This reran the real task-owned PostgreSQL/TCP/two-worker/Docker/
native queue and STOP proof against the bounded SQL implementation. Ruff format
and lint passed for both modified files. No Task3 commit yet.

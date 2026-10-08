# Local B verification evidence

Recorded 2026-10-09 in the `ecs-native-reuse` worktree at base `cf15bda7`, with
uncommitted local B changes. No cloud deployment or node-pool claim is made.

Latest verification uses Python 3.12 in this worktree’s `backend/.venv`, created
by `uv sync --locked --extra postgres --extra redis`. Earlier iterations used an
existing older local backend environment. All test
commands set absolute `PYTHONPATH` entries for this worktree's `packages/harness`,
`packages/extension-api` and `packages/ecs-executor`, so the older environment's
editable installation could not select a different checkout. An initial offline
invocation without these overrides failed with missing old-harness modules;
the corrected invocation below exercised current source.

Focused input-reference RED: extended the existing declared-input test with a
native upload reference; `ExecutionSpec` rejected `input_refs` (1 failed). Added
native-path/owner/incarnation/digest snapshot handling; input-reference and stale
publication checks then passed (2 passed, 1.00 seconds). A subsequent assertion
that replay survives source mutation failed with `Native input digest mismatch`;
added persisted request lookup before rereading references. Latest focused suite
confirms that replay returns the original handle and immutable snapshot.

Specification review identified an aggregate-count admission gap: 64 inline files
plus one reference had been accepted. The single added regression failed with
`DID NOT RAISE`, then passed after enforcing the combined 64-file limit before
ledger insertion. It also submits a subsequent legal job and runs the local
worker tick to confirm that rejection does not stop later execution.

Quality review identified missing terminal container cleanup. The one lifecycle
regression failed with `KeyError: cleanup_pending`, then passed after result
commit also persisted cleanup intent and terminal pending jobs became retryable.
The test observes initial removal failure, reopens SQL and rebuilds the worker,
then verifies successful removal with the same saved result and no start replay.
The real main path now asserts completed containers are removed before teardown.

Latest offline command, from `backend/`:

```bash
PYTHONPATH="$CURRENT_HARNESS:$CURRENT_EXTENSION_API:$CURRENT_EXECUTOR" \
  "$BACKEND_PYTHON" -m pytest \
  tests/test_ecs_executor_scope.py tests/test_ecs_executor_b_main.py -q --tb=short
```

Result: **18 passed, 1 skipped, 1 warning in 1.61 seconds**. The skip is the explicit
real-Docker opt-in. Warning: upstream deprecated `streamablehttp_client` alias.

Latest real main-path command, from `backend/`:

```bash
PYTHONPATH="$CURRENT_HARNESS:$CURRENT_EXTENSION_API:$CURRENT_EXECUTOR" \
  ECS_EXECUTOR_DOCKER_TEST=1 ECS_EXECUTOR_TCP_TEST=1 \
  ECS_EXECUTOR_TEST_DB="$TEST_SYNC_DATABASE_URL" \
  ECS_EXECUTOR_NATIVE_TEST_DB="$TEST_ASYNC_DATABASE_URL" \
  "$BACKEND_PYTHON" -m pytest \
  tests/test_ecs_executor_b_main.py::test_native_sql_http_docker_main_cancel_restart \
  -q --tb=short
```

Result: **1 passed, 23 warnings in 16.48 seconds**. Warnings are upstream MCP
HTTP-client alias and httpx per-request fixture cookie deprecations.

The databases were a fresh dedicated test-owned PostgreSQL container on
an ephemeral loopback port (sync psycopg execution ledger, asyncpg native tracking). No credentials
or full database URLs are recorded. The MCP service was a real separate TCP
process, restarted against the same SQL and private/shared directories. Docker
used the existing `alpine:3.20` image without pulling.

The main test asserted:

- Submit committed a remote handle to native `mcp_tasks` while the remote job was
  staged; the worker alone could not activate it.
- Native background status activated execution with an owner/task-only signature.
- A declared existing native upload script was snapshotted; rewriting its source
  after submission did not change what the container executed.
- Executor restart preserved the running container's exact `StartedAt` value.
- Docker had the operator CPU/memory/user limits and network `none`.
- Output stdout and file bytes were returned through the native artifact API for
  Alice, with Bob denied (404). The private artifact endpoint also enforced owner.
- Native cancellation remained non-terminal while physical STOP was pending;
  after worker removal was confirmed, native status became cancelled.
- Normal completion durably committed cleanup intent and removed its container
  before fixture teardown; saved private/native output remained readable.

The offline stale-thread check denies publication before writing files when
native incarnation has changed. Publication and snapshot traversal use pinned
no-follow directory descriptors, not path-based check-then-follow access.

Ruff check and format use `backend/ruff.toml` (240-column repository style).
Full backend `make test` and `make test-blocking-io` have not been executed by this
B implementation worker; repository-wide gates remain for root coordination.
Root reported independent specification and final quality review PASS after
the aggregate input-count and durable terminal-cleanup repairs. Full repository
gate results remain for root coordination; no overall completion is claimed.

The fresh PostgreSQL test container was removed in the verification runner’s
`finally` block; the execution containers were already absent before test cleanup.
No other containers/images were modified.

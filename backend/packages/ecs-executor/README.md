# Native MCP execution bridge (local B)

This optional package uses DeerFlow's existing HTTP MCP interceptor and
`McpTaskService` ordinary-tools driver. The Agent submits once; native SQL
`mcp_tasks` owns background polling, cancellation and delivery. A separate
`ecs_execution_jobs` ledger owns physical Docker execution. The executor never
reads or writes `mcp_tasks`, creates threads, or starts another Agent loop.

Install alongside the matching local harness in the Gateway environment and on
the execution host:

```bash
uv pip install ./packages/ecs-executor
# PostgreSQL execution/metadata databases:
uv pip install './packages/ecs-executor[postgres]'
```

B is a single-host POSIX/Docker implementation. Run one executor worker for its
private artifact directory and ledger; a process lock rejects a second worker.
It binds HTTP to `127.0.0.1` and requires an operator-provided private JSON config:

```bash
ECS_EXECUTOR_CONFIG=/private/operator/executor.json \
  python -m ecs_executor.mcp_server
```

Copy [executor.example.json](executor.example.json), replace its paths and
image with operator-controlled values, and provide the named credential env
variables. Preload the image: admission uses `--pull=never`. Prefer image digests
for reproducibility. Configure SQL persistence plus enabled native `mcp_tasks`
in the Gateway and register [extensions.example.json](extensions.example.json).
Restart after package, interceptor, task binding or secret changes.

Gateway interceptor configuration:

| Variable | Meaning |
| --- | --- |
| `ECS_EXECUTOR_SCOPE_SERVER` | Exact configured HTTP server name, e.g. `ecs` |
| `ECS_EXECUTOR_SCOPE_SUBMIT_TOOL` | Raw submit tool, e.g. `submit` |
| `ECS_EXECUTOR_SCOPE_STATUS_TOOL` | Raw background status tool, e.g. `status` |
| `ECS_EXECUTOR_SCOPE_CANCEL_TOOL` | Raw background cancel tool, e.g. `cancel` |
| `ECS_EXECUTOR_SCOPE_AUDIENCE` | Exact executor audience, e.g. `executor` |
| `ECS_EXECUTOR_SCOPE_SECRET` | Shared random HMAC secret, at least 32 UTF-8 bytes |

Both management tool env names must be present for B. They must match one native
`task_toolsets` binding and all three names must differ. HTTP `user_auth` must
be enabled with `on_missing: deny`. Set the discovery header to a distinct
credential and provide per-user bearer credentials through environment references.
Gateway `*_AUTH_HEADER` env values contain the full `Bearer <token>` header;
executor `*_CREDENTIAL` env values contain only the matching token.
Discovery returns schemas but cannot execute commands or read artifacts.
Register the scope interceptor last; never configure its reserved
`X-DeerFlow-Execution-Scope` header statically. Redact this header and credentials
from HTTP logs/traces. Builder load failures are skipped by the native loader,
so mandatory server verification remains the final fail-closed boundary.

Submission scopes bind current trusted user, thread, incarnation, run,
operation, audience, expiry and canonical argument digest. Runtime identity never
comes from model arguments or a default user. Management scopes bind only the
persisted authenticated owner, task ID, operation, audience and expiry; they do
not invent a thread/run context after the Agent run ends. Scope lifetime defaults
to 60 seconds, with a 300-second maximum; keep host clocks synchronized. JSON
arguments are bounded to 256 KiB and nesting 32; tokens are bounded to 8 KiB.

A submit response durably stages the job without execution. Only the first
signed native background status poll activates it, after native submission SQL
has committed. Staging expires after 300 seconds by default. The run/request key
namespace returns the same immutable job on retry. A changed spec for an existing
request key fails. Jobs with a persisted start intent and unknown physical outcome
are inspected and never automatically started again. Cancellation reports a
retryable MCP error until the worker observes physical container removal.
Completion and output/publication failures commit a durable `cleanup_pending`
flag alongside the immutable result. The worker scans terminal pending jobs,
verifies container ownership and physical STOP, removes the container, and
clears the flag only after inspection confirms absence. Removal failure or a
process crash retries cleanup after restart without restarting execution or
deleting saved results.

Operator profiles control image, CPU, memory, numeric non-root user, process
count, output budget, execution deadline and Docker network. Arguments cannot
supply Docker flags or override profiles. Network defaults to `none`; an operator
must explicitly list additional networks, and `host`/`default` are forbidden.
Containers have read-only root filesystems, dropped capabilities, no privilege
gain, bounded logs/file sizes, read-only input mounts and private output mounts.

Input files may be small inline base64 snapshots (`input_files`, total 128 KiB)
or declared current-thread native references:

```json
{
  "request_key": "analysis-1",
  "profile": "small",
  "argv": ["sh", "/inputs/program.sh"],
  "input_refs": {
    "program.sh": {
      "path": "uploads/program.sh",
      "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_SHA256"
    }
  }
}
```

References resolve only below the verified owner's native thread user-data
`uploads`, `workspace` or `outputs` directory on a fixed shared workspace.
Absolute host paths, traversal, symlinks, special files and hard links are
rejected. Under a native `threads_meta` owner/incarnation row lock, the executor
checks the supplied digest and persists an immutable snapshot before admission.
Later source changes do not alter retries or execution. The operator's combined
input budget defaults to 8 MiB (`max_input_bytes`, 128 KiB–64 MiB). At most 64
input names are accepted; use distinct inline/reference target names.

Successful output includes bounded stdout, exit code and a SHA256 file manifest.
Collection rejects unsafe files and limits file count to 256 and aggregate bytes
to the selected profile budget. Private `result.json` is atomically persisted and
verified on reads. With fixed `workspace_root` and `metadata_database_url`,
publication locks the existing native thread metadata and verifies owner and
incarnation again. Directory traversal, writes and rename use no-follow dirfds;
publication atomically creates `outputs/<job_id>/` and returns the existing native
artifact API URI. A stale or reassigned thread fails publication and keeps the
private result. This metadata connection needs logical SELECT and row-lock
permissions only; it performs no application schema migration or row mutation.
Without shared publication configured, the owner-authenticated executor artifact
endpoint returns only the private result JSON/manifest.

Private artifact storage, shared workspace and SQL storage must persist across
executor restarts. This local B implementation does not deploy cloud nodes,
implement a distributed pool, or provide node transport/credentials. Existing
shared filesystem mounts are operator infrastructure.

Offline and opt-in main-path verification (from `backend/`):

```bash
uv run pytest tests/test_ecs_executor_scope.py tests/test_ecs_executor_b_main.py -q
# Set throwaway SQL database URLs, never production databases:
ECS_EXECUTOR_DOCKER_TEST=1 ECS_EXECUTOR_TCP_TEST=1 \
  ECS_EXECUTOR_TEST_DB="$TEST_SYNC_DATABASE_URL" \
  ECS_EXECUTOR_NATIVE_TEST_DB="$TEST_ASYNC_DATABASE_URL" \
  uv run pytest tests/test_ecs_executor_b_main.py::test_native_sql_http_docker_main_cancel_restart -q
```

The main path uses a real TCP MCP process, Docker and SQL native task tracking;
it snapshots an existing upload script, mutates the source, verifies the produced
file through the native artifact API, restarts the executor without another
container start, and confirms cancellation after STOP. See
[local B verification evidence](LOCAL_B_EVIDENCE.md) for the recorded run.

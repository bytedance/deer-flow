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
# First stop every process using the executor ledger; provision a dedicated DB.
python -m ecs_executor.schema upgrade --database-url-env ECS_EXECUTOR_DATABASE_URL
python -m ecs_executor.schema check --database-url-env ECS_EXECUTOR_DATABASE_URL
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

Workspace transport preparation (not tenant activation): `mint_execution_scope`
accepts a trusted immutable `workspace_context` and signs protocol `version: 2`
alongside the existing Run identity and argument digest. `verify_execution_scope`
requires an independently authorized `expected_workspace_context` with exactly
matching workspace, actor, membership and policy versions. A scoped verifier
refuses a legacy token; an unintegrated verifier refuses version 2. Tokens do not
resolve membership or authorize parent/child resources. Native Run/MCP/worker
integration and live reauthorization remain pending; the current interceptor
continues to use the legacy protocol behind the closed tenant activation gate.
Do not enable tenant execution on the strength of this signing primitive.

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
Declared relative input and output paths preserve Unicode names and spaces
without normalization (for example, `uploads/报告.xlsx` and `sales report.csv`).
Paths are bounded to 512 UTF-8 bytes total and 255 bytes per component; empty
or dot components, backslashes and control characters are rejected. Absolute
host paths, traversal, symlinks, special files and hard links are rejected. Under a native `threads_meta` owner/incarnation row lock, the executor
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
artifact API URI. Completed native output trees use directories 0755 and non-executable files 0644 so the existing per-thread sandbox mount can read artifacts from a different UID. Staging remains private until content is complete; only the staged job tree changes mode through no-follow directory/file descriptors. Private executor pool results and inputs keep their existing permissions. Owner/incarnation checks and the native artifact API still enforce tenant access. A stale or reassigned thread fails publication and keeps the
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

## Outbound PostgreSQL pool

Set `mode: "pool"` in the private central JSON configuration. Pool mode requires
PostgreSQL; omit `mode` only for the existing single-host compatibility mode.
Central starts no Docker worker and never sends HTTP/SSH to a worker. Keep its
HTTP endpoint private behind the operator's authenticated TLS network ingress.
Do not expose worker listeners or attach public IPs for this transport.

Add fixed operator nodes and separate credential environment variables:

```json
{
  "mode": "pool",
  "lease_seconds": 120,
  "nodes": {
    "ecs-one": {
      "cpu_millis": 2000, "memory_mib": 1024,
      "resident_cpu_millis": 500, "resident_memory_mib": 256,
      "max_concurrency": 2, "profiles": ["small"],
      "kinds": ["B", "C"], "drain": false,
      "worker_version": "0.1.0"
    }
  },
  "worker_credential_env": {"ecs-one": "ECS_ONE_TOKEN"}
}
```

These are additions to the existing central config, including its fixed
`artifact_root`, profiles and owner credentials. Each node's CPU/memory ledger
subtracts the explicitly configured resident native Gateway allocation. B and C
share this resource ledger; native C uses the separate operator-enabled
Gateway transport described below. A drained node receives no new work. Authenticated polls
persist node heartbeat health and renew assigned jobs. Config changes require
central restart. All central instances must use the same operator configuration.

Mount the same NAS `artifact_root` at the same absolute path on central and nodes
before starting either service. Central creates `pool-mount-id`; workers refuse
to start without that marker and the server checks its identity before admission.
Verify the mount with a cross-host write/read probe as an operator deployment
check; a local multi-process test does not establish cloud NAS mount correctness.
Optional native publication retains the existing fixed `workspace_root` and
metadata DB settings; the metadata connection performs only native ownership
reads/row locks, never `mcp_tasks` or control job-ledger writes.

A worker's private configuration contains no execution-ledger DB URL:

```json
{
  "executor_url": "https://private-executor.example",
  "node_id": "ecs-one",
  "credential_env": "ECS_ONE_TOKEN",
  "artifact_root": "/shared/executor"
}
```

Run `ECS_WORKER_CONFIG=/private/worker.json python -m ecs_executor.dispatch`
in the installed executor environment. Add `workspace_root` and
`metadata_database_url` only when using native shared-file publication. Each node
holds its own NAS lock; separate credentials bind it to its fixed node. Run the
worker under a process supervisor (`Restart=always`, `RestartSec=5` for systemd):
a failed outbound transport can terminate the process. Restarted workers wait
for the previous 120-second lease before same-node reconciliation; they never
replay the unknown physical start or free its reservation. Server
protocol and expected worker version fail closed. The worker reuses `LocalWorker`
and deterministic Docker job names plus job/spec/node labels.

Resource admission uses SQL COUNT/SUM over unreleased reservations, and takes
only one eligible queued payload per claim. Recovery filters node/kind/STOP in
SQL; completed historical input snapshots are not loaded by polling.

Claims persist assignment, attempt, report generation and reservation before
HTTP delivery. No lost response or restart issues another start. A new process
may adopt only its same node's unresolved jobs after the 120-second lease, and
only reconciles their existing physical state. Heartbeat loss, lease expiry and
unknown/failed outcomes retain reservations. Actual STOP/removal releases the
job allocation; resident Gateway overhead stays allocated. Program deadlines,
HMAC capability TTL and the 120-second cleanup safety allowance are independent.

The opt-in main acceptance test provisions only a task-owned PostgreSQL
container, starts a central TCP process and two outbound worker OS processes,
and runs three real Alpine jobs through unchanged native MCP task tracking:

```bash
ECS_EXECUTOR_POOL_TEST=1 uv run --no-sync pytest tests/test_ecs_executor_dispatch_main.py -q
```

It verifies node assignment, resident overhead/concurrency caps, queued work
using released capacity, report fencing, and physical cleanup. It removes only
its own PostgreSQL/job containers. This is local transport evidence, not cloud
or native C-runtime deployment evidence.

## Native Gateway outbound execution (opt-in)

`ECS_NATIVE_CONFIG=/private/central.json` or `/private/worker.json` installs a
trusted native admission host in the normal Gateway lifespan. Missing optional
package, invalid configuration, or host initialization failure aborts enabled
startup. Install this package alongside the normal backend environment; launch
both roles through the normal `uvicorn app.gateway.app:app` entry point.
The JSON examples in `examples/ecs-native/` contain environment references only.
Use the same PostgreSQL, Redis, JWT/internal-auth secrets, native owner database,
and absolute NAS paths for both Gateways. Native config requires
`deployment.multi_instance: true`, PostgreSQL, DB run events, Redis stream bridge,
and ownership heartbeats. Thread admission and deletion retain native serialization.

The central stages a C job before handing off the original pending native Run.
The worker polls outbound, verifies the signed canonical admission and assignment,
and adopts that exact Run without another `create_or_reject` or graph loop.
Native checkpoints, events, results, and cross-instance cancellation retain their
existing APIs. Adopted tasks remain tracked through retryable transport/report
failures; known settled outcomes retry idempotent reports and owned STOP without
replaying a graph. Shutdown first quiesces claims/adoption before RunManager takes its drain
snapshot. An adoption lock and synchronous checks around native CAS/task attach
fence late graphs. A cleanup-only watcher observes already-adopted aborts and
shares owned STOP to unblock native tool finalizers. Host cleanup waits within
the 120-second physical allowance, then cancels retry wrappers; unresolved native
finalizers/STOP retain the client and node lock until they unwind. Queued
cancellation and pre-adoption refusals persist typed SQL-filtered settlement
intents before native terminal commits. Refusals require exact dispatch ownership
and assigned node/worker/generation; cancellation wins the pending error CAS.
Recovery confirms matching native error/action and END before dynamic release.
A changed native owner remains uncertain and reserved, without synthetic END. Trusted scheduled origin places new heavy work remotely; later
admissions for the same owner/thread/incarnation follow durable fixed-node affinity.
External request metadata cannot select placement. Caller request secrets use
the native Fernet credential cipher keyed by the selected node credential; only
string pairs cross, inside an owner/thread/incarnation/Run/node-bound carrier in
the signed immutable snapshot. Ledger and native config remain redacted, and
only the worker in-memory config restores the native skill secret carrier. B polling only consumes B jobs.
Queued C leases renew before native startup orphan reconciliation on every role.
Workers require authenticated outbound bootstrap renewal before that recovery;
central unavailability aborts worker startup and releases its client/node lock so
a supervisor can retry after central is ready. Unknown started
attempts are retained, never replayed or treated as physically stopped.

The 2 CPU / 4 GiB example reserves 1500m CPU / 2048 MiB continuously: native warm
AIO uses Docker limits 1 CPU / 1 GiB and the Gateway has a conservative 500m CPU /
1 GiB resident allowance. C dynamically reserves another 500m / 1024 MiB. The
Gateway allowance is a total process cap, not a separate cgroup per Run. Linux
launch supervision must actually enforce that cap; local macOS HTTP acceptance
does not prove Linux cgroup enforcement. Warm AIO remains charged after a success.
`physical_stopped=true` on successful C releases its dynamic reservation only;
cancelled C additionally proves exact sandbox absence after native task finalizers.
Native `hard_capacity: true` blocks creation if warm destruction fails or physical
old containers remain; default provider behavior is unchanged. One native role
holds a separate NAS node lock, allowing the ordinary B daemon on the same node.

The initial real main acceptance config explicitly enables native bash/file tools
and disables browser and memory. Its ordinary path leaves Scheduler disabled. It proves actual model and isolated
native tools, original Run ownership, peer events/checkpoints, and affinity. Full
configured browser capability remains subject to the native multi-instance gate;
Native dependency notifications now forward outbound into the same central native
notification launcher. Durable receipts bind awaited native MCP tasks to the
original goal revision and visible conversation; all tasks must be terminal before
one idempotent group continuation. Source finalizers drain before B acquires the
shared slot. Cancellation, replacement, new messages and cumulative native budgets
reject stale goal work. A stale result notification may report its bounded native
task result without model tools or goal mutation. Scheduled waits retain their
original goal and overlap slot; atomic occurrence transfer precedes queue activation.
Recovery validates current receipt/goal/cancellation/occurrence outside writer
transactions; removed host configuration cannot retain a historical wait forever.
The native scheduler snapshots sources before validation, resolves each receipt
exactly, and defers sources completed after that snapshot to the next pass.
Global notification claims may forward from any authenticated node, including
ordinary tasks with no source RunId; canonical native task scope determines
identity while central placement determines whether a goal continuation is valid.
Shared memory text/locks must use NAS and the SQLite FTS index must stay local per
instance when enabled. Cloud NAS/cgroup/combined C-B-C deployment acceptance is
still required before claiming full remote deployment completion.

The combined local main uses the same owned PostgreSQL/Redis/native HTTP fixture,
one node and one dynamic slot, actual DeepSeek, Alpine Docker B, native file tools
and `present_files`. Run `tests/test_ecs_executor_bc_main.py::test_real_native_c_mcp_b_same_goal_c`
with the same environment below to select only the ordinary combined main. Scheduler goal/occurrence recovery is covered by focused native
runtime and SQL contracts. This is an independent package with explicit optional
core hooks, rather than a fully portable extension plugin.

Run the single opt-in actual model acceptance with operator-owned model sources:

```bash
ECS_NATIVE_LIVE=1 ECS_NATIVE_MODEL_CONFIG=/private/config.yaml \
  ECS_NATIVE_MODEL_ENV=/private/.env uv run --no-sync pytest tests/test_ecs_executor_c_live.py -m live -q -s
```

It starts test-owned PostgreSQL/Redis and two normal native HTTP Gateway processes,
uses DeepSeek plus native AIO Docker tools, reads peer native state, checks the one
original Run/worker owner and native tool calls, verifies container-local warm
state on a later interactive admission, then requests central cancellation and
checks physical Docker STOP. It cleans only its own infrastructure. Model secrets
stay in child environments and are not persisted in the execution snapshot.

### Native Scheduler roles

With `scheduler.enabled: true`, `scheduler.tool_enabled: true`, and
`scheduler.multi_instance: true` on both native Gateways, control hosts run the
existing `ScheduledTaskService` poller. Execution-only outbound workers retain
the same native foreground service and completion hook, but do not recover,
claim, or launch occurrences. Their trusted host sets
`scheduler_dispatch_enabled=False`; core defaults to normal dispatch when no
host supplies this optional contract. Native schedule creation and own-occurrence
stop tools remain owner-bound. Manual trials/triggers on an execution host enter
the shared durable occurrence queue for the control poller. Shared Postgres,
DB run events, ownership heartbeats, and all Scheduler switches remain required.
Browser/UI ingress remains the control Gateway, whose features report
`running=true`; execution-only workers report `running=false` and may report
`tool_enabled=true`. Their foreground APIs/tools do not imply a local poller.

The opt-in `test_real_scheduled_native_c_mcp_b_same_occurrence_goal_c` reuses the
existing owned live fixture. An authenticated once task is launched automatically
by the real Scheduler into the original pending native Run, executes on the
fixed remote C worker, waits for ordinary MCP B, then resumes C with the same
occurrence and native goal budget. Final native file delivery settles the once
task with one occurrence/count and clears its goal. Browser and cloud
acceptance remain separate work; native memory has its own opt-in case below.

Run only the actual scheduled main from `backend/` (Docker images and the locked
backend environment must already exist; credentials are read-only inputs):

```bash
ECS_NATIVE_LIVE=1 ECS_NATIVE_MODEL_CONFIG=/private/config.yaml \
  ECS_NATIVE_MODEL_ENV=/private/.env PYTHONPATH=.:packages/ecs-executor \
  uv run --no-sync pytest \
  tests/test_ecs_executor_bc_main.py::test_real_scheduled_native_c_mcp_b_same_occurrence_goal_c -q -s
```

### Native memory configuration

Native C reuses the normal memory backend and server-owned user/agent identity.
Merge the memory overlay in `examples/ecs-native/native-memory.yaml` into each
role's normal Gateway config: enable native `deermem` in `tool` mode, share
`DEER_FLOW_HOME` for canonical per-user summaries/Markdown facts and locks, and
omit `backend_config.storage_path`. Set the overlay's
`DEER_FLOW_MEMORY_INDEX_PATH` environment reference to a distinct absolute
instance-local directory on every Gateway. Derived SQLite FTS/WAL/SHM files
must stay off shared NAS. Shared manifest revisions refresh each local index
when a peer writes; no executor memory store or control protocol is involved.
The overlay is not a complete startup config. Use the exclusive-create merge
command in [the operator example](../../../examples/ecs-native/README.md) to
replace only the base config's `memory` section while preserving model/database/
auth settings, then set `DEER_FLOW_CONFIG_PATH` to that merged file. Give each
role its own merged config and local index path.

The opt-in single actual-model memory main reuses the C fixture's owned
PostgreSQL/Redis and two normal native Gateways:

```bash
ECS_NATIVE_LIVE=1 ECS_NATIVE_MODEL_CONFIG=/private/config.yaml \
  ECS_NATIVE_MODEL_ENV=/private/.env PYTHONPATH=.:packages/ecs-executor \
  .venv/bin/python -m pytest \
  tests/test_ecs_executor_c_live.py::test_native_remote_memory_shared_facts_and_owner_isolation -q -s
```

It primes the peer before the API seed, then requires the actual worker's
`memory_search` and `memory_get` to retrieve a UUID receipt value absent from
the prompt. Actual `memory_add` writes another fact visible from central and
worker; native `write_file`/`present_files` deliver the retrieved content. Both
APIs exclude those facts for another registered owner. One original remote Run,
worker ownership, DB events, canonical Markdown files and two separate local
indexes are checked. The ordinary shell/BC/Scheduler fixture modes retain their
existing defaults. This local shared-directory acceptance does not prove cloud
NAS behavior, browser support, or Linux Gateway cgroups.

## Native browser affinity/control

Browser control is an explicit operator hook implemented by this package. It is
not a public packaged-extension contribution point. Install the native locked
`browser` extra and Chromium in the matching Gateway image/environment. Add this
section to **both** role JSON files selected by `ECS_NATIVE_CONFIG`:

```json
"browser_control": {
  "provider": "ecs_executor.browser:build_browser_control_provider"
}
```

Enable the normal native browser tools on both roles (see the partial overlay
`examples/ecs-native/native-browser.yaml`). Keep `allow_private_addresses: false`
and CDP disabled. The startup provider snapshot is read once, validated before
multi-instance admission, then bound to the native host. Ordinary deployments
without the provider keep the process-local browser startup rejection; multiple
uvicorn workers remain unsupported even with the provider.

The central role admits all native C origins to its fixed serial worker when
browser control is enabled. UI navigation before the first Agent turn places the
same owner/thread/incarnation affinity without creating a Run. The worker opens
an outbound WebSocket to the existing central Gateway at
`/api/native-workers/{node}/browser-control`; no worker listener or direct
controller-to-worker HTTP connection is introduced. Production requires HTTPS /
WSS. The explicit `test_only_allow_loopback_plaintext: true` flag exists only for
literal-loopback local fixtures and must not be used in deployment examples.
The existing reverse proxy must forward WebSocket upgrades on this central route;
deployment routing and Linux cgroup evidence belong to deployment acceptance.

Control permits only native navigate and native Live operations, with signed
owner/thread/incarnation, operation/argument digest, fixed node/tunnel owner,
expiry, and original header digest. Actual cookies/Authorization/Origin/Host
travel in memory through TLS into the worker's existing ASGI routes. Both sides
run native auth, permissions, exact thread ownership, and Origin admission; a
signed executor identity never replaces user authentication. Browser state,
cookies, and control credentials are not written to SQL, Redis, or logs. Input
and frame queues/message sizes are bounded. Disconnect cancels the operation;
effectful input is never replayed after reconnect. Canonical deletion/reset
retires scoped sessions and streams; a restarted worker has fresh browser state.

Tools and UI use the same native guarded Playwright session, keyed by verified
owner/thread/incarnation through a host-only ContextVar. Native subagent/task and
thread hops preserve the binding. The opt-in one-session physical-capacity mode
counts retained, closing, and uncertain sessions. Unpinned LRU retirement rejects
the new operation with retryable capacity until native close confirms disconnect;
pinned/uncertain sessions cannot be replaced. Shutdown retains the worker node
lock when physical browser closure is unknown. Cross-process physical containment
still requires the Gateway container cgroup and complete container STOP.

The normal readiness endpoint probes native infrastructure, not worker browser
connectivity. A central provider may start before the worker, avoiding bootstrap
cycles; browser operations return 503 while no verified tunnel is connected.
Use the opt-in single-case local acceptance command (credentials stay in memory):

```bash
ECS_NATIVE_LIVE=1 ECS_NATIVE_MODEL_CONFIG=/read-only/config.yaml \
ECS_NATIVE_MODEL_ENV=/read-only/.env \
  .venv/bin/python -m pytest \
  tests/test_ecs_executor_c_live.py::test_native_remote_browser_model_and_control_share_session \
  -q -s --no-showlocals --tb=short
```

This fixture reuses owned PostgreSQL/Redis/AIO, uses only required model/process
settings in browser child environments, and suppresses local-variable failure
dumps for the explicit live session. Local Chromium closure/session behavior
is evidence separate from cloud cgroup/reverse-proxy deployment acceptance.

The worker watcher registry retains only manager-retained physical identities
(including closing/unknown), bounded active relay operations, and the one active
native task. Unused or LRU-retired identities are pruned. Canonical deletion/reset
cancels and drains only operations for the same verified scope; cancelled HTTP
operations return an unknown-outcome terminal response and are never replayed.
Worker browser teardown belongs to the native host deferred release after native
finalizers, including when its bounded shutdown drain allowance expires.

Production tunnel admission requires the actual ASGI scheme `wss`. When TLS
terminates at nginx, configure restricted trusted proxy forwarded-proto handling;
WebSocket Upgrade alone does not establish this. The literal-loopback fixture
exception is not production TLS evidence.

Strict session retirement is permanent: held Live/tool references cannot rebuild
Chromium after close. Initialization is shielded through private-loop settlement,
and physical close shares its initialization lock, so an in-flight launch cannot
outlive a successful capacity release. Default session behavior is unchanged.


## Versioned private executor schema

The executor owns a dedicated database containing only `ecs_execution_jobs`,
`ecs_execution_nodes`, `ecs_native_affinities`, and
`ecs_executor_alembic_version`. Native Run/MCP/schedule/checkpoint tables stay in
the native application database. `metadata_database_url` names that **native**
database for owner file publication; it must not name the executor database.
The B service and central Gateway call a read-only revision/shape guard before
dispatch. Outbound B/native workers send and check schema revision
`e0001_execution_ledger` through the existing authenticated worker channel;
missing/unknown revisions fail closed. Matching version text alone cannot adopt
unknown column/default/generated/key/FK/CHECK/index/collation semantics. Unknown constraints
are refused without deletion or repair; neutral PostgreSQL reflection defaults
are accepted. SQLite requires native BINARY index semantics and conservatively
refuses explicit column/table COLLATE overrides; PostgreSQL columns must retain
the native type-default collation. CLI URL construction and failures remain redacted. No startup config flag selects bootstrap.

`python -m ecs_executor.schema upgrade` is an explicit stopped-writer operation.
It executes private Alembic migrations, including adoption of an exact previously
unversioned accepted ledger without changing job/node/affinity records. Unknown
reservations and ambiguous physical starts remain retained; the migration never
claims, starts, releases or replays a job. `JobStore.initialize()` is an explicit
Python test/local helper executing this same versioned upgrade; production
entrypoints never call it. Unknown version rows, native/Fleet tables, and malformed
existing ledger shapes are refused. SQLite remains an isolated single-host/local
option; multi-host production requires PostgreSQL and a dedicated database.
See [schema, legacy quarantine and rollback](../../../docs/ecs-native-fork-integration.md).
Current live helpers now provision an owned independent executor database and
observe native tables through the native URL. Their prior model evidence is
historical; these schema wiring edits were checked without repeating model runs.
Ops/cgroup/cloud/restart acceptance belongs to Task6B.

Task6B native role Compose, private reference-only generation, durable operator drain
and stopped-writer image selection are documented in `docs/ecs-native-deployment.md`. Installed/cloud acceptance remains separately recorded;
cloud/Jenkins work is paused.

## Tenant schema foundation (implementation in progress)

This development branch requires `e0002_workspace_scope` for production ledger
admission. The explicit offline upgrade accepts only reviewed legacy/current
shapes, adds nullable indexed workspace fields to jobs and native affinities,
and leaves existing physical reservations, JSON payloads and versions intact.
It never assigns legacy tenant ownership or replays work. New job creation
persists scope; mutation and conflicting create retries cannot change it.

These columns are not user authorization. Tenant protocol, live membership
checks, native/executor backfill and the controlled migration receipt remain
required. The historical Shanghai release manifests and same-schema operations
contract still describe `0035/e0001`; do not edit their receipts or use that
release flow to claim a `0036/e0002` rollout. No deployment has been performed.

`tenant_backfill.py` provides offline plan/apply attribution from a pinned native
ownership export. Only exact user/thread/incarnation/run bindings acquire scope;
unknown or conflicting records remain quarantined. Apply changes only indexed
scope and top-level JSON scope, preserving job versions, physical state, native
snapshots and affinity node selection. It never authorizes runtime access or
releases physical capacity. The caller must stop writers and retain coherent
backups plus both database receipts. Native `export_native_workspace_bindings` now supplies the metadata-only DTO.
A guarded operator CLI and paired migration receipts are still required;
hand-authored bindings are not a deployment procedure.

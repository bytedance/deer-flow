# AGENTS.md

## Project Overview

Native ECS dependency coordination lives in the independent `ecs_executor.dependencies`
package. Optional trusted RunContext receipts and lifecycle callbacks preserve the
native goal/checkpoint authority; harness code imports neither app nor executor.
Worker-origin notifications use signed outbound transport into the existing MCP
notification launcher. Scheduled source receipts are validated outside ORM writer
transactions before recovery; the native repository receives valid source IDs and
an explicit checked-source snapshot. Newly completed unexamined sources defer one
pass; with no host, native recovery settles historical waits normally. Exact
scheduled-source receipt lookup avoids ordinary waits masking recovery. Occurrence
RunId transfer precedes physical queue activation and
preserves original accounting. Superseded notifications report results with no
goal injection, model tools or tool execution. Native memory retains shared owner facts and local per-instance indexes. Optional
browser control uses an immutable operator provider snapshot, native scoped
Playwright sessions and an outbound native HTTP/Live relay. Worker teardown is
owned by native-host release after finalizers; strict retired sessions cannot
reinitialize. See the Gateway and tools guides. Shanghai native HTTP/WSS, cgroups and NAS main acceptance is recorded in
`../docs/ecs-native-testing.md`; this does not establish OS reboot recovery.

The backend runs a LangGraph-based super agent with sandbox execution, persistent memory, subagent delegation, and extensible tools in isolated per-thread environments.

**Architecture**:
- **Gateway API** (port 8001): REST API plus embedded LangGraph-compatible agent runtime
- **Frontend** (port 3000): Next.js web interface
- **Nginx** (port 2026): Unified reverse proxy entry point
- **Provisioner** (port 8002, optional in Docker dev): Started only when sandbox is configured for provisioner/Kubernetes mode

**Runtime**:
- `make dev`, Docker dev, and production all run the agent runtime in Gateway via `RunManager` + `run_agent()` + `StreamBridge` (`packages/harness/deerflow/runtime/`). Nginx exposes that runtime at `/api/langgraph/*` and rewrites it to Gateway's native `/api/*` routers.
- Gateway streams `write_file` and `str_replace` argument deltas in bounded batches for multi-mode `messages-tuple` consumers; single-mode message consumers retain the original per-chunk contract. Non-message frames flush pending batches, and `values` remains an optional complete-state snapshot rather than a prerequisite for batching.
- Subgraph SSE frames retain their namespace; root consumers must not treat them as root state. Background subagents use provider tool_call_id for messages/events/public scope and a distinct server execution_id for registry ownership, cancellation and cleanup. Provider IDs are not globally unique; retain each SubagentResult in scheduler closures. Usage comes from the run's ToolMessage, never a global ID cache. See [runtime](packages/harness/deerflow/runtime/AGENTS.md) and [subagents](packages/harness/deerflow/subagents/AGENTS.md) for streaming, lazy entrypoints and lifecycle contracts.
- Scheduled tasks dispatch through the normal Gateway run path. `launch_scheduled_thread_run` reads `get_app_config()` at dispatch and passes `scheduler.recursion_limit` (default 1000, matching the web UI; clamped by `max_recursion_limit`), so YAML changes apply on the next run without restarting Gateway.
- Run-history `status` filters are occurrence states, not task states. `ScheduledTaskRunStatus` in `persistence/scheduled_tasks/model.py` is the shared API/repository vocabulary and must match the active and terminal occurrence-status sets. Keep owner lookup before reading history, and apply SQL task/status predicates before pagination; omitted status preserves the existing response.
- The background scheduler is single-instance by default. `scheduler.multi_instance=true` opts into lease-aware recovery across Gateway instances and requires shared Postgres, `run_ownership.heartbeat_enabled=true`, and `run_events.backend=db`; otherwise startup rejects the configuration. Live scheduled runs are preserved when a peer starts; expired launch claims return to the durable queue, expired run leases are atomically taken over, stale launch writes are fenced by lease ownership, and the Postgres advisory-locked budget makes `max_concurrent_runs` a shared global cap for `launching`/`running` rows.
- Trusted native admission hosts may opt out of Scheduler dispatch via `scheduler_dispatch_enabled=False`. The native service starts foreground operations and completion observers without startup recovery or a polling loop; manual triggers persist queued occurrences for control-host dispatch. `is_running` still describes the local poller; `is_available` gates tools and task creation. ECS role policy stays in `NativeWorkerHost`, with both Scheduler flags and multi-instance startup requirements preserved.
- The multi-process startup gate also fires on `deployment.multi_instance: true`; contract in `docs/CONFIGURATION.md`.
- Long-running MCP work uses a separate durable task runtime (`McpTaskService` + `mcp_tasks`, lease-based recovery) rather than keeping remote task IDs or status polling inside the Agent loop; only submit remains Agent-visible, the database is the source of truth, and `ThreadState` receives only a bounded current-thread projection. Full contract (leases, cancellation fencing, delivery idempotency, management-tool exposure): [packages/harness/deerflow/mcp/AGENTS.md](packages/harness/deerflow/mcp/AGENTS.md).
- MCP task notification retries, dead-lettering, and the cancel endpoint's worker-stopped 503 are part of that same contract — see [packages/harness/deerflow/mcp/AGENTS.md](packages/harness/deerflow/mcp/AGENTS.md).
- Scheduled admission allows one active queued/launching/running occurrence per task. Only lease-fenced launching calls Gateway; stable idempotency reuses durable runs. Queue conflicts return to queued, other launch errors fail. Serialize before shared/global and per-owner budget counts (Postgres advisory lock; SQLite BEGIN IMMEDIATE), excluding waiting rows. Coalesce triggers and enforce same-thread FIFO. Mutations lock parent before occurrence: pause/delete cancel queued but reject launching/running; PATCH/resume reject all active states. Manual triggers may queue/run while paused. The persistence guide owns exact leases, queue timeouts and recovery semantics.
- Scheduled-task lifecycle, recovery and queue timeout: [persistence guide](packages/harness/deerflow/persistence/AGENTS.md#scheduled-task-lifecycle).
- `POST /api/scheduled-tasks/preview-cron` requires authenticated `threads:read`. Bounded cron previews call the shared scheduler calculator in `asyncio.to_thread`, preserving its DST semantics. Capture the optional aware reference once; return UTC and offset-bearing local occurrences without acquiring task/thread/run stores or dispatching work. This advisory API does not reserve execution.
- Gateway MCP/skill updates write `extensions_config.json` at runtime. Production Compose mounts it read-write (`config.yaml` stays `:ro`); Helm seeds a writable home-volume copy. Hold both `extensions_config_write_lock` and the sidecar advisory `extensions_config_file_lock` during read-modify-write to prevent lost updates across workers. `atomic_write_extensions_config` uses temp-file replacement; only mount-point `EBUSY` permits a non-atomic in-place overwrite (crashes can truncate). Warn about this fallback once per target; propagate other errors. `get_extensions_config()` revalidates reads by file signature; see [config caching](packages/harness/deerflow/config/AGENTS.md). Tests: `tests/test_compose_extensions_config_writable.py`, `tests/test_extensions_config_atomic_write.py`, `tests/test_helm_extensions_config_writable.py`.
- MCP cache reset scope and discovery fencing: [MCP guide](packages/harness/deerflow/mcp/AGENTS.md).

**Module map** (read the owning guide before changing a module):
- Gateway REST/auth/runtime wiring: [app/gateway/AGENTS.md](app/gateway/AGENTS.md); IM platforms: [app/channels/AGENTS.md](app/channels/AGENTS.md).
- Harness framework: [packages/harness/deerflow/AGENTS.md](packages/harness/deerflow/AGENTS.md). Its agents, runtime, sandbox, MCP, config, persistence, models, skills, extensions and tools directories each own an `AGENTS.md`.
- Public extension contracts: `packages/extension-api/` (`deerflow_extension_api.*`); native ECS adapter: [packages/ecs-executor/README.md](packages/ecs-executor/README.md).
- Tests: [tests/AGENTS.md](tests/AGENTS.md); benchmarks: `scripts/benchmark/`; application configuration and skills live at the repo root.

ATX outline closing markers use a linear suffix scan; do not use unanchored
whitespace regex searches on unbounded uploaded headings. The long-heading
regression exercises the production extractor under a generous process deadline.

## Important Development Guidelines

### Documentation Update Policy
Every code change must keep docs accurate and current: update `README.md` for
user-facing behavior and the relevant `AGENTS.md` for development changes.
`CLAUDE.md` imports `AGENTS.md`; do not edit the shim.

### Backend Benchmarks

`scripts/benchmark/context_snapshot/`: explicit `run-live` needs provider env
vars; `summarize` and pytest are offline. See its README for the protocol.

Benchmarks in `scripts/benchmark/` must be standalone and reproducible. Import
production functions; never duplicate them or introduce an alternative runtime.

- Pin every external dataset by immutable revision and SHA-256. Callers provide
  the local dataset path; evaluation commands must not silently download data.
- Never commit upstream dataset text, credentials, complete provider requests,
  or response headers. Committed manifests may contain stable IDs and source
  locators. Synthetic cases must identify themselves as synthetic.
- Read provider credentials and endpoints from named environment variables.
  Version model IDs, inference parameters, prompts, retry rules, clocks, and
  random seeds in the evaluation config.
- Public raw results may contain case IDs, policy decisions, model hypotheses,
  grades, and non-secret response metadata. Keep dataset questions, reference
  answers, memory content, and full provider payloads in ignored local run
  directories.
- Use fixed clocks and deterministic ordering for offline selection. Results
  must record the config, manifest, prompt, dataset, and git revisions used.

`scripts/benchmark/deermem_eviction/` evaluates production `select_facts_for_capacity()` only for historical confidence and opt-in hybrid-v1. Its [README](scripts/benchmark/deermem_eviction/README.md) owns commands/dataset contracts. Offline tests use synthetic fixtures and require no provider credentials, network or LongMemEval dataset.

`scripts/benchmark/concurrency/` measures users-table contention in separate OS processes, not asyncio tasks, for SQLite/Postgres. Its orchestrator bootstraps once; workers mirror production SQLite PRAGMAs, synchronize READY/GO and fail on crashes, short counts or errors. PostgreSQL uses a disposable per-run schema from --pg-url, never public. Run the existing `run_concurrency_bench.py` and `tests/test_bench_concurrency.py`/`test_bench_worker.py` from backend.

## Commands

**Root directory** (for full application):
```bash
make check      # Check system requirements
make install    # Install all dependencies (frontend + backend)
make extension-install SOURCE=...  # Install and enable a trusted Python extension
make extension-upgrade SOURCE=...  # Replace an installed extension and keep its config
make extension-list                # List configured Python extensions
make extension-enable NAME=...     # Enable an installed extension
make extension-disable NAME=...    # Disable an extension without uninstalling it
make extension-remove NAME=...     # Remove a managed extension
make detect-thread-boundaries  # Inventory backend executor/thread/event-loop boundaries
make dev        # Start all services (Gateway + Frontend + Nginx), with config.yaml preflight
make start      # Start production services locally
make stop       # Stop all services
```

**Backend directory** (for backend development only):
```bash
make install            # Install backend dependencies
make dev                # Gateway API, reload (port 8001)
make gateway            # Gateway API only (port 8001)
make test               # four offline workers; TEST_JOBS=1 for serial
make test-live          # live tests (real APIs)
make test-blocking-io   # strict Blockbuster gate on tests/blocking_io/
make test-shard SPLITS=4 GROUP=2  # one duration-aware shard
make test-shard-durations  # refresh baseline
make lint               # ruff lint
make format             # ruff format
make migrate-rev MSG="..."  # Autogenerate a new alembic revision (see Schema Migrations section)
```

The backend `make dev` target pre-creates and excludes `DEER_FLOW_HOME`
(default: `backend/.deer-flow`) and `backend/sandbox` from Uvicorn's reload
watcher. Do not replace it with a bare `uvicorn --reload`: agent tasks write
Python and other runtime files below `DEER_FLOW_HOME`, which would otherwise
restart the Gateway during an active run.

Configuration checks and operator migration scripts reuse the installed backend
environment with `uv run --no-sync --project backend` from the repository root.
`--project` preserves the caller's working directory and relative runtime/config
selectors; `--no-sync` retains installed extras such as PostgreSQL drivers.

More specific `AGENTS.md` files in backend code directories contain the subsystem sections split from this file. Follow the nearest file in the directory tree.

## Architecture

- **Native ECS execution bridge**: optional `packages/ecs-executor` integrates ordinary persistent MCP jobs with native Gateway execution; [package contract](packages/ecs-executor/README.md) owns protocol, recovery, dependency and browser depth. No second Agent loop, checkpoint, goal, thread or native task authority is permitted. Harness imports neither app nor executor.
- Submit scopes bind authenticated owner/thread/run/incarnation; management scopes bind persisted owner/task and require fail-closed `user_auth` plus matching `task_toolsets`. Native `McpTaskService` commits before signed status polling activates the executor's separate ledger. Fixed node credentials, protocol/version and canonical NAS marker precede admission. Central never executes Docker or connects inbound to workers; B workers never adopt C.
- Shared Scheduling uses a PostgreSQL advisory lock and resident deductions; SQL aggregates unreleased capacity, selects eligible FIFO work with LIMIT 1, and filters recovery before loading records. Never materialize completed history during polling. C snapshots/signs the admitted native Run and adopts it through `native_admission.adopt_native_run`; `services.execute_admitted_native_run` remains the sole execution closure. Install the host before orphan recovery and fail closed on invalid configuration or unavailable authenticated outbound bootstrap.
- Assignment/attempt/generation and start intent persist before delivery/start. Reports whitelist result/start/STOP fields and fence owner/generation/snapshot. Never replay unknown starts or release/move uncertain work on lease expiry. Same-node recovery changes only report ownership after the 120-second safety allowance. Queued cancellation/pre-adoption refusal persists settlement intent before native terminal commit/END/release; error CAS cannot overwrite cancellation. Changed native ownership stays reserved.
- Shutdown fences claims/adoption/task attachment, tracks adopted aborts through finalizers and physical STOP, and quarantines client/node locks when uncertain. Native and B node locks are separate but capacity is shared. Warm AIO is charged continuously: 1 CPU/1 GiB, replicas=1, hard capacity and strict physical counts. Release follows native finalizers; cancellation verifies exact sandbox destruction. Terminal output/publication failures retain results plus cleanup_pending; node-scoped cleanup clears it only after verified physical absence, preserving retries across removal errors/restarts.
- Profiles own immutable image/resources/non-root user/network; default network is none with an explicit allowlist. Request secrets cross only as native Fernet-encrypted caller pairs bound to signed owner/thread/incarnation/Run/node, then rebind into worker memory; ledger/API configuration remains redacted. Inputs use fixed Paths, owner/incarnation threads_meta row locks, no-follow dirfds and SHA256 immutable snapshots. Outputs use bounded manifests and atomic dirfd rename to native outputs/job_id; metadata DB access is SELECT/row-lock only. Preserve Unicode/spaces (512 UTF-8 bytes total, 255/component); reject controls, backslashes and empty/dot components without alias normalization.

### Harness / App Split

The backend is split into two layers with a strict dependency direction:

- **Harness** (`packages/harness/deerflow/`): Publishable agent framework package (`deerflow-harness`). Import prefix: `deerflow.*`. Contains agent orchestration, tools, sandbox, models, MCP, skills, config — everything needed to build and run agents.
- **App** (`app/`): Unpublished application code. Import prefix: `app.*`. Contains the FastAPI Gateway API and IM channel integrations (Feishu, Slack, Telegram, DingTalk).

**Dependency rule**: App imports deerflow, but deerflow never imports app. This boundary is enforced by `tests/test_harness_boundary.py` which runs in CI.

Use `deerflow.*` for harness imports and `app.*` for application imports. Never import app from harness, even indirectly; the boundary test enforces this.

Package import hygiene: the `deerflow.agents` and `deerflow.subagents` package
roots expose heavyweight graph/executor entrypoints lazily. The
`deerflow.agents:make_lead_agent` LangGraph Server entrypoint is a concrete thin
module-level function because the server resolves graph factories directly from
the module dictionary; the wrapper keeps the lead-agent and skill-cache imports
inside the function so importing the package remains lightweight. Internal
modules that only need lightweight types, config, or registries should import
the concrete submodule instead of adding eager package-root imports that pull in
the tool graph or subagent executor during state/schema imports.

`ThreadMetaStore.search()` keeps JSON filter semantics identical across memory,
SQLite, and PostgreSQL: missing differs from null, bool differs from int, and
float filters accept integer or real JSON numbers through `json_value_matches`.

### Gateway Run-Context Trust Boundary

Gate server-owned run context on both client feeds (`body.context` and
`body.config`): `merge_run_context_overrides` admits it only for `internal=True`,
while `strip_internal_context_keys` scrubs both destinations. Treat
`disable_clarification` like `non_interactive`. Before run/state writes,
`_normalize_input_messages` rejects canonical external system/developer roles;
only `AUTH_SOURCE_INTERNAL` run input may retain them.

## Development Workflow

### Test-Driven Development (TDD) — MANDATORY

**Every new feature or bug fix MUST be accompanied by unit tests. No exceptions.**

- Write tests in `backend/tests/` following the existing naming convention `test_<feature>.py`
- Run both offline targets before and after your change: `make test` and `make test-blocking-io`
- Tests must pass before a feature is considered complete
- For lightweight config/utility modules, prefer pure unit tests with no external dependencies
- If a module causes circular import issues in tests, add a `sys.modules` mock in `tests/conftest.py` (see existing example for `deerflow.subagents.executor`)

```bash
# Four duration-balanced offline shards
make test

# Run strict blocking-I/O tests
make test-blocking-io

# Live API tests: require config.yaml, credentials, and explicit opt-in
make test-live

# Run a specific test file
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

Keep live tests opt-in via `DEER_FLOW_RUN_LIVE_TESTS=1`; guard POSIX-only
markers with `os.name` for Windows collection.

Jina logging tests use dummy keys (`tests/test_jina_client.py`).
Jina/Browserless/InfoQuest resolve URLs without rebuilding HTML.
InfoQuest connect/read timeout is 30s, separate from crawl timeouts (`tests/test_infoquest_http_timeout.py`).

### Running the Full Application

Run `make dev` from the repo root to start all services at `http://localhost:2026`.

**All startup modes:**

| | **Local Foreground** | **Local Daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |

| Action | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Stop** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Restart** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

**Nginx routing**:
- `/api/langgraph/*` → Gateway embedded runtime (8001), rewritten to `/api/*`
- `/api/*` (other) → Gateway API (8001)
- `/` (non-API) → Frontend (3000)

### Running Backend Services Separately

From the **backend** directory:

```bash
# Gateway API
make gateway
```

Direct access (without nginx):
- Gateway: `http://localhost:8001`

### Frontend Configuration

The frontend uses environment variables to connect to backend services:
- `NEXT_PUBLIC_LANGGRAPH_BASE_URL` - Defaults to `/api/langgraph` (through nginx)
- `NEXT_PUBLIC_BACKEND_BASE_URL` - Defaults to empty string (through nginx)

When using `make dev` from root, the frontend automatically connects through nginx.

## Key Features

### Web Search Recency

Optional `web_search` `time_range=day|week|month|year` mappings:
DDG → `d|w|m|y`; Brave → `pd|pw|pm|py`; Tavily/SearXNG → unchanged;
Sofya → unchanged in `freshness`; Serper → `qdr:d|w|m|y` in `tbs`.
Omission preserves request shape; Serper null also omits `tbs`. Image search is unchanged.
DDGS 9.14.1 recency uses only enabled Brave/DuckDuckGo/Yahoo engines honoring
`timelimit`: `auto`/`all` selects this set; drop incompatible engines and fall back
to this set if empty. Re-check on DDGS upgrades.

Tavily titles fall back to result URL, then request URL.

### File Upload

Outlines use ATX syntax (1–6 hashes, space/tab separator, ≤3 leading spaces), strip closing hashes and skip fenced code.
- Endpoint: `POST /api/threads/{thread_id}/uploads`
- Supports: PDF, PPT, Excel, Word documents (converted via `markitdown`)
- Rejects directories before copying to keep uploads all-or-nothing
- One conversion worker per request when called from an active event loop
- Files stored in thread-isolated directories under the resolving user's bucket (`users/{user_id}/threads/{thread_id}/user-data/uploads`). For IM channels the owner is threaded explicitly via the `user_id=` kwarg (see IM Channels → Owner-scoped file storage); HTTP/embedded callers resolve it from `get_effective_user_id()`
- Per-thread `upload-companions/`: source mtime/ctime.
- Duplicate filenames within one request get `_N` suffixes to prevent overwrites.
- Gateway HTTP uploads stage `.upload-*.part` files, hidden from upload listings, agent context, and sandbox listings/searches. After size validation, publication is atomic; staged-name cleanup logs errors and leaves leftovers for startup sweep. The sweep keeps lone `.part` files under 24h: they may be in flight on another replica; `st_nlink > 1` means a published alias, removed at any age so the multi-link check can still replace the file.
- Gateway HTTP upload/list/delete handlers offload filesystem work through `deerflow.utils.file_io.run_file_io`, a dedicated ContextVar-preserving file IO executor. Non-mounted sandbox uploads acquire sandboxes with `SandboxProvider.acquire_async()` and offload `read_bytes()` plus `sandbox.update_file()` together.
- Mounted uploads skip sandbox acquire/sync. AIO remote/provisioner requires accurate `sandbox.thread_data_mounts: true`; omission keeps backend auto-detection.
- `UploadsMiddleware` caps outline titles at 200 characters and previews at 2000 including markers. Titles use `original_user_content`, not upload-prefixed content; attachment-only titles use a sanitized, bounded filename or count.

[Upload details](docs/FILE_UPLOAD.md).

### Plan Mode

`config.configurable.is_plan_mode=True` enables TodoList `write_todos` for
multi-step tasks: one `in_progress` task, real-time updates. See
[usage](docs/plan_mode_usage.md).

### Run Interaction Policy

Interaction-sensitive changes must follow [policy](docs/RUN_INTERACTION_POLICY.md).

### Context Summarization

Automatic conversation summarization when approaching token limits:
- Configured in `config.yaml` under `summarization` key
- Trigger types: tokens, messages, or fraction of max input
- Keeps recent messages while summarizing older ones
- Manual compaction uses `POST /api/threads/{id}/compact`, reuses the same
  `DeerFlowSummarizationMiddleware`, writes a new checkpoint with updated
  `messages` and `summary_text`, and bumps only those channel versions.
  The route uses the shared `reserve_checkpoint_write()` boundary (also used by
  manual state updates). Its short-lived `checkpoint_write` thread operation
  shares the durable active-thread uniqueness constraint with run admission,
  preventing either worker-local or cross-worker checkpoint-write races.
- Cache only first-candidate no-ops; never suppress primary retries with fallback results. See [reuse and telemetry](docs/summarization.md#reuse-and-telemetry) for cache and counter contracts.

### Vision Support

Models with supports_vision enable ViewImageMiddleware/view_image_tool. Base64 payloads require both server-owned marker and reserved ID; Gateway strips untrusted markers. Inject only inside wrap_model_call, never graph state/checkpoints; persist lightweight metadata, preserve client IDs and sweep stranded payloads before rebuilding. See [middleware guide](packages/harness/deerflow/agents/middlewares/AGENTS.md).

## Code Style

- Uses `ruff` for linting and formatting
- Line length: 240 characters
- Python 3.12+ with type hints
- Double quotes, space indentation

## Documentation

Module documentation:
- [CONFIGURATION.md](docs/CONFIGURATION.md) - Configuration options
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - Architecture details
- [API.md](docs/API.md) - API reference
- [SETUP.md](docs/SETUP.md) - Setup guide
- [FILE_UPLOAD.md](docs/FILE_UPLOAD.md) - File upload feature
- [PATH_EXAMPLES.md](docs/PATH_EXAMPLES.md) - Path types and usage
- [summarization.md](docs/summarization.md) - Context summarization
- [plan_mode_usage.md](docs/plan_mode_usage.md) - Plan mode with TodoList

Task6A isolates private executor migrations from native persistence. Production
B/central require an already-compatible executor schema; outbound workers validate
the same revision over credential-authenticated transport. Gateway checks preserved
legacy Fleet intent immediately after native DB initialization, before checkpoint,
recovery and scheduler activation. A schema upgrade is not permission to replay old
intent. Inventory/disposition and stopped-writer rollback are documented in
`docs/ecs-native-fork-integration.md`; cloud/ops gates remain separate.

Task6B native role Compose, private reference-only generation, durable operator drain
and stopped-writer image selection are documented in `docs/ecs-native-deployment.md`. Installed/cloud acceptance is separately recorded in
`docs/ecs-native-shanghai-resume-2026-10-10.md`. The current Shanghai run accepts
B/C/BC, worker CLI/controller Compose lifecycle and native browser HTTP/WSS
control and same-schema compatible rollback (#48). OS reboot recovery and final
cold artifacts remain separate gates. Use the owned Jenkins test job; do not run Docker/runtime tests locally.

Native ECS publication keeps staging private, then makes only the completed job output tree readable (0755 directories / non-executable 0644 files) through pinned no-follow descriptors before atomic rename. This matches native per-thread sandbox mounts across UIDs; owner/incarnation locks and artifact API checks remain authoritative. Executor pool data, tenant ancestors and existing publications are unchanged. Regression: `tests/test_ecs_native_publication_permissions.py` requires the owned Linux root test container to verify an actual non-root reader.


Runtime artifact MIME lookup requires the system `media-types` table even on a slim image; `backend/Dockerfile` installs it in the runtime stage over HTTPS. Preserve native active-content attachment handling instead of relaxing MIME/security assertions when that table is absent. Full offline backend CI also needs a Git executable and real repository metadata for benchmark identity checks. Archive-based isolated fixtures may initialize a new repository from verified public bytes, but must identify its commit as synthetic fixture metadata, retain the original source/overlay hashes, and never copy private Git credentials/history. Git is a test-image dependency; adding it to CI must not silently add it to production role images.


Native ECS cloud CI note: trusted repository regression fixtures require Git and make and the extension-manager source-install tests require package-index access and their own loopback Git/index servers. Keep Git/make in the test-only image. Invoke `/app/backend/.venv/bin/python -m pytest` and `/app/backend/.venv/bin/ruff` directly. Remove inherited `UV_PROJECT_ENVIRONMENT` and `UV_OFFLINE`. Give the frozen source backend an independent byte copy of the installed venv (no shared writable packages); `UV_NO_SYNC=1` keeps ordinary `uv run` on that installed checkout. ExtensionManager strips the selector and no-sync keys for its installs; direct extension-test `uv sync` must target its own temporary project. Check selected base-package metadata afterward to detect damage to the fixed top-level environment. A CI Docker bridge may provide dependency transport while mounting only reviewed public test source; no credentials, env files, Docker socket, NAS/database data or published ports belong in that fixture. This CI transport does not change ordinary B sandbox network-none isolation or production dependencies. Full-collection tests must select the already-loaded backend conftest plugin by exact path when checking its hooks; bare `import conftest` can resolve a nested test plugin.


M4 transport preparation: `ecs_executor.scope` supports explicit version-2
submission scopes carrying trusted `WorkspaceContext`. Verification requires a
separately authorized expected context, rejects legacy downgrade, and refuses
scoped tokens for callers without that expectation. This is a signing primitive
only: native Run/MCP/Scheduler/executor wiring and live authorization remain
required; do not enable workspace startup based on these transport tests.


M4 native Run identity preparation uses runs.workspace_context_json plus
thread_incarnation (0039) under the existing private admission lock. RunManager
preserves and validates that snapshot, including local idempotency rechecks;
legacy create/upsert refuse workspace authority. This now includes scoped normal Run reject admission, pending transitions
and deterministic native worker execution, as documented in the runtime guide.
Remote transport, leases, terminal publication and full worker lifecycle remain
pending. Workspace startup remains closed until the whole runtime and release
plan is verified. See persistence/runtime guides and tenant migration docs.


M4 MCP metadata/driver foundation: scoped native task requests/references retain
the source Run's immutable workspace; source execution owner is copied from a
server-owned runtime key. SQL validates source/current membership/nonce before
and after remote submission and before polling/result commit. Native schema is
now 0040; independent executor schema is e0003. Scoped submit signing uses v2
without legacy fallback. The B HTTP component verifies native source/task/live
member receipts for submission and management; scoped control queues, physical
execution/publication and full tenant activation remain pending.

The executor's `verify_native_execution_scope` is a read-only SQL submission
preflight. It verifies cryptographic intent before native lookup, reuses native
membership/account policy and checks the original running Run/private parent and
snapshot. It is not a durable physical start/publication grant. Opt-in scoped B
HTTP submission and v2 management now verify original native MCP commitment and
snapshot identity. Scoped single-host B physically executes with native authority
fences; default store/pool scoped claims remain closed.
Never enable the tenant startup gate on this component evidence.

Executor schema `e0003_execution_identity` appends a nullable immutable B intent
snapshot/hash. Native ownership attribution leaves it NULL; it does not create a
launch grant. JobStore validates captured identity on reads/mutations/retries.
Default JobStore and pool queued claims exclude workspace-attributed jobs;
scoped single-host B claims via ExecutionJobs native authority. Pool filtering
precedes limit. All old processes must stop before offline upgrade.
Do not interpret this schema floor or HTTP management as completed scoped B/C
physical launch/publication, native cancellation delivery or tenant activation.

Scoped B receiver configuration is operator-only (`workspace_required` plus exact
`native_server_name`); it requires native 0040/executor e0003, and existing native
team data refuses legacy receiver startup. Native `mcp_tasks` remains lifecycle
authority: B reads its committed remote/server/source/private-parent snapshot for
authorization only. The normal task-local service binding signs v2 management
without making up a live Run. Native cancel/notification queues remain withheld;
remote cancellation of an unstarted B job is not physical STOP acceptance.
Staging expiry only mutates staged rows and leaves unknown history/reservations
untouched. Scoped file snapshots/publication recheck live scope under native
workspace/actor/private-parent locks. Full physical start/adopt/result/control
and M0-M11 evidence are still required; activation stays compiled false.

Scoped single-host B now uses NativeSubmissionAuthority.fence around short
claim/start-intent/result SQL writes, locking workspace -> actor -> private
parent -> source Run -> native task. Docker/HTTP is outside that transaction.
The worker authorizes before start/reconcile/publication and persists a control
stop request on observed withdrawal; cleanup only uses captured ownership and
physical inspection, never a withdrawn business grant. Native file publication
rechecks active task/cancel state under native scope/parent locks before writes.
No automatic start replay or STOP/capacity inference from failed inspection.
Pool scoped claims stay closed. Native outbox/task control settlement and remote
C/full lifecycle remain required; Gateway activation remains compiled false.
Reproduction and exact limits: ../docs/tenant-workspaces-testing.md.


Scoped native C sandbox cancellation uses execution-local captures bound to the
SQL-adopted Run before task creation. AIO acquire/identity-checked reuse captures
immutable physical IDs across warm release; STOP never recalculates IDs from a
mutable workspace or skills projection. Captured teardown retains native provider
ownership/lease fences and refuses unknown outcomes. A drained task that never
entered acquisition can prove text-only NoStart; failed/in-flight acquisition
cannot. Captures are private in-memory receipts: restart without them retains
reservations. Cloud AIO lifecycle acceptance and tenant activation remain separate.

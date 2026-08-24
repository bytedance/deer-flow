# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with code in this repository. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

## Project Overview

DeerFlow is a LangGraph-based AI super agent system with a full-stack architecture. The backend provides a "super agent" with sandbox execution, persistent memory, subagent delegation, and extensible tool integration - all operating in per-thread isolated environments.

**Architecture**:
- **Gateway API** (port 8001): REST API plus embedded LangGraph-compatible agent runtime
- **Frontend** (port 3000): Next.js web interface
- **Nginx** (port 2026): Unified reverse proxy entry point
- **Provisioner** (port 8002, optional in Docker dev): Started only when sandbox is configured for provisioner/Kubernetes mode

**Runtime**:
- `make dev`, Docker dev, and production all run the agent runtime in Gateway via `RunManager` + `run_agent()` + `StreamBridge` (`packages/harness/deerflow/runtime/`). Nginx exposes that runtime at `/api/langgraph/*` and rewrites it to Gateway's native `/api/*` routers.
- Gateway streams `write_file` and `str_replace` argument deltas in bounded batches when clients also subscribe to `values`; messages-only consumers retain the original per-chunk contract, while `values` preserves the complete tool call.
- With `stream_subgraphs`, subgraph frames keep their namespace in the SSE event name (`values|<ns>`, LangGraph Platform style) instead of impersonating root frames — a delegated subagent inherits the parent checkpoint namespace, so publishing its `values` snapshot as bare `values` replaces the whole thread view in SDK clients (#4399). Root-only consumers (file-tool chunk batcher, subagent event persistence, LLM error-fallback detection) ignore namespaced frames. The web frontend does not request subgraph streaming; subtask progress rides root-namespace `task_*` custom events.
- Background subagent identity is deliberately split: the provider `tool_call_id` remains the correlation key for `ToolMessage`, `task_*` SSE events, persisted lifecycle events, frontend cards, and the public `ExtensionData.scope_id` contract (stored as `SubagentResult.external_task_id`), while `SubagentExecutor.execute_async()` generates a full server-side `execution_id` for `SubagentResult.task_id`, the process-wide registry, polling, cancellation, timeout handling, and cleanup. Provider IDs are not globally unique across parent runs, so they must never become registry ownership keys; scheduler closures retain their own `SubagentResult` rather than resolving ownership again through the mutable registry. Terminal subagent token usage travels in the current run's `ToolMessage.additional_kwargs` and is attributed from message state, never through a process-global provider-ID cache.
- Scheduled-task executions must reuse that same Gateway run lifecycle. The scheduler may decide *when* work runs, but it must dispatch through the existing run path rather than introducing a parallel execution stack. Scheduled launches pass `scheduler.recursion_limit` (default 1000, matching the web UI's `recursion_limit: 1000`, clamped by `max_recursion_limit`) via `launch_scheduled_thread_run`; the value is read from `get_app_config()` at dispatch.
- The background scheduler is single-instance by default. `scheduler.multi_instance=true` opts into lease-aware recovery across Gateway instances and requires shared Postgres, `run_ownership.heartbeat_enabled=true`, and `run_events.backend=db`; otherwise startup rejects the configuration. Live scheduled runs are preserved when a peer starts; expired launch claims return to the durable queue, expired run leases are atomically taken over, stale launch writes are fenced by lease ownership, and the Postgres advisory-locked budget makes `max_concurrent_runs` a shared global cap for `launching`/`running` rows.
- Long-running MCP work uses a separate durable task runtime rather than keeping remote task IDs or status polling inside the Agent loop. Explicit `task_toolsets` bind raw submit/status/cancel names; only submit remains Agent-visible, and its wrapper persists the remote handle before returning a local ID. `McpTaskService` claims due rows with leases, resolves a protocol-specific `McpTaskDriver`, and writes normalized snapshots back to `mcp_tasks`; expired leases are the restart-recovery mechanism, and a result returned after expiry or after a cancel request must be discarded even when the owner token still matches. The first cancel request fences an in-flight poll lease, while repeats preserve an active cancellation lease so they cannot issue concurrent remote cancels; cancellation backoff starts when the remote attempt finishes, so a slow timeout cannot consume the retry delay. Cancellation, polling, and notification batches isolate per-task exceptions; an unexpected cancellation/poll failure leaves that record's lease to expire, while notification failures release only the affected lease for retry. Input-required and terminal event snapshots are delivered by idempotent Agent runs and marked delivered only after run success; the trusted notification instruction stays outside the input boundary while the serialized remote event is framed as untrusted data. A busy-thread conflict is normalized back to the service boundary so the queued snapshot coalesces to the latest task event. A missing dispatched run becomes a failed delivery attempt, while transient run-store hydration errors stay distinguishable and retry the same lookup. The database is the source of truth; `ThreadState` receives only a bounded current-thread projection, and display names are neutralized at that model-state boundary. The installed process-local submitter is the source of truth for management-tool exposure; hot `mcp_tasks` edits take effect only after restart, and active skills must explicitly declare the list/cancel business tools.
- MCP notification failures use a consecutive counter separate from the idempotency-key `dispatch_attempt`, capped exponential backoff, latest-event rebuilding before a run launches, and a five-attempt budget before `dead_letter`. A permanently missing/mismatched target thread is dead-lettered immediately instead of being recreated or reclaimed. HTTP and Agent cancellation requests return after the durable cancel fence; the background loop alone owns the potentially slow remote call and retry schedule. The HTTP cancel endpoint rejects requests with 503 when the loop is not running (`mcp_tasks_available` false, e.g. `mcp_tasks.enabled=false` with SQL persistence), so a cancellation is never acknowledged without a worker to perform it. The bounded notification error/count/status join poll and cancellation diagnostics in the task detail API and expanded card.
- Scheduled-task dispatch enforces at most one non-terminal occurrence per task through `uq_scheduled_task_run_active` (`task_id WHERE status IN ('queued','launching','running')`). `queued` is durable and survives restart; `launching` carries a short owner/expiry lease and is the only state that may call the normal Gateway launch path; `running` is associated with the durable run. Each occurrence also supplies a stable run-admission idempotency key, so a recovered launch retry reuses the same durable run. A reused-thread `ConflictError` moves `launching` back to `queued`, while non-conflict launch errors become terminal `failed`. Waiting rows do not consume `max_concurrent_runs`; the atomic queue claim enforces the budget. Repeated triggers coalesce on the one active row, and same-thread FIFO treats older `queued`, `launching`, and `running` rows as blockers. The task definition stays immutable for all three active states because queue admission, PATCH/resume, pause, and delete serialize on the parent task row before touching the occurrence row. Pause/delete atomically interrupt existing `queued` rows and reject `launching`/`running` rows; PATCH/resume reject every active state, and mutation errors advertise pause cancellation only for `queued` work. A manual trigger may queue and run while the parent schedule remains paused. Recovery and multi-instance reconciliation lock task/run pairs in deterministic task-id/run-id order and must reconstruct `run_id`, `started_at`, and the live error state before releasing the short launch claim. Launch/failure/timeout bookkeeping changes the occurrence and its parent task in one parent-first transaction so a peer cannot claim the released task between those writes. Queue timeout marks the occurrence failed and advances a scheduled occurrence so it cannot immediately requeue forever; repository write boundaries coerce serialized task timestamps before binding SQL `DateTime` fields.
- `extensions_config.json` is written at runtime by the Gateway (`PUT`/`PATCH /api/mcp/config`, the MCP enable switch, skill updates), so the production compose mounts it read-write while `config.yaml` stays `:ro`; Helm copies its ConfigMap seed into a writable home-volume directory before Gateway starts. Every read-modify-write holds both `extensions_config_write_lock` and the sidecar advisory `extensions_config_file_lock`, because the process-local lock alone loses updates across workers. Docker mounts the compose file as its own mount point, and Linux refuses `rename()` over a mount point with `EBUSY` even when the mount is writable — so `atomic_write_extensions_config` keeps the temp-file-plus-rename path and falls back to an in-place overwrite only on `EBUSY`. That fallback is deliberately non-atomic (a crash mid-write truncates the file); it exists because the alternative is a write that can never succeed, and only its first occurrence per target is logged at warning level. Any other `errno` still propagates. Pinned by `tests/test_compose_extensions_config_writable.py`, `tests/test_extensions_config_atomic_write.py`, and `tests/test_helm_extensions_config_writable.py`.

**Project Structure**:
```
deer-flow/
├── Makefile                    # Root commands (check, install, dev, stop)
├── config.yaml                 # Main application configuration
├── extensions_config.json      # MCP servers and skills configuration
├── backend/                    # Backend application (this directory)
│   ├── Makefile               # Backend-only commands (dev, gateway, lint)
│   ├── langgraph.json         # LangGraph Studio graph configuration
│   ├── packages/
│   │   ├── extension-api/     # public, host-independent extension contracts (import: deerflow_extension_api.*)
│   │   └── harness/           # deerflow-harness package (import: deerflow.*)
│   │       ├── pyproject.toml
│   │       └── deerflow/
│   │           ├── agents/            # LangGraph agent system
│   │           │   ├── lead_agent/    # Main agent (factory + system prompt)
│   │           │   ├── middlewares/   # middleware components (see Middleware Chain section)
│   │           │   ├── memory/        # Memory extraction, queue, prompts
│   │           │   └── thread_state.py # ThreadState schema
│   │           ├── sandbox/           # Sandbox execution system
│   │           │   ├── local/         # Local filesystem provider
│   │           │   ├── sandbox.py     # Abstract Sandbox interface
│   │           │   ├── tools.py       # bash, ls, read/write/str_replace
│   │           │   └── middleware.py  # Sandbox lifecycle management
│   │           ├── subagents/         # Subagent delegation system
│   │           │   ├── builtins/      # general-purpose, bash agents
│   │           │   ├── executor.py    # Background execution engine
│   │           │   └── registry.py    # Agent registry
│   │           ├── tools/builtins/    # Built-in tools (present_files, ask_clarification, view_image, review_skill_package)
│   │           ├── mcp/               # MCP integration (tools, cache, client)
│   │           ├── integrations/      # Managed first-party integration installers (e.g. Lark CLI skill pack)
│   │           ├── extensions/        # Python plugin loader, registry, placement, and isolation
│   │           ├── models/            # Model factory with thinking/vision support
│   │           ├── skills/            # Skills discovery, loading, parsing
│   │           ├── config/            # Configuration system (app, model, sandbox, tool, etc.)
│   │           ├── community/         # Community tools (search/fetch/scrape, image search, AIO sandbox)
│   │           ├── reflection/        # Dynamic module loading (resolve_variable, resolve_class)
│   │           ├── utils/             # Utilities (network, readability)
│   │           └── client.py          # Embedded Python client (DeerFlowClient)
│   ├── app/                   # Application layer (import: app.*)
│   │   ├── gateway/           # FastAPI Gateway API
│   │   │   ├── app.py         # FastAPI application
│   │   │   └── routers/       # FastAPI route modules (models, mcp, memory, skills, uploads, threads, artifacts, agents, suggestions, channels)
│   │   └── channels/          # IM platform integrations
│   ├── tests/                 # Test suite
│   └── docs/                  # Documentation
├── frontend/                   # Next.js frontend application
└── skills/                     # Agent skills directory
    ├── public/                # Public skills (committed)
    └── custom/                # Custom skills (gitignored)
```

## Important Development Guidelines

### Documentation Update Policy
**CRITICAL: Always update README.md and AGENTS.md after every code change**

When making code changes, you MUST update the relevant documentation:
- Update `README.md` for user-facing changes (features, setup, usage instructions)
- Update `AGENTS.md` for development changes (architecture, commands, workflows, internal systems). `CLAUDE.md` imports it via `@AGENTS.md`, so editing `AGENTS.md` updates both.
- Keep documentation synchronized with the codebase at all times
- Ensure accuracy and timeliness of all documentation

## Commands

**Root directory** (for full application):
```bash
make check      # Check system requirements
make install    # Install all dependencies (frontend + backend)
make extension-install SOURCE=...  # Install and enable a trusted Python extension
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
make dev                # Run Gateway API with runtime-safe reload (port 8001)
make gateway            # Run Gateway API only (port 8001)
make test               # Run offline backend tests (excludes live external-API tests)
make test-live          # Explicitly run live DeerFlowClient tests with real APIs
make test-blocking-io   # Run strict Blockbuster runtime gate on tests/blocking_io/
make lint               # Lint with ruff
make format             # Format code with ruff
make migrate-rev MSG="..."  # Autogenerate a new alembic revision (see Schema Migrations section)
```

The backend `make dev` target pre-creates and excludes `DEER_FLOW_HOME`
(default: `backend/.deer-flow`) and `backend/sandbox` from Uvicorn's reload
watcher. Do not replace it with a bare `uvicorn --reload`: agent tasks write
Python and other runtime files below `DEER_FLOW_HOME`, which would otherwise
restart the Gateway during an active run.

More specific `AGENTS.md` files in backend code directories contain the subsystem sections split from this file. Follow the nearest file in the directory tree.

## Architecture

### Harness / App Split

The backend is split into two layers with a strict dependency direction:

- **Harness** (`packages/harness/deerflow/`): Publishable agent framework package (`deerflow-harness`). Import prefix: `deerflow.*`. Contains agent orchestration, tools, sandbox, models, MCP, skills, config — everything needed to build and run agents.
- **App** (`app/`): Unpublished application code. Import prefix: `app.*`. Contains the FastAPI Gateway API and IM channel integrations (Feishu, Slack, Telegram, DingTalk).

**Dependency rule**: App imports deerflow, but deerflow never imports app. This boundary is enforced by `tests/test_harness_boundary.py` which runs in CI.

**Import conventions**:
```python
# Harness internal
from deerflow.agents import make_lead_agent
from deerflow.models import create_chat_model

# App internal
from app.gateway.app import app
from app.channels.service import start_channel_service

# App → Harness (allowed)
from deerflow.config import get_app_config

# Harness → App (FORBIDDEN — enforced by test_harness_boundary.py)
# from app.gateway.routers.uploads import ...  # ← will fail CI
```

Package import hygiene: the `deerflow.agents` and `deerflow.subagents` package
roots expose heavyweight graph/executor entrypoints lazily. The
`deerflow.agents:make_lead_agent` LangGraph Server entrypoint is a concrete thin
module-level function because the server resolves graph factories directly from
the module dictionary; the wrapper keeps the lead-agent and skill-cache imports
inside the function so importing the package remains lightweight. Internal
modules that only need lightweight types, config, or registries should import
the concrete submodule instead of adding eager package-root imports that pull in
the tool graph or subagent executor during state/schema imports.

## Development Workflow

### Test-Driven Development (TDD) — MANDATORY

**Every new feature or bug fix MUST be accompanied by unit tests. No exceptions.**

- Write tests in `backend/tests/` following the existing naming convention `test_<feature>.py`
- Run the full offline suite before and after your change: `make test`
- Tests must pass before a feature is considered complete
- For lightweight config/utility modules, prefer pure unit tests with no external dependencies
- If a module causes circular import issues in tests, add a `sys.modules` mock in `tests/conftest.py` (see existing example for `deerflow.subagents.executor`)

```bash
# Run all offline tests
make test

# Explicit live integration tests (requires config.yaml and credentials;
# calls real APIs and may create local side effects)
make test-live

# Run a specific test file
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

Direct pytest collection or execution of `tests/test_client_live.py` remains
skipped unless `DEER_FLOW_RUN_LIVE_TESTS=1` is set. Do not add that opt-in to
default CI workflows.

### Running the Full Application

From the **project root** directory:
```bash
make dev
```

This starts all services and makes the application available at `http://localhost:2026`.

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

### File Upload

Multi-file upload with automatic document conversion:
- Endpoint: `POST /api/threads/{thread_id}/uploads`
- Supports: PDF, PPT, Excel, Word documents (converted via `markitdown`)
- Rejects directory inputs before copying so uploads stay all-or-nothing
- Reuses one conversion worker per request when called from an active event loop
- Files stored in thread-isolated directories under the resolving user's bucket (`users/{user_id}/threads/{thread_id}/user-data/uploads`). For IM channels the owner is threaded explicitly via the `user_id=` kwarg (see IM Channels → Owner-scoped file storage); HTTP/embedded callers resolve it from `get_effective_user_id()`
- Duplicate filenames in a single upload request are auto-renamed with `_N` suffixes so later files do not truncate earlier files
- Gateway HTTP uploads stage bytes as `.upload-*.part` files and atomically replace the destination only after size validation. These staging files are hidden from upload listings, agent upload context, and sandbox listing/search tools, and swept on Gateway startup if a hard crash leaves one behind.
- Gateway HTTP upload/list/delete handlers offload filesystem work through `deerflow.utils.file_io.run_file_io`, a dedicated ContextVar-preserving file IO executor. Non-mounted sandbox uploads acquire sandboxes with `SandboxProvider.acquire_async()` and offload `read_bytes()` plus `sandbox.update_file()` together.
- Mounted upload paths skip both sandbox acquisition and per-file synchronization. For AIO remote/provisioner deployments this requires an explicit, accurate `sandbox.thread_data_mounts: true`; omission preserves backend auto-detection.
- Agent receives uploaded file list via `UploadsMiddleware`

See [docs/FILE_UPLOAD.md](docs/FILE_UPLOAD.md) for details.

### Plan Mode

TodoList middleware for complex multi-step tasks:
- Controlled via runtime config: `config.configurable.is_plan_mode = True`
- Provides `write_todos` tool for task tracking
- One task in_progress at a time, real-time updates

See [docs/plan_mode_usage.md](docs/plan_mode_usage.md) for details.

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

See [docs/summarization.md](docs/summarization.md) for details.

### Vision Support

For models with `supports_vision: true`:
- `ViewImageMiddleware` processes images in conversation
- `view_image_tool` added to agent's toolset
- Images are converted to base64 and injected into a hidden message carrying both a reserved ID prefix and a server-owned metadata marker for the model call; Gateway strips that marker from untrusted input, and the middleware requires both identifiers before removing the message. The `before_model` and `model` node checkpoints for that call still contain the payload; after `after_model` cleanup, subsequent checkpoints retain only lightweight `viewed_images` metadata, while client-chosen IDs survive

## Code Style

- Uses `ruff` for linting and formatting
- Line length: 240 characters
- Python 3.12+ with type hints
- Double quotes, space indentation

## Documentation

See `docs/` directory for detailed documentation:
- [CONFIGURATION.md](docs/CONFIGURATION.md) - Configuration options
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - Architecture details
- [API.md](docs/API.md) - API reference
- [SETUP.md](docs/SETUP.md) - Setup guide
- [FILE_UPLOAD.md](docs/FILE_UPLOAD.md) - File upload feature
- [PATH_EXAMPLES.md](docs/PATH_EXAMPLES.md) - Path types and usage
- [summarization.md](docs/summarization.md) - Context summarization
- [plan_mode_usage.md](docs/plan_mode_usage.md) - Plan mode with TodoList

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

- Gateway owns the embedded agent runtime through `RunManager`, `run_agent()`,
  and `StreamBridge`; Nginx exposes it at `/api/langgraph/*`.
- Scheduled tasks reuse the normal Gateway run lifecycle. Database constraints,
  not process-local prechecks, are the final arbiter for overlap prevention.
- Long-running MCP work uses the durable MCP task runtime; recoverable task state
  must not live only in `ThreadState`.
- For lifecycle, streaming, scheduler, and MCP details, use the subsystem index
  below instead of adding implementation narratives here.

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
│   │           │   ├── middlewares/   # middleware components (see [docs/MIDDLEWARE_CHAIN.md](docs/MIDDLEWARE_CHAIN.md))
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

**Doc updates travel with the change that made them necessary** — a PR that
changes behavior updates the doc describing that behavior, in the same change set.

- `README.md` — user-facing changes (features, setup, usage).
- `AGENTS.md` — **orientation layer only**: public repo structure, commands,
  cross-cutting conventions, hard architectural constraints (e.g. the
  harness/app import boundary), and the subsystem index. Update it only when
  those change.
- Subsystem internals — go in `backend/docs/<SUBSYSTEM>.md` (see the index
  below), **not** in this AGENTS.md.
- Guidance budgets and validation are defined in the root `AGENTS.md`; run
  `make check-agent-guidance` from the repository root.

## Commands

**Root directory** (for full application):
```bash
make check      # Check system requirements
make install    # Install all dependencies (frontend + backend)
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
make migrate-rev MSG="..."  # Autogenerate a new alembic revision (see [docs/SCHEMA_MIGRATIONS.md](docs/SCHEMA_MIGRATIONS.md))
```

The backend `make dev` target pre-creates and excludes `DEER_FLOW_HOME`
(default: `backend/.deer-flow`) and `backend/sandbox` from Uvicorn's reload
watcher. Do not replace it with a bare `uvicorn --reload`: agent tasks write
Python and other runtime files below `DEER_FLOW_HOME`, which would otherwise
restart the Gateway during an active run.

Deep documentation for the executor and blocking-io detection tooling lives in
[docs/THREAD_BOUNDARY_DETECTION.md](docs/THREAD_BOUNDARY_DETECTION.md) and
[docs/BLOCKING_IO_DETECTION.md](docs/BLOCKING_IO_DETECTION.md).

Boundary check (harness → app import firewall):
- `tests/test_harness_boundary.py` — ensures `packages/harness/deerflow/` never imports from `app.*`

Memory backend async boundary:
- `MemoryMiddleware.aafter_agent` calls `MemoryManager.aadd`; network-backed
  managers must override their `a*` methods to offload or use native async I/O.
- The mem0 backend requires an HTTPS `base_url` by default because requests
  carry an API token. Plain HTTP requires the explicit
  `backend_config.allow_insecure_http: true` local-development opt-in.
- Gateway memory routes offload the synchronous management contract with
  `asyncio.to_thread`, so backend file or HTTP I/O does not run on the ASGI
  event loop. Gateway startup and shutdown also resolve the manager off-loop,
  because a backend's `from_config` may perform a fail-fast connectivity check.
- A backend may set `requires_passive_writes_in_tool_mode = True` when tool-mode
  search is supported but durable writes still depend on conversation-level
  extraction. Such backends receive memory tools and retain `MemoryMiddleware`.
- Prompt recall rethrows `MemoryManagerError` only when backend config declares
  `failure_policy.read: fail_closed`; other recall errors preserve the existing
  log-and-empty-context behavior.

CI runs these regression tests for every pull request via [.github/workflows/backend-unit-tests.yml](../.github/workflows/backend-unit-tests.yml).

Agentic browser sessions are process-local. The Gateway startup safety gate rejects
`GATEWAY_WORKERS > 1` when `browser_navigate` is configured, because ordinary
uvicorn worker dispatch does not provide thread affinity for browser tools, REST
navigation, and the Live WebSocket.

Browser Live screenshots remain JPEG bytes inside the harness and the Gateway's
bounded, drop-oldest frame queue. WebSocket clients that request
`frame_format=binary` receive binary messages; control metadata remains JSON.
The legacy no-parameter protocol still base64-encodes frames into JSON at the
Gateway boundary for backward compatibility. Unknown `frame_format` values
receive a JSON error and close code 1008.

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
roots expose heavyweight graph/executor entrypoints lazily. Internal modules
that only need lightweight types, config, or registries should import the
concrete submodule instead of adding eager package-root imports that pull in the
tool graph or subagent executor during state/schema imports.

### Agent System

- Entry point: `make_lead_agent(config: RunnableConfig)` registered in `langgraph.json`
- Dynamic model selection via `create_chat_model()` with thinking/vision support
- Full detail (ThreadState schema, runtime config, reducers): see [AGENT_SYSTEM.md](docs/AGENT_SYSTEM.md)

### Reflection System

- `resolve_variable(path)` - Import module and return variable (e.g., `module.path:variable_name`)
- `resolve_class(path, base_class)` - Import and validate class against base class

### Subsystem Index

Subsystem depth lives in `backend/docs/`. Before changing a subsystem, read its guide.

| Subsystem | Code path | Deep docs |
|---|---|---|
| Agent / Lead Agent | `agents/lead_agent/`, `agents/thread_state.py` | [AGENT_SYSTEM.md](docs/AGENT_SYSTEM.md) |
| Middleware chain | `agents/middlewares/` | [MIDDLEWARE_CHAIN.md](docs/MIDDLEWARE_CHAIN.md) |
| Python extension system | `extensions/` | [EXTENSION_SYSTEM.md](docs/EXTENSION_SYSTEM.md) |
| Configuration system | `config/` | [CONFIGURATION_SYSTEM.md](docs/CONFIGURATION_SYSTEM.md) |
| Gateway API | `app/gateway/` | [GATEWAY_API.md](docs/GATEWAY_API.md) |
| Sandbox system | `sandbox/` | [SANDBOX_SYSTEM.md](docs/SANDBOX_SYSTEM.md) |
| Subagent system | `subagents/` | [SUBAGENTS_SYSTEM.md](docs/SUBAGENTS_SYSTEM.md) |
| Tool system | `tools/` | [TOOL_SYSTEM.md](docs/TOOL_SYSTEM.md) |
| MCP system | `mcp/` | [MCP_SYSTEM.md](docs/MCP_SYSTEM.md) |
| Skills system | `skills/` | [SKILLS_SYSTEM.md](docs/SKILLS_SYSTEM.md) |
| Model factory | `models/` | [MODELS.md](docs/MODELS.md) |
| IM channels | `app/channels/` | [IM_CHANNELS.md](docs/IM_CHANNELS.md) |
| Memory system | `agents/memory/` | [MEMORY_SYSTEM.md](docs/MEMORY_SYSTEM.md) |
| Schema migrations | `persistence/migrations/` | [SCHEMA_MIGRATIONS.md](docs/SCHEMA_MIGRATIONS.md) |
| Checkpoint channel modes | `runtime/checkpointer/` | [CHECKPOINT_MODES.md](docs/CHECKPOINT_MODES.md) |
| TUI | `tui/` | [TUI.md](docs/TUI.md) |
| Observability | `tracing/`, `trace_context.py` | [TRACING.md](docs/TRACING.md) |
| Embedded client | `client.py` | [EMBEDDED_CLIENT.md](docs/EMBEDDED_CLIENT.md) |
| File uploads | `app/gateway/routers/uploads.py`, `agents/middlewares/uploads.py` | [FILE_UPLOAD.md](docs/FILE_UPLOAD.md) |
| Context summarization | `agents/middlewares/summarization.py` | [summarization.md](docs/summarization.md) |
| Plan mode | `agents/middlewares/todo_list.py` | [plan_mode_usage.md](docs/plan_mode_usage.md) |
| Executor/blocking-io detection | `scripts/` | [THREAD_BOUNDARY_DETECTION.md](docs/THREAD_BOUNDARY_DETECTION.md), [BLOCKING_IO_DETECTION.md](docs/BLOCKING_IO_DETECTION.md) |

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

## Code Style

- Uses `ruff` for linting and formatting
- Line length: 240 characters
- Python 3.12+ with type hints
- Double quotes, space indentation

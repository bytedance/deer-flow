# AGENTS.md

## Project Overview

The LangGraph backend provides sandbox execution, persistent memory, subagent delegation, and extensible tools, isolated per thread.

Service roles and ports: [root service topology](../AGENTS.md#service-topology).

**Runtime**:
- `make dev`, Docker dev, and production all run the agent runtime in Gateway via `RunManager` + `run_agent()` + `StreamBridge` (`packages/harness/deerflow/runtime/`). Nginx exposes that runtime at `/api/langgraph/*` and rewrites it to Gateway's native `/api/*` routers.
- Scheduled-task lifecycle, recovery and queue timeout: [persistence guide](packages/harness/deerflow/persistence/AGENTS.md#scheduled-task-lifecycle).
- MCP cache reset scope and discovery fencing: [MCP guide](packages/harness/deerflow/mcp/AGENTS.md).

**Where the rules live** — read the guide for the area before you change it:

| Area | Guide |
| --- | --- |
| Run streaming, SSE namespaces, subagent IDs, checkpoints | [runtime](packages/harness/deerflow/runtime/AGENTS.md) |
| Scheduled tasks, durable MCP tasks, leases, thread metadata filters | [persistence](packages/harness/deerflow/persistence/AGENTS.md), [migrations](packages/harness/deerflow/persistence/migrations/AGENTS.md) |
| `config.yaml`, `extensions_config.json` and runtime writes to them | [config](packages/harness/deerflow/config/AGENTS.md) |
| Lead agent, package imports, middleware chain, summarization, vision | [agents](packages/harness/deerflow/agents/AGENTS.md), [middlewares](packages/harness/deerflow/agents/middlewares/AGENTS.md) |
| Memory, subagents, skills, tools, web search | [memory](packages/harness/deerflow/agents/memory/AGENTS.md), [subagents](packages/harness/deerflow/subagents/AGENTS.md), [skills](packages/harness/deerflow/skills/AGENTS.md), [tools](packages/harness/deerflow/tools/AGENTS.md) |
| Sandbox, uploads, MCP, models, extensions | [sandbox](packages/harness/deerflow/sandbox/AGENTS.md), [uploads](packages/harness/deerflow/uploads/AGENTS.md), [mcp](packages/harness/deerflow/mcp/AGENTS.md), [models](packages/harness/deerflow/models/AGENTS.md), [extensions](packages/harness/deerflow/extensions/AGENTS.md) |
| Search, fetch and sandbox providers | `packages/harness/deerflow/community/<provider>/AGENTS.md` |
| Gateway API and routers, IM channels | [gateway](app/gateway/AGENTS.md), [routers](app/gateway/routers/AGENTS.md), [channels](app/channels/AGENTS.md) |
| Tests, benchmarks | [tests](tests/AGENTS.md), [benchmarks](scripts/benchmark/AGENTS.md) |

**Layout:** [Repository map](../AGENTS.md#repository-map). Tests: `tests/`;
docs: `docs/`; benchmarks: `scripts/benchmark/`. Read module-local `AGENTS.md`
for implementation boundaries.

## Important Development Guidelines

### Documentation Update Policy
Keep docs accurate in the same change: user-facing behavior goes in the matching
guide under `docs/guide/` or `backend/docs/`, not in the root `README.md` (an index).
Add to `AGENTS.md` only what the code and commands do not already show.
`CLAUDE.md` imports `AGENTS.md`; do not edit the shim.

Image result URL policy: [image search guide](packages/harness/deerflow/community/image_search/AGENTS.md).

## Commands

Root orchestration and extension commands live in the
[root guide](../AGENTS.md#commands-root-vs-module); run them from the repo root.
`make detect-thread-boundaries` inventories backend executor, thread and event-loop
boundaries.

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

Read the nearest scoped `AGENTS.md` for subsystem ownership.

## Architecture

Read-only knowledge: [contract](docs/KNOWLEDGE.md) covers independent retrieval
tools, scope intersection and extension-owned providers.
HTTPX clients for several community providers, including RAGFlow, LightRAG,
You.com, GroundRoute, Webz, Crawl4AI, Browserless, InfoQuest, Jsonify, SearXNG
and Jina, use `asyncio.to_thread` for synchronous TLS setup; requests and cleanup
stay on-loop, and Browserless and Jsonify own construction as a task so
cancellation during setup still closes the client it builds.

### Harness / App Split

The backend is split into two layers with a strict dependency direction:

- **Harness** (`packages/harness/deerflow/`): Publishable agent framework package (`deerflow-harness`). Import prefix: `deerflow.*`. Contains agent orchestration, tools, sandbox, models, MCP, skills, config — everything needed to build and run agents.
- **App** (`app/`): Unpublished application code. Import prefix: `app.*`. Contains the FastAPI Gateway API and IM channel integrations (Feishu, Slack, Telegram, DingTalk). Feishu option clarifications can render as interactive button cards behind `channels.feishu.card_interaction_enabled` (default off); see `app/channels/AGENTS.md`.

Channel credential staging (`app/channels/credential_staging.py`) is swept on worker-thread state loads, including SQL legacy import. Only owned regular files older than 24h are removed; leave anonymous temporary files alone and keep WeChat constructors IO-free.

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

### Gateway Run-Context Trust Boundary

Gate server-owned run context on both client feeds (`body.context` and
`body.config`): `merge_run_context_overrides` admits it only for `internal=True`,
while `strip_internal_context_keys` scrubs both destinations. A validated
`context.locale` (`en-US` / `zh-CN`) is a runtime-only language preference for
replies and memory writes; it never persists into checkpoint `configurable`,
and an explicit invalid/null top-level value clears a legacy preference. Treat
`disable_clarification` like `non_interactive`. Before run/state writes,
`_normalize_input_messages` rejects canonical external system/developer roles;
only `AUTH_SOURCE_INTERNAL` run input may retain them.
`_normalize_external_todos` rejects invalid caller todos with HTTP 400: entries
must be objects with string content and a known status (default `pending`). Todo
and token-usage readers normalize malformed stored/direct-integration values so
model calls remain usable.

`contracts/ui_locales.v1.json` pins the UI/Gateway locale allowlists in tests;
DeerMem's portable map stays separate. Scheduled/MCP notification runs omit
locale; persisted owner locale is used for scheduled IM notices only.

`start_run` assigns IDs to ID-less messages before recording input or invoking
the graph; keyed retries keep those IDs stable, while the pre-stamp input
remains the idempotency identity. The record and checkpoint share IDs so
frontend reconnect can deduplicate the user's message.

## Development Workflow

### Test-Driven Development (TDD) — MANDATORY

**Every new feature or bug fix MUST be accompanied by unit tests. No exceptions.**

- Write tests in `backend/tests/` following the existing naming convention `test_<feature>.py`
- Run both offline targets before and after your change: `make test` and `make test-blocking-io`
- Tests must pass before a feature is considered complete
- For lightweight config/utility modules, prefer pure unit tests with no external dependencies
- If a module causes circular import issues in tests, add a `sys.modules` mock in `tests/conftest.py` (see existing example for `deerflow.subagents.executor`)

Keep live tests opt-in via `DEER_FLOW_RUN_LIVE_TESTS=1`; guard POSIX-only
markers with `os.name` for Windows collection.

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

File upload: [uploads guide](packages/harness/deerflow/uploads/AGENTS.md) and
[docs/FILE_UPLOAD.md](docs/FILE_UPLOAD.md).

### Plan Mode

`config.configurable.is_plan_mode=True` enables TodoList `write_todos` for
multi-step tasks: one `in_progress` task, real-time updates. See
[usage](docs/plan_mode_usage.md).

### Run Interaction Policy

Interaction/HITL rules: [policy](docs/RUN_INTERACTION_POLICY.md).

### Context Summarization

`summarization` in `config.yaml` triggers on tokens, messages or max-input fraction.
Keep recent messages; summarize older ones.

See [docs/summarization.md](docs/summarization.md) for details.

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

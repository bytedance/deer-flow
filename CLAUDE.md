# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Root directory (full application)

```bash
make config          # First-time setup: generate config.yaml from config.example.yaml (aborts if exists)
make config-upgrade  # Merge new fields from config.example.yaml into existing config.yaml
make check           # Verify Node.js 22+, pnpm, uv, nginx are installed
make install         # Install all dependencies (backend uv sync + frontend pnpm install)
make dev             # Start all services with hot-reload (LangGraph:2024, Gateway:8001, Frontend:3000, Nginx:2026)
make stop            # Stop all running services
make clean           # Stop services and remove backend/.deer-flow, .langgraph_api, logs
```

Service logs during `make dev`: `logs/langgraph.log`, `logs/gateway.log`, `logs/frontend.log`, `logs/nginx.log`

### Backend directory (`cd backend`)

```bash
make dev             # Run LangGraph server only (port 2024)
make gateway         # Run Gateway API only (port 8001)
make test            # Run all backend tests
make lint            # Lint with ruff
make format          # Format code with ruff (--fix + format)

# Run a single test file
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

### Frontend directory (`cd frontend`)

```bash
pnpm lint
pnpm typecheck
BETTER_AUTH_SECRET=local-dev-secret pnpm build   # BETTER_AUTH_SECRET required for build
```

Note: `pnpm check` is broken — use `pnpm lint` and `pnpm typecheck` separately.

### Docker

```bash
make docker-init     # Pull sandbox image (once)
make docker-start    # Start dev services (mode-aware from config.yaml)
make up              # Build + start production Docker services
make down            # Stop production containers
```

## Architecture

DeerFlow is a full-stack super agent harness. Entry point: `http://localhost:2026` (nginx proxy).

**Service topology:**
- **LangGraph Server** (port 2024) — agent runtime, graph execution
- **Gateway API** (port 8001) — FastAPI REST API for models, skills, MCP, memory, uploads, threads
- **Frontend** (port 3000) — Next.js 16 + React 19 + TypeScript
- **Nginx** (port 2026) — unified reverse proxy: `/api/langgraph/*` → 2024, `/api/*` → 8001, `/` → 3000

**Backend split (strict dependency direction: app → deerflow, never reverse):**
- `backend/packages/harness/deerflow/` — publishable `deerflow-harness` package; contains agent orchestration, sandbox, tools, models, MCP, skills, config, memory
- `backend/app/` — unpublished application layer; FastAPI Gateway + IM channel integrations (Feishu, Slack, Telegram)
- Boundary enforced by `backend/tests/test_harness_boundary.py` (runs in CI)

**Frontend structure:**
- `frontend/src/app/` — Next.js routes/pages
- `frontend/src/components/` — UI components (workspace: chats, messages, artifacts, settings)
- `frontend/src/core/` — app logic modules (threads, models, tools, skills, MCP, memory, uploads, agents, i18n)
- `frontend/src/server/better-auth/` — authentication

## Key Backend Components

### Agent System

- **Lead Agent** (`deerflow/agents/lead_agent/agent.py`): entry point `make_lead_agent()`, registered in `backend/langgraph.json`
- **ThreadState** (`deerflow/agents/thread_state.py`): extends `AgentState` with sandbox, thread_data, title, artifacts, todos, uploaded_files, viewed_images
- **Runtime config** (via `config.configurable`): `thinking_enabled`, `model_name`, `is_plan_mode`, `subagent_enabled`

### Middleware Chain (execution order)

1. ThreadDataMiddleware — creates per-thread directories
2. UploadsMiddleware — injects newly uploaded files
3. SandboxMiddleware — acquires sandbox, stores sandbox_id
4. DanglingToolCallMiddleware — handles interrupted tool calls
5. GuardrailMiddleware — pre-tool-call authorization (optional)
6. SummarizationMiddleware — context reduction (optional)
7. TodoListMiddleware — task tracking with `write_todos` (plan_mode only)
8. TitleMiddleware — auto-generates thread title
9. MemoryMiddleware — queues conversations for async memory update
10. ViewImageMiddleware — injects base64 image data (vision models only)
11. SubagentLimitMiddleware — enforces MAX_CONCURRENT_SUBAGENTS=3 (subagent_enabled only)
12. ClarificationMiddleware — intercepts `ask_clarification`, interrupts via `Command(goto=END)` (must be last)

### Configuration

- `config.yaml` (project root) — main config: models, tools, sandbox, memory, summarization, channels
- `extensions_config.json` (project root) — MCP servers and skills enabled state
- Config values starting with `$` are resolved as environment variables
- `get_app_config()` auto-reloads when file mtime changes (no restart needed)
- Override config path via `DEER_FLOW_CONFIG_PATH` env var
- Bump `config_version` in `config.example.yaml` when changing the schema; run `make config-upgrade` to migrate

### Sandbox Virtual Path System

Agent sees virtual paths; physical paths are translated transparently:
- `/mnt/user-data/{workspace,uploads,outputs}` → `backend/.deer-flow/threads/{thread_id}/user-data/...`
- `/mnt/skills` → `deer-flow/skills/`

Sandbox modes: Local (host filesystem), Docker (isolated containers), Docker + Kubernetes (provisioner).

### Subagent System

- Max 3 concurrent subagents (`SubagentLimitMiddleware`)
- Built-in agents: `general-purpose` (all tools except `task`) and `bash` (command specialist)
- `task()` tool → `SubagentExecutor` → background thread → SSE events → result
- 15-minute timeout per subagent

### Memory System

- Stored in `backend/.deer-flow/memory.json`
- LLM extracts facts and context from conversations asynchronously (debounced 30s)
- Top 15 facts + context injected into system prompt via `<memory>` tags
- Deduplicates facts before appending

### Model Factory

- `create_chat_model(name, thinking_enabled)` in `deerflow/models/factory.py`
- Instantiates any LangChain-compatible LLM via reflection from `config.yaml` `use` field
- Supports CLI-backed providers: `CodexChatModel` (Codex CLI) and `ClaudeChatModel` (Claude Code OAuth)

### Gateway API Routers

| Path | Purpose |
|------|---------|
| `GET/PUT /api/mcp/config` | MCP server configuration |
| `GET /api/models` | List/get models |
| `GET/PUT /api/skills` | List, update, install skills |
| `GET /api/memory` | Memory data, reload, config, status |
| `POST /api/threads/{id}/uploads` | Upload files (auto-converts PDF/PPT/Excel/Word via markitdown) |
| `DELETE /api/threads/{id}` | Remove local thread data after LangGraph thread deletion |
| `GET /api/threads/{id}/artifacts/{path}` | Serve artifacts |
| `POST /api/threads/{id}/suggestions` | Generate follow-up questions |

## Development Rules

- **Every feature/bugfix must include tests** in `backend/tests/test_<feature>.py`
- **Always update `backend/README.md` and `backend/CLAUDE.md`** after code changes
- **harness never imports app** — enforced by CI (`tests/test_harness_boundary.py`)
- Code style: `ruff`, line length 240, Python 3.12+, double quotes
- Before opening PRs: `cd backend && make lint && make test`, plus frontend lint/typecheck if frontend was touched

## CI

`.github/workflows/backend-unit-tests.yml` runs on every PR:
1. `uv sync --group dev`
2. `make lint`
3. `make test`

Notable test files:
- `tests/test_harness_boundary.py` — import firewall
- `tests/test_client.py` — embedded client + Gateway conformance (77 tests)
- `tests/test_memory_updater.py` — memory deduplication
- `tests/test_docker_sandbox_mode_detection.py` — sandbox config parsing
- `tests/test_provisioner_kubeconfig.py` — kubeconfig handling

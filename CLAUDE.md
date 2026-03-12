# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the DeerFlow codebase. It covers architecture, development workflow, debugging, and how to add new features.

## Project Overview

DeerFlow is a LangGraph-based AI "super agent harness" with sandbox execution, persistent memory, subagent delegation, extensible tools, skills, and IM channel integrations. It is a full-stack application with a Python backend and Next.js frontend.

## System Architecture

```
Client Browser
    ↓
Nginx (Port 2026) — Unified Reverse Proxy
    ├─ /api/langgraph/* → LangGraph Server (Port 2024)
    ├─ /api/*           → Gateway API (Port 8001)
    └─ /*               → Frontend (Port 3000)
```

### Services

| Service | Port | Role |
|---------|------|------|
| **LangGraph Server** | 2024 | Agent runtime — runs the lead agent, middlewares, tools, subagents |
| **Gateway API** | 8001 | FastAPI REST API — models, MCP, skills, memory, uploads, artifacts, channels |
| **Frontend** | 3000 | Next.js 16 web UI — chat, artifacts, settings, todos |
| **Nginx** | 2026 | Reverse proxy entry point |
| **Provisioner** | 8002 | Optional — Kubernetes sandbox provisioner |

## Directory Structure

```
deer-flow/
├── Makefile                       # Root commands (check, install, dev, stop)
├── config.yaml                    # Main config (from config.example.yaml)
├── extensions_config.json         # MCP servers + skills state
├── .env                           # API keys (git-ignored)
├── backend/
│   ├── Makefile                   # Backend commands (dev, gateway, test, lint)
│   ├── langgraph.json             # LangGraph entry point config
│   ├── src/
│   │   ├── agents/
│   │   │   ├── lead_agent/        # Main agent factory + system prompt
│   │   │   ├── middlewares/       # 11 middleware components (strict order)
│   │   │   ├── memory/            # Persistent memory (updater, queue, prompt)
│   │   │   ├── checkpointer/      # Thread state persistence
│   │   │   └── thread_state.py    # ThreadState schema
│   │   ├── gateway/
│   │   │   ├── app.py             # FastAPI app + lifespan
│   │   │   └── routers/           # 8 route modules
│   │   ├── sandbox/               # Sandbox execution (local + Docker)
│   │   ├── subagents/             # Subagent delegation (executor, registry, builtins)
│   │   ├── tools/builtins/        # present_files, ask_clarification, view_image
│   │   ├── mcp/                   # MCP integration (client, cache, manager)
│   │   ├── models/                # LLM model factory
│   │   ├── skills/                # Skill loading + parsing
│   │   ├── channels/              # IM channels (Slack, Feishu, Telegram)
│   │   ├── config/                # Configuration system
│   │   ├── community/             # Community tools (tavily, jina, firecrawl, etc.)
│   │   ├── reflection/            # Dynamic module loading
│   │   ├── utils/                 # Utilities
│   │   └── client.py              # Embedded Python client (DeerFlowClient)
│   └── tests/                     # Backend tests
├── frontend/
│   ├── src/
│   │   ├── app/                   # Next.js App Router
│   │   ├── components/            # React components (ui/, ai-elements/, workspace/)
│   │   ├── core/                  # Business logic (threads, api, artifacts, i18n, etc.)
│   │   ├── hooks/                 # Shared React hooks
│   │   ├── lib/                   # Utilities (cn())
│   │   └── styles/                # Global CSS
│   └── package.json               # pnpm dependencies
├── skills/
│   ├── public/                    # 17+ public skills (committed)
│   └── custom/                    # User-created skills (git-ignored)
└── docker/                        # Docker compose + nginx configs
```

## Commands

### Root (full application)

```bash
make config     # Generate config files from examples
make check      # Check system requirements
make install    # Install all dependencies
make dev        # Start all services (LangGraph + Gateway + Frontend + Nginx)
make stop       # Stop all services
```

### Backend (`cd backend/`)

```bash
make install    # Install Python dependencies (uv)
make dev        # LangGraph server only (port 2024)
make gateway    # Gateway API only (port 8001)
make test       # Run all tests
make lint       # Lint with ruff
make format     # Format with ruff
```

### Frontend (`cd frontend/`)

```bash
pnpm dev        # Dev server with Turbopack (port 3000)
pnpm build      # Production build
pnpm check      # Lint + type check (run before committing)
pnpm lint:fix   # ESLint with auto-fix
pnpm typecheck  # TypeScript type check
```

### Docker

```bash
make docker-init   # Build Docker images
make docker-start  # Start Docker services
make docker-stop   # Stop Docker services
```

## Configuration

### config.yaml (main application config)

Located at project root. Copied from `config.example.yaml`.

Key sections:
- `models[]` — LLM configs with `use` class path, `supports_thinking`, `supports_vision`
- `tools[]` — Tool configs with `use` variable path and `group`
- `tool_groups[]` — Logical tool groupings
- `sandbox.use` — Sandbox provider class path
- `skills` — Paths to skills directory
- `title` — Auto-title generation settings
- `summarization` — Context summarization config
- `memory` — Memory system config
- `channels` — IM channel config (Feishu, Slack, Telegram)
- `subagents.enabled` — Master switch for subagent delegation

Config values starting with `$` are resolved as environment variables.

Priority: explicit arg → `DEER_FLOW_CONFIG_PATH` env → `config.yaml` in current dir → parent dir.

### extensions_config.json (MCP + skills state)

Located at project root. Copied from `extensions_config.example.json`.

```json
{
  "mcpServers": {
    "server-name": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
    }
  },
  "skills": {
    "public:skill-name": {"enabled": true}
  }
}
```

Priority: explicit arg → `DEER_FLOW_EXTENSIONS_CONFIG_PATH` env → `extensions_config.json` in current dir → parent dir.

### .env (API keys)

Contains provider API keys (OpenAI, Anthropic, Tavily, etc.) and channel tokens. Git-ignored.

---

## Backend Architecture Deep Dive

### Lead Agent

**Entry point**: `backend/src/agents/lead_agent/agent.py` → `make_lead_agent(config: RunnableConfig)`

Registered in `langgraph.json` as `"lead_agent": "src.agents:make_lead_agent"`.

The agent:
1. Reads runtime config (`thinking_enabled`, `model_name`, `is_plan_mode`, `subagent_enabled`)
2. Creates LLM via `create_chat_model()` (supports thinking + vision models)
3. Loads tools via `get_available_tools()` (sandbox + built-in + MCP + community + subagent)
4. Generates system prompt via `apply_prompt_template()` (injects skills, memory, subagent instructions)
5. Runs the middleware chain
6. Returns a `create_react_agent()` instance

### ThreadState

**File**: `backend/src/agents/thread_state.py`

Extends LangGraph's `AgentState` with DeerFlow fields:
- `sandbox: SandboxState` — sandbox environment info
- `thread_data: ThreadDataState` — paths to workspace/uploads/outputs
- `title: str | None` — auto-generated conversation title
- `artifacts: list[str]` — generated file paths (deduplicated via `merge_artifacts`)
- `todos: list | None` — task tracking (plan mode)
- `uploaded_files: list[dict] | None` — uploaded file metadata
- `viewed_images: dict[str, ViewedImageData]` — image data (mergeable via `merge_viewed_images`)

### Middleware Chain (strict order)

All middlewares in `backend/src/agents/middlewares/`:

| # | Middleware | Purpose |
|---|-----------|---------|
| 1 | ThreadDataMiddleware | Creates per-thread dirs under `backend/.deer-flow/threads/{thread_id}/user-data/` |
| 2 | UploadsMiddleware | Tracks uploaded files, injects file list into conversation |
| 3 | SandboxMiddleware | Acquires sandbox, stores `sandbox_id` in state |
| 4 | DanglingToolCallMiddleware | Injects placeholder ToolMessages for incomplete tool calls |
| 5 | SummarizationMiddleware | Context reduction near token limits (optional) |
| 6 | TodoListMiddleware | Task tracking with `write_todos` tool (optional, plan_mode) |
| 7 | TitleMiddleware | Auto-generates thread title after first exchange |
| 8 | MemoryMiddleware | Queues conversations for async memory extraction |
| 9 | ViewImageMiddleware | Injects base64 image data (if model supports vision) |
| 10 | SubagentLimitMiddleware | Enforces `MAX_CONCURRENT_SUBAGENTS = 3` |
| 11 | ClarificationMiddleware | Intercepts `ask_clarification`, interrupts via `Command(goto=END)` — must be last |

### Tool System

**File**: `backend/src/tools/__init__.py` → `get_available_tools()`

Assembles tools from:
1. **Config-defined tools** — resolved from `config.yaml` via reflection
2. **MCP tools** — from enabled MCP servers (lazy init, cached with mtime invalidation)
3. **Built-in tools** (`src/tools/builtins/`):
   - `present_files` — expose output files to user (only `/mnt/user-data/outputs`)
   - `ask_clarification` — request clarification (intercepted by ClarificationMiddleware)
   - `view_image` — read image as base64 (only if model supports vision)
4. **Subagent tool** (if enabled): `task` — delegate to subagent

**Community tools** (`src/community/`):
- `tavily/` — Web search (5 results) and fetch (4KB limit)
- `jina_ai/` — Web fetch via Jina reader API
- `firecrawl/` — Web scraping via Firecrawl API
- `image_search/` — Image search via DuckDuckGo
- `infoquest/` — BytePlus InfoQuest integration

### Sandbox System

**Files**: `backend/src/sandbox/`

**Abstract interface**: `Sandbox` with `execute_command()`, `read_file()`, `write_file()`, `list_dir()`
**Provider pattern**: `SandboxProvider` with `acquire()`, `get()`, `release()` lifecycle

**Implementations**:
- `LocalSandboxProvider` (`src/sandbox/local/`) — filesystem execution, development
- `AioSandboxProvider` (`src/community/aio_sandbox/`) — Docker-based, production

**Virtual path mapping** (agent sees → physical):
| Virtual | Physical |
|---------|----------|
| `/mnt/user-data/workspace` | `backend/.deer-flow/threads/{thread_id}/user-data/workspace` |
| `/mnt/user-data/uploads` | `backend/.deer-flow/threads/{thread_id}/user-data/uploads` |
| `/mnt/user-data/outputs` | `backend/.deer-flow/threads/{thread_id}/user-data/outputs` |
| `/mnt/skills` | `deer-flow/skills/` |

**Sandbox tools** (`src/sandbox/tools.py`): `bash`, `ls`, `read_file`, `write_file`, `str_replace`

### Subagent System

**Files**: `backend/src/subagents/`

- **Built-in agents**: `general-purpose` (all tools except `task`), `bash` (command specialist)
- **Execution**: Dual thread pool — scheduler (3 workers) + execution (3 workers)
- **Concurrency**: MAX_CONCURRENT_SUBAGENTS = 3, 15-minute timeout
- **Flow**: `task()` tool → `SubagentExecutor` → background thread → poll 5s → SSE events → result
- **Events**: `task_started`, `task_running`, `task_completed`, `task_failed`, `task_timed_out`

### MCP System

**Files**: `backend/src/mcp/`

- `MultiServerMCPClient` from `langchain-mcp-adapters`
- Lazy initialization via `get_cached_mcp_tools()`
- Cache invalidation by mtime on `extensions_config.json`
- Transports: stdio, SSE, HTTP
- OAuth support for HTTP/SSE transports

### Skills System

**Files**: `backend/src/skills/`

- **Location**: `deer-flow/skills/{public,custom}/`
- **Format**: Directory with `SKILL.md` containing YAML frontmatter (name, description, license, allowed-tools)
- **Loading**: `load_skills()` scans `skills/{public,custom}` for `SKILL.md`
- **Enabled state**: Stored in `extensions_config.json` under `skills` key with `{category}:{name}` format
- **Injection**: Enabled skills listed in agent system prompt
- **Installation**: `POST /api/skills/install` extracts `.skill` ZIP archive to `custom/`

### Memory System

**Files**: `backend/src/agents/memory/`

- `updater.py` — LLM-based fact extraction and atomic file I/O
- `queue.py` — Debounced update queue (30s default, per-thread deduplication)
- `prompt.py` — Prompt templates

**Data** (`backend/.deer-flow/memory.json`):
- User context: `workContext`, `personalContext`, `topOfMind`
- History: `recentMonths`, `earlierContext`, `longTermBackground`
- Facts: `id`, `content`, `category`, `confidence` (0-1), `createdAt`, `source`

### Gateway API

**Files**: `backend/src/gateway/`

FastAPI on port 8001. Health check: `GET /health`.

| Router | Endpoints |
|--------|-----------|
| Models (`/api/models`) | `GET /` list; `GET /{name}` details |
| MCP (`/api/mcp`) | `GET /config`; `PUT /config` |
| Skills (`/api/skills`) | `GET /`; `GET /{name}?category=`; `PUT /{name}?category=`; `POST /install` |
| Memory (`/api/memory`) | `GET /`; `POST /reload`; `GET /config`; `GET /status` |
| Uploads (`/api/threads/{id}/uploads`) | `POST /`; `GET /list`; `DELETE /{filename}` |
| Artifacts (`/api/threads/{id}/artifacts`) | `GET /{path}?download=true` |
| Channels (`/api/channels`) | Channel management |
| Agents (`/api/agents`) | Agent listing |

### IM Channels

**Files**: `backend/src/channels/`

Bridges Feishu, Slack, Telegram to DeerFlow via LangGraph SDK.

Components: `message_bus.py` (pub/sub), `store.py` (thread mapping), `manager.py` (dispatcher), `service.py` (lifecycle), platform impls (`slack.py`, `feishu.py`, `telegram.py`).

Commands: `/new`, `/status`, `/models`, `/memory`, `/help`.

### Model Factory

**File**: `backend/src/models/factory.py`

`create_chat_model(name, thinking_enabled)` — instantiates LLM from config via reflection. Supports thinking models, vision models, env var resolution. Providers: OpenAI, Anthropic, DeepSeek, Google Gemini, any LangChain integration.

### Embedded Client

**File**: `backend/src/client.py`

`DeerFlowClient` — direct in-process access without HTTP. Same return types as Gateway API. Methods: `chat()`, `stream()`, `list_models()`, `get_mcp_config()`, `list_skills()`, `get_memory()`, `upload_files()`, `get_artifact()`, etc.

---

## Frontend Architecture Deep Dive

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2+

### Source Layout

- `app/` — App Router. Routes: `/` (landing), `/workspace/chats/[thread_id]` (chat)
- `components/ui/` — Shadcn UI primitives (auto-generated, don't edit)
- `components/ai-elements/` — Vercel AI SDK elements (auto-generated, don't edit)
- `components/workspace/` — Chat page components (messages, artifacts, settings, todos)
- `core/` — Business logic:
  - `threads/` — Thread creation, streaming, state (hooks + types)
  - `api/` — LangGraph client singleton (`getAPIClient()`)
  - `artifacts/` — Artifact loading and caching
  - `i18n/` — Internationalization (en-US, zh-CN)
  - `settings/` — User preferences (localStorage)
  - `memory/` — Memory system UI
  - `skills/` — Skills management
  - `messages/` — Message processing
  - `mcp/` — MCP integration UI
  - `streamdown/` — Markdown streaming
- `hooks/` — Shared React hooks
- `lib/` — Utilities (`cn()`)
- `styles/` — Global CSS with CSS variables for theming

### Key Patterns

- Server Components by default, `"use client"` only for interactive components
- Thread hooks (`useThreadStream`, `useSubmitThread`, `useThreads`) are the primary API
- TanStack Query (`@tanstack/react-query`) for server state
- localStorage for user settings
- Path alias: `@/*` → `src/*`
- Environment validation via `@t3-oss/env-nextjs` with Zod

### Code Style

- Import ordering enforced (builtin → external → internal → parent → sibling)
- Inline type imports: `import { type Foo }`
- Unused variables prefixed with `_`
- `cn()` for conditional Tailwind classes

---

## How to Add New Features

### Adding a New Tool

1. **Create the tool function** in `backend/src/community/<tool_name>/` or `backend/src/tools/builtins/<tool_name>/`
2. **Register it** in `config.yaml` under `tools[]`:
   ```yaml
   tools:
     - use: src.community.my_tool:my_tool_function
       group: my_group
   ```
3. **Add the group** to `tool_groups[]` if it's a new group
4. **Write tests** in `backend/tests/test_<tool_name>.py`
5. Run `make test` to verify

### Adding a New Community Tool (Search/Fetch Provider)

1. Create directory: `backend/src/community/<provider>/`
2. Implement the tool function with `@tool` decorator from LangChain
3. Add to `config.yaml` `tools[]` with appropriate group
4. Add any required API keys to `.env.example` and `.env`
5. Write tests

### Adding a New MCP Server

1. Add to `extensions_config.json` under `mcpServers`:
   ```json
   "my-server": {
     "enabled": true,
     "type": "stdio",
     "command": "npx",
     "args": ["-y", "@my/mcp-server"],
     "env": {}
   }
   ```
2. Or use the Gateway API: `PUT /api/mcp/config`
3. Tools are auto-discovered and cached with mtime invalidation

### Adding a New Skill

1. Create directory: `skills/public/<skill-name>/` (or `skills/custom/`)
2. Create `SKILL.md` with YAML frontmatter:
   ```markdown
   ---
   name: My Skill
   description: What this skill does
   license: MIT
   allowed-tools:
     - read_file
     - write_file
     - bash
   ---

   # Skill Instructions
   Instructions injected into the system prompt when skill is loaded...
   ```
3. The skill is auto-discovered by `load_skills()` and listed in the UI
4. Enable/disable via `extensions_config.json` or the UI

### Adding a New Middleware

1. Create file in `backend/src/agents/middlewares/`
2. Implement the middleware class following existing patterns (see any middleware as template)
3. **Register in strict order** in `backend/src/agents/lead_agent/agent.py` middleware chain
4. Order matters — ClarificationMiddleware must always be last
5. Write tests

### Adding a New Gateway API Router

1. Create file in `backend/src/gateway/routers/<name>.py`
2. Define an `APIRouter` with appropriate prefix
3. Register in `backend/src/gateway/app.py` via `app.include_router()`
4. Add corresponding frontend API client in `frontend/src/core/<name>/api.ts`
5. Add React hooks in `frontend/src/core/<name>/hooks.ts`
6. Write tests

### Adding a New Subagent Type

1. Create file in `backend/src/subagents/builtins/<name>.py`
2. Define the agent with system prompt, allowed tools, and description
3. Register in `backend/src/subagents/registry.py`
4. The lead agent can now delegate to it via the `task()` tool

### Adding a New IM Channel

1. Create `backend/src/channels/<platform>.py` extending the `Channel` base class
2. Implement `start()`, `stop()`, and `send()` methods
3. Add channel config section to `config.yaml` under `channels`
4. Register in `backend/src/channels/service.py`
5. Add required tokens to `.env.example`

### Adding a New LLM Provider

1. Install the LangChain integration: `uv add langchain-<provider>`
2. Add model config to `config.yaml` under `models[]`:
   ```yaml
   models:
     - name: my-model
       display_name: My Model
       use: langchain_provider:ChatProvider
       api_key: $MY_API_KEY
       supports_thinking: false
       supports_vision: false
   ```
3. Add the API key to `.env.example` and `.env`
4. The model factory resolves the class via reflection automatically

### Adding Frontend Components

1. For UI primitives, use Shadcn CLI: `pnpm dlx shadcn@latest add <component>`
2. For workspace components, create in `frontend/src/components/workspace/`
3. For business logic, add to `frontend/src/core/<domain>/`
4. Use TanStack Query for server state, localStorage for client state
5. Run `pnpm check` before committing

### Adding i18n Translations

1. Add keys to `frontend/src/core/i18n/locales/types.ts`
2. Add translations in `en-US.ts` and `zh-CN.ts`
3. Use via `const { t } = useI18n()` in components

---

## Debugging Guide

### Backend Debugging

**LangGraph server won't start**:
- Check `config.yaml` exists at project root (copy from `config.example.yaml`)
- Check `.env` has required API keys
- Check `langgraph.json` points to valid entry: `"lead_agent": "src.agents:make_lead_agent"`
- Run from `backend/` dir: `PYTHONPATH=. uv run python -c "from src.agents import make_lead_agent; print('OK')"`

**Gateway API errors**:
- Check health: `curl http://localhost:8001/health`
- Check logs for router registration errors in `src/gateway/app.py`
- For upload/artifact issues, verify thread directory exists: `backend/.deer-flow/threads/{thread_id}/`

**Tool not appearing**:
- Verify it's in `config.yaml` `tools[]` with correct `use` path
- Check the `group` matches an entry in `tool_groups[]`
- For MCP tools, check `extensions_config.json` has the server enabled
- Check import path is resolvable: `PYTHONPATH=. uv run python -c "from src.community.my_tool import my_func"`

**Middleware not executing**:
- Verify registration order in `backend/src/agents/lead_agent/agent.py`
- Check conditional middlewares (plan_mode, subagent_enabled, vision) have their flags set
- Add logging: middlewares use Python `logging` module

**Memory not updating**:
- Check `memory.enabled: true` in `config.yaml`
- Memory updates are debounced (30s default) — wait for queue flush
- Check `backend/.deer-flow/memory.json` for data
- Force reload: `POST /api/memory/reload`

**Sandbox path issues**:
- Local sandbox maps virtual paths → physical paths via `replace_virtual_path()`
- Check `is_local_sandbox()` returns correct value
- Verify thread dirs exist under `backend/.deer-flow/threads/`

**Skill not loading**:
- Check `SKILL.md` exists in skill directory with valid YAML frontmatter
- Check `extensions_config.json` has skill enabled (key format: `{category}:{name}`)
- Duplicate skill names within a category raise `ValueError`

### Frontend Debugging

**Build/type errors**:
- Run `pnpm check` to see all lint + type errors
- Don't edit files in `components/ui/` or `components/ai-elements/` — they're auto-generated

**API connection issues**:
- Default: frontend connects through nginx at port 2026
- Direct: set `NEXT_PUBLIC_BACKEND_BASE_URL` and `NEXT_PUBLIC_LANGGRAPH_BASE_URL` in `.env`
- Check nginx is running: `curl http://localhost:2026/api/health`

**Thread streaming issues**:
- Check `core/threads/hooks.ts` — `useThreadStream` manages SSE connection
- Verify LangGraph server is running on port 2024
- Check browser DevTools Network tab for SSE stream

**Environment validation**:
- Uses `@t3-oss/env-nextjs` with Zod — skip with `SKIP_ENV_VALIDATION=1`
- Schema defined in `src/env.js`

### General Debugging

**Check all services are running**:
```bash
curl http://localhost:2024/ok       # LangGraph
curl http://localhost:8001/health   # Gateway
curl http://localhost:3000          # Frontend
curl http://localhost:2026          # Nginx
```

**View logs**:
- Services log to stdout/stderr
- Check `logs/` directory at project root for file-based logs
- Nginx logs in Docker: `docker logs deer-flow-nginx`

**Run backend tests**:
```bash
cd backend && make test                                    # All tests
PYTHONPATH=. uv run pytest tests/test_client.py -v         # Specific file
PYTHONPATH=. uv run pytest tests/test_client.py -k "test_name" -v  # Specific test
```

---

## Code Style & Conventions

### Backend (Python)

- **Formatter/Linter**: ruff
- **Line length**: 240 characters
- **Python**: 3.12+ with type hints
- **Quotes**: Double quotes
- **Indentation**: Spaces
- **Testing**: pytest, TDD is mandatory — every feature/fix needs tests

### Frontend (TypeScript)

- **Formatter/Linter**: ESLint + Prettier
- **Language**: TypeScript for all code
- **Styling**: Tailwind CSS 4
- **Imports**: Enforced ordering, inline type imports (`import { type Foo }`)
- **Path alias**: `@/*` → `src/*`
- **Components**: `"use client"` only when needed
- **State**: TanStack Query for server state, localStorage for user settings
- **Package manager**: pnpm 10.26.2+
- **Node**: 22+

### Documentation

Always update relevant docs after code changes:
- `CLAUDE.md` (this file) for architecture/development changes
- `backend/CLAUDE.md` for backend-specific changes
- `frontend/CLAUDE.md` for frontend-specific changes
- `README.md` for user-facing changes

---

## Key Files Quick Reference

| Purpose | File |
|---------|------|
| Agent entry point | `backend/src/agents/lead_agent/agent.py` |
| System prompt | `backend/src/agents/lead_agent/prompt.py` |
| Thread state schema | `backend/src/agents/thread_state.py` |
| Tool assembly | `backend/src/tools/__init__.py` |
| Sandbox tools | `backend/src/sandbox/tools.py` |
| Model factory | `backend/src/models/factory.py` |
| Gateway app | `backend/src/gateway/app.py` |
| Skill loader | `backend/src/skills/loader.py` |
| Memory updater | `backend/src/agents/memory/updater.py` |
| Subagent executor | `backend/src/subagents/executor.py` |
| MCP client | `backend/src/mcp/client.py` |
| Config loader | `backend/src/config/app_config.py` |
| Extensions config | `backend/src/config/extensions_config.py` |
| Embedded client | `backend/src/client.py` |
| Frontend thread hooks | `frontend/src/core/threads/hooks.ts` |
| Frontend API client | `frontend/src/core/api/` |
| LangGraph config | `backend/langgraph.json` |
| Main config | `config.yaml` (project root) |
| Extensions config | `extensions_config.json` (project root) |

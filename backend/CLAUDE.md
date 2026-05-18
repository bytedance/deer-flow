# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeerFlow is a LangGraph-based AI super agent system with a full-stack architecture. The backend provides a "super agent" with sandbox execution, persistent memory, subagent delegation, and extensible tool integration - all operating in per-thread isolated environments.

**Architecture**:
- **Gateway API** (port 8001): REST API plus embedded LangGraph-compatible agent runtime
- **Frontend** (port 3000): Next.js web interface
- **Nginx** (port 2026): Unified reverse proxy entry point
- **Provisioner** (port 8002, optional in Docker dev): Started only when sandbox is configured for provisioner/Kubernetes mode

**Runtime**:
- `make dev`, Docker dev, and production all run the agent runtime in Gateway via `RunManager` + `run_agent()` + `StreamBridge` (`packages/harness/deerflow/runtime/`). Nginx exposes that runtime at `/api/langgraph/*` and rewrites it to Gateway's native `/api/*` routers.

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
│   │   └── harness/           # deerflow-harness package (import: deerflow.*)
│   │       ├── pyproject.toml
│   │       └── deerflow/
│   │           ├── agents/            # LangGraph agent system
│   │           │   ├── lead_agent/    # Main agent (factory + system prompt)
│   │           │   ├── middlewares/   # 10 middleware components
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
│   │           ├── tools/builtins/    # Built-in tools (present_files, ask_clarification, view_image)
│   │           ├── mcp/               # MCP integration (tools, cache, client)
│   │           ├── models/            # Model factory with thinking/vision support
│   │           ├── skills/            # Skills discovery, loading, parsing
│   │           ├── config/            # Configuration system (app, model, sandbox, tool, etc.)
│   │           ├── community/         # Community tools (tavily, jina_ai, firecrawl, image_search, aio_sandbox)
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
**CRITICAL: Always update README.md and CLAUDE.md after every code change**

When making code changes, you MUST update the relevant documentation:
- Update `README.md` for user-facing changes (features, setup, usage instructions)
- Update `CLAUDE.md` for development changes (architecture, commands, workflows, internal systems)
- Keep documentation synchronized with the codebase at all times
- Ensure accuracy and timeliness of all documentation

## Commands

**Root directory** (for full application):
```bash
make check      # Check system requirements
make install    # Install all dependencies (frontend + backend)
make dev        # Start all services (Gateway + Frontend + Nginx), with config.yaml preflight
make start      # Start production services locally
make stop       # Stop all services
```

**Backend directory** (for backend development only):
```bash
make install    # Install backend dependencies
make dev        # Run Gateway API with reload (port 8001)
make gateway    # Run Gateway API only (port 8001)
make test       # Run all backend tests
make lint       # Lint with ruff
make format     # Format code with ruff
```

Regression tests related to Docker/provisioner behavior:
- `tests/test_docker_sandbox_mode_detection.py` (mode detection from `config.yaml`)
- `tests/test_provisioner_kubeconfig.py` (kubeconfig file/directory handling)

Boundary check (harness → app import firewall):
- `tests/test_harness_boundary.py` — ensures `packages/harness/deerflow/` never imports from `app.*`

CI runs these regression tests for every pull request via [.github/workflows/backend-unit-tests.yml](../.github/workflows/backend-unit-tests.yml).

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

### Agent System

**Lead Agent** (`packages/harness/deerflow/agents/lead_agent/agent.py`):
- Entry point: `make_lead_agent(config: RunnableConfig)` registered in `langgraph.json`
- Dynamic model selection via `create_chat_model()` with thinking/vision support
- Tools loaded via `get_available_tools()` - combines sandbox, built-in, MCP, community, and subagent tools
- System prompt generated by `apply_prompt_template()` with skills, memory, and subagent instructions

**ThreadState** (`packages/harness/deerflow/agents/thread_state.py`):
- Extends `AgentState` with: `sandbox`, `thread_data`, `title`, `artifacts`, `todos`, `uploaded_files`, `viewed_images`
- Uses custom reducers: `merge_artifacts` (deduplicate), `merge_viewed_images` (merge/clear)

**Runtime Configuration** (via `config.configurable`):
- `thinking_enabled` - Enable model's extended thinking
- `model_name` - Select specific LLM model
- `is_plan_mode` - Enable TodoList middleware
- `subagent_enabled` - Enable task delegation tool

### Middleware Chain

Lead-agent middlewares are assembled in strict append order across `packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` (`build_lead_runtime_middlewares`) and `packages/harness/deerflow/agents/lead_agent/agent.py` (`_build_middlewares`):

1. **ThreadDataMiddleware** - Creates per-thread directories under the user's isolation scope (`backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`); resolves `user_id` via `get_effective_user_id()` (falls back to `"default"` in no-auth mode); Web UI thread deletion now follows LangGraph thread removal with Gateway cleanup of the local thread directory
2. **UploadsMiddleware** - Tracks and injects newly uploaded files into conversation
3. **SandboxMiddleware** - Acquires sandbox, stores `sandbox_id` in state
4. **DanglingToolCallMiddleware** - Injects placeholder ToolMessages for AIMessage tool_calls that lack responses (e.g., due to user interruption), including raw provider tool-call payloads preserved only in `additional_kwargs["tool_calls"]`
5. **LLMErrorHandlingMiddleware** - Normalizes provider/model invocation failures into recoverable assistant-facing errors before later middleware/tool stages run
6. **GuardrailMiddleware** - Pre-tool-call authorization via pluggable `GuardrailProvider` protocol (optional, if `guardrails.enabled` in config). Evaluates each tool call and returns error ToolMessage on deny. Three provider options: built-in `AllowlistProvider` (zero deps), OAP policy providers (e.g. `aport-agent-guardrails`), or custom providers. See [docs/GUARDRAILS.md](docs/GUARDRAILS.md) for setup, usage, and how to implement a provider.
7. **SandboxAuditMiddleware** - Audits sandboxed shell/file operations for security logging before tool execution continues
8. **ToolErrorHandlingMiddleware** - Converts tool exceptions into error `ToolMessage`s so the run can continue instead of aborting
9. **SummarizationMiddleware** - Context reduction when approaching token limits (optional, if enabled)
10. **TodoListMiddleware** - Task tracking with `write_todos` tool (optional, if plan_mode)
11. **TokenUsageMiddleware** - Records token usage metrics when token tracking is enabled (optional); subagent usage is cached by `tool_call_id` only while token usage is enabled and merged back into the dispatching AIMessage by message position rather than message id
12. **TitleMiddleware** - Auto-generates thread title after first complete exchange and normalizes structured message content before prompting the title model
13. **MemoryMiddleware** - Queues conversations for async memory update (filters to user + final AI responses)
14. **ViewImageMiddleware** - Injects base64 image data before LLM call (conditional on vision support)
15. **DeferredToolFilterMiddleware** - Hides deferred tool schemas from the bound model until tool search is enabled (optional)
16. **SubagentLimitMiddleware** - Truncates excess `task` tool calls from model response to enforce `MAX_CONCURRENT_SUBAGENTS` limit (optional, if `subagent_enabled`)
17. **LoopDetectionMiddleware** - Detects repeated tool-call loops; hard-stop responses clear both structured `tool_calls` and raw provider tool-call metadata before forcing a final text answer
18. **ClarificationMiddleware** - Intercepts `ask_clarification` tool calls, interrupts via `Command(goto=END)` (must be last)

### Configuration System

**Main Configuration** (`config.yaml`):

Setup: Copy `config.example.yaml` to `config.yaml` in the **project root** directory.

**Config Versioning**: `config.example.yaml` has a `config_version` field. On startup, `AppConfig.from_file()` compares user version vs example version and emits a warning if outdated. Missing `config_version` = version 0. Run `make config-upgrade` to auto-merge missing fields. When changing the config schema, bump `config_version` in `config.example.yaml`.

**Config Caching**: `get_app_config()` caches the parsed config, but automatically reloads it when the resolved config path changes or the file's mtime increases. This keeps Gateway and LangGraph reads aligned with `config.yaml` edits without requiring a manual process restart.

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_CONFIG_PATH` environment variable
3. `config.yaml` in current directory (backend/)
4. `config.yaml` in parent directory (project root - **recommended location**)

Config values starting with `$` are resolved as environment variables (e.g., `$OPENAI_API_KEY`).
`ModelConfig` also declares `use_responses_api` and `output_version` so OpenAI `/v1/responses` can be enabled explicitly while still using `langchain_openai:ChatOpenAI`.

**Extensions Configuration** (`extensions_config.json`):

MCP servers and skills are configured together in `extensions_config.json` in project root:

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable
3. `extensions_config.json` in current directory (backend/)
4. `extensions_config.json` in parent directory (project root - **recommended location**)

### Gateway API (`app/gateway/`)

FastAPI application on port 8001 with health check at `GET /health`. Set `GATEWAY_ENABLE_DOCS=false` to disable `/docs`, `/redoc`, and `/openapi.json` in production (default: enabled).

CORS is same-origin by default when requests enter through nginx on port 2026. Split-origin or port-forwarded browser clients must opt in with `GATEWAY_CORS_ORIGINS` (comma-separated exact origins); Gateway `CORSMiddleware` and `CSRFMiddleware` both read that variable so browser CORS and auth-origin checks stay aligned.

**Routers**:

| Router | Endpoints |
|--------|-----------|
| **Models** (`/api/models`) | `GET /` - list models; `GET /{name}` - model details |
| **MCP** (`/api/mcp`) | `GET /config` - get config; `PUT /config` - update config (saves to extensions_config.json) |
| **Skills** (`/api/skills`) | `GET /` - list skills; `GET /{name}` - details; `PUT /{name}` - update enabled; `POST /install` - install from .skill archive (accepts standard optional frontmatter like `version`, `author`, `compatibility`) |
| **Memory** (`/api/memory`) | `GET /` - memory data; `POST /reload` - force reload; `GET /config` - config; `GET /status` - config + data |
| **Uploads** (`/api/threads/{id}/uploads`) | `POST /` - upload files (auto-converts PDF/PPT/Excel/Word); `GET /list` - list; `DELETE /{filename}` - delete |
| **Threads** (`/api/threads/{id}`) | `DELETE /` - remove DeerFlow-managed local thread data after LangGraph thread deletion; unexpected failures are logged server-side and return a generic 500 detail |
| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - serve artifacts; active content types (`text/html`, `application/xhtml+xml`, `image/svg+xml`) are always forced as download attachments to reduce XSS risk; `?download=true` still forces download for other file types |
| **Suggestions** (`/api/threads/{id}/suggestions`) | `POST /` - generate follow-up questions; rich list/block model content is normalized before JSON parsing |
| **Thread Runs** (`/api/threads/{id}/runs`) | `POST /` - create background run; `POST /stream` - create + SSE stream; `POST /wait` - create + block; `GET /` - list runs; `GET /{rid}` - run details; `POST /{rid}/cancel` - cancel; `GET /{rid}/join` - join SSE; `GET /{rid}/messages` - paginated messages `{data, has_more}`; `GET /{rid}/events` - full event stream; `GET /../messages` - thread messages with feedback; `GET /../token-usage` - aggregate tokens |
| **Feedback** (`/api/threads/{id}/runs/{rid}/feedback`) | `PUT /` - upsert feedback; `DELETE /` - delete user feedback; `POST /` - create feedback; `GET /` - list feedback; `GET /stats` - aggregate stats; `DELETE /{fid}` - delete specific |
| **Runs** (`/api/runs`) | `POST /stream` - stateless run + SSE; `POST /wait` - stateless run + block; `GET /{rid}/messages` - paginated messages by run_id `{data, has_more}` (cursor: `after_seq`/`before_seq`); `GET /{rid}/feedback` - list feedback by run_id |

Proxied through nginx: `/api/langgraph/*` → Gateway LangGraph-compatible runtime, all other `/api/*` → Gateway REST APIs.

### Sandbox System (`packages/harness/deerflow/sandbox/`)

**Interface**: Abstract `Sandbox` with `execute_command`, `read_file`, `write_file`, `list_dir`
**Provider Pattern**: `SandboxProvider` with `acquire`, `get`, `release` lifecycle
**Implementations**:
- `LocalSandboxProvider` - Local filesystem execution. `acquire(thread_id)` returns a per-thread `LocalSandbox` (id `local:{thread_id}`) whose `path_mappings` resolve `/mnt/user-data/{workspace,uploads,outputs}` and `/mnt/acp-workspace` to that thread's host directories, so the public `Sandbox` API honours the `/mnt/user-data` contract uniformly with AIO. `acquire()` / `acquire(None)` keeps the legacy generic singleton (id `local`) for callers without a thread context. Per-thread sandboxes are held in an LRU cache (default 256 entries) guarded by a `threading.Lock`.
- `AioSandboxProvider` (`packages/harness/deerflow/community/`) - Docker-based isolation

**Virtual Path System**:
- Agent sees: `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`
- Physical: `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`, `deer-flow/skills/`
- Translation: `LocalSandboxProvider` builds per-thread `PathMapping`s for the user-data prefixes at acquire time; `tools.py` keeps `replace_virtual_path()` / `replace_virtual_paths_in_command()` as a defense-in-depth layer (and for path validation). AIO has the directories volume-mounted at the same virtual paths inside its container, so both implementations accept `/mnt/user-data/...` natively.
- Detection: `is_local_sandbox()` accepts both `sandbox_id == "local"` (legacy / no-thread) and `sandbox_id.startswith("local:")` (per-thread)

**Sandbox Tools** (in `packages/harness/deerflow/sandbox/tools.py`):
- `bash` - Execute commands with path translation and error handling
- `ls` - Directory listing (tree format, max 2 levels)
- `read_file` - Read file contents with optional line range
- `write_file` - Write/append to files, creates directories; overwrites by default and exposes the `append` argument in the model-facing schema for end-of-file writes
- `str_replace` - Substring replacement (single or all occurrences); same-path serialization is scoped to `(sandbox.id, path)` so isolated sandboxes do not contend on identical virtual paths inside one process

### Subagent System (`packages/harness/deerflow/subagents/`)

**Built-in Agents**: `general-purpose` (all tools except `task`) and `bash` (command specialist)
**Execution**: Dual thread pool - `_scheduler_pool` (3 workers) + `_execution_pool` (3 workers)
**Concurrency**: `MAX_CONCURRENT_SUBAGENTS = 3` enforced by `SubagentLimitMiddleware` (truncates excess tool calls in `after_model`), 15-minute timeout
**Flow**: `task()` tool → `SubagentExecutor` → background thread → poll 5s → SSE events → result
**Events**: `task_started`, `task_running`, `task_completed`/`task_failed`/`task_timed_out`

### Tool System (`packages/harness/deerflow/tools/`)

`get_available_tools(groups, include_mcp, model_name, subagent_enabled)` assembles:
1. **Config-defined tools** - Resolved from `config.yaml` via `resolve_variable()`
2. **MCP tools** - From enabled MCP servers (lazy initialized, cached with mtime invalidation)
3. **Built-in tools**:
   - `present_files` - Make output files visible to user (only `/mnt/user-data/outputs`)
   - `ask_clarification` - Request clarification (intercepted by ClarificationMiddleware → interrupts)
   - `view_image` - Read image as base64 (added only if model supports vision)
   - `setup_agent` - Bootstrap-only: persist a brand-new custom agent's `SOUL.md` and `config.yaml`. Bound only when `is_bootstrap=True`.
   - `update_agent` - Custom-agent-only: persist self-updates to the current agent's `SOUL.md` / `config.yaml` from inside a normal chat (partial update + atomic write). Bound when `agent_name` is set and `is_bootstrap=False`.
4. **Subagent tool** (if enabled):
   - `task` - Delegate to subagent (description, prompt, subagent_type)

**Community tools** (`packages/harness/deerflow/community/`):
- `tavily/` - Web search (5 results default) and web fetch (4KB limit)
- `jina_ai/` - Web fetch via Jina reader API with readability extraction
- `firecrawl/` - Web scraping via Firecrawl API

**ACP agent tools**:
- `invoke_acp_agent` - Invokes external ACP-compatible agents from `config.yaml`
- ACP launchers must be real ACP adapters. The standard `codex` CLI is not ACP-compatible by itself; configure a wrapper such as `npx -y @zed-industries/codex-acp` or an installed `codex-acp` binary
- Missing ACP executables now return an actionable error message instead of a raw `[Errno 2]`
- Each ACP agent uses a per-thread workspace at `{base_dir}/users/{user_id}/threads/{thread_id}/acp-workspace/`. The workspace is accessible to the lead agent via the virtual path `/mnt/acp-workspace/` (read-only). In docker sandbox mode, the directory is volume-mounted into the container at `/mnt/acp-workspace` (read-only); in local sandbox mode, path translation is handled by `tools.py`
- `image_search/` - Image search via DuckDuckGo

### MCP System (`packages/harness/deerflow/mcp/`)

- Uses `langchain-mcp-adapters` `MultiServerMCPClient` for multi-server management
- **Lazy initialization**: Tools loaded on first use via `get_cached_mcp_tools()`
- **Cache invalidation**: Detects config file changes via mtime comparison
- **Transports**: stdio (command-based), SSE, HTTP
- **OAuth (HTTP/SSE)**: Supports token endpoint flows (`client_credentials`, `refresh_token`) with automatic token refresh + Authorization header injection
- **Runtime updates**: Gateway API saves to extensions_config.json; LangGraph detects via mtime

### Skills System (`packages/harness/deerflow/skills/`)

- **Location**: `deer-flow/skills/{public,custom}/`
- **Format**: Directory with `SKILL.md` (YAML frontmatter: name, description, license, allowed-tools)
- **Loading**: `load_skills()` recursively scans `skills/{public,custom}` for `SKILL.md`, parses metadata, and reads enabled state from extensions_config.json
- **Injection**: Enabled skills listed in agent system prompt with container paths
- **Installation**: `POST /api/skills/install` extracts .skill ZIP archive to custom/ directory

### Model Factory (`packages/harness/deerflow/models/factory.py`)

- `create_chat_model(name, thinking_enabled)` instantiates LLM from config via reflection
- Supports `thinking_enabled` flag with per-model `when_thinking_enabled` overrides
- Supports vLLM-style thinking toggles via `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking` for Qwen reasoning models, while normalizing legacy `thinking` configs for backward compatibility
- Supports `supports_vision` flag for image understanding models
- Config values starting with `$` resolved as environment variables
- Missing provider modules surface actionable install hints from reflection resolvers (for example `uv add langchain-google-genai`)

### vLLM Provider (`packages/harness/deerflow/models/vllm_provider.py`)

- `VllmChatModel` subclasses `langchain_openai:ChatOpenAI` for vLLM 0.19.0 OpenAI-compatible endpoints
- Preserves vLLM's non-standard assistant `reasoning` field on full responses, streaming deltas, and follow-up tool-call turns
- Designed for configs that enable thinking through `extra_body.chat_template_kwargs.enable_thinking` on vLLM 0.19.0 Qwen reasoning models, while accepting the older `thinking` alias

### IM Channels System (`app/channels/`)

Bridges external messaging platforms (Feishu, Slack, Telegram, DingTalk) to the DeerFlow agent via the LangGraph Server.


**Architecture**: Channels communicate with Gateway through the `langgraph-sdk` HTTP client (same as the frontend), ensuring threads are created and managed server-side. The internal SDK client injects process-local internal auth plus a matching CSRF cookie/header pair so Gateway accepts state-changing thread/run requests from channel workers without relying on browser session cookies.

**Components**:
- `message_bus.py` - Async pub/sub hub (`InboundMessage` → queue → dispatcher; `OutboundMessage` → callbacks → channels)
- `store.py` - JSON-file persistence mapping `channel_name:chat_id[:topic_id]` → `thread_id` (keys are `channel:chat` for root conversations and `channel:chat:topic` for threaded conversations)
- `manager.py` - Core dispatcher: creates threads via `client.threads.create()`, routes commands, keeps Slack/Telegram on `client.runs.wait()`, and uses `client.runs.stream(["messages-tuple", "values"])` for Feishu incremental outbound updates
- `base.py` - Abstract `Channel` base class (start/stop/send lifecycle)
- `service.py` - Manages lifecycle of all configured channels from `config.yaml`
- `slack.py` / `feishu.py` / `telegram.py` / `dingtalk.py` - Platform-specific implementations (`feishu.py` tracks the running card `message_id` in memory and patches the same card in place; `dingtalk.py` optionally uses AI Card streaming for in-place updates when `card_template_id` is configured)

**Message Flow**:
1. External platform -> Channel impl -> `MessageBus.publish_inbound()`
2. `ChannelManager._dispatch_loop()` consumes from queue
3. For chat: look up/create thread through Gateway's LangGraph-compatible API
4. Feishu chat: `runs.stream()` → accumulate AI text → publish multiple outbound updates (`is_final=False`) → publish final outbound (`is_final=True`)
5. Slack/Telegram chat: `runs.wait()` → extract final response → publish outbound
6. Feishu channel sends one running reply card up front, then patches the same card for each outbound update (card JSON sets `config.update_multi=true` for Feishu's patch API requirement)
7. DingTalk AI Card mode (when `card_template_id` configured): `runs.stream()` → create card with initial text → stream updates via `PUT /v1.0/card/streaming` → finalize on `is_final=True`. Falls back to `sampleMarkdown` if card creation or streaming fails
8. For commands (`/new`, `/status`, `/models`, `/memory`, `/help`): handle locally or query Gateway API
9. Outbound → channel callbacks → platform reply

**Configuration** (`config.yaml` -> `channels`):
- `langgraph_url` - LangGraph-compatible Gateway API base URL (default: `http://localhost:8001/api`)
- `gateway_url` - Gateway API URL for auxiliary commands (default: `http://localhost:8001`)
- In Docker Compose, IM channels run inside the `gateway` container, so `localhost` points back to that container. Use `http://gateway:8001/api` for `langgraph_url` and `http://gateway:8001` for `gateway_url`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` / `DEER_FLOW_CHANNELS_GATEWAY_URL`.
- Per-channel configs: `feishu` (app_id, app_secret), `slack` (bot_token, app_token), `telegram` (bot_token), `dingtalk` (client_id, client_secret, optional `card_template_id` for AI Card streaming)


### Memory System (`packages/harness/deerflow/agents/memory/`)

**Components**:
- `updater.py` - LLM-based memory updates with fact extraction, whitespace-normalized fact deduplication (trims leading/trailing whitespace before comparing), and atomic file I/O
- `queue.py` - Debounced update queue (per-thread deduplication, configurable wait time); captures `user_id` at enqueue time so it survives the `threading.Timer` boundary
- `prompt.py` - Prompt templates for memory updates
- `storage.py` - File-based storage with per-user isolation; cache keyed by `(user_id, agent_name)` tuple

**Per-User Isolation**:
- Memory is stored per-user at `{base_dir}/users/{user_id}/memory.json`
- Per-agent per-user memory at `{base_dir}/users/{user_id}/agents/{agent_name}/memory.json`
- Custom agent definitions (`SOUL.md` + `config.yaml`) are also per-user at `{base_dir}/users/{user_id}/agents/{agent_name}/`. The legacy shared layout `{base_dir}/agents/{agent_name}/` remains read-only fallback for unmigrated installations
- `user_id` is resolved via `get_effective_user_id()` from `deerflow.runtime.user_context`
- In no-auth mode, `user_id` defaults to `"default"` (constant `DEFAULT_USER_ID`)
- Absolute `storage_path` in config opts out of per-user isolation
- **Migration**: Run `PYTHONPATH=. python scripts/migrate_user_isolation.py` to move legacy `memory.json`, `threads/`, and `agents/` into per-user layout. Supports `--dry-run` (preview changes) and `--user-id USER_ID` (assign unowned legacy data to a user, defaults to `default`).

**Data Structure** (stored in `{base_dir}/users/{user_id}/memory.json`):
- **User Context**: `workContext`, `personalContext`, `topOfMind` (1-3 sentence summaries)
- **History**: `recentMonths`, `earlierContext`, `longTermBackground`
- **Facts**: Discrete facts with `id`, `content`, `category` (preference/knowledge/context/behavior/goal), `confidence` (0-1), `createdAt`, `source`

**Workflow**:
1. `MemoryMiddleware` filters messages (user inputs + final AI responses), captures `user_id` via `get_effective_user_id()`, and queues conversation with the captured `user_id`
2. Queue debounces (30s default), batches updates, deduplicates per-thread
3. Background thread invokes LLM to extract context updates and facts, using the stored `user_id` (not the contextvar, which is unavailable on timer threads)
4. Applies updates atomically (temp file + rename) with cache invalidation, skipping duplicate fact content before append
5. Next interaction injects top 15 facts + context into `<memory>` tags in system prompt

Focused regression coverage for the updater lives in `backend/tests/test_memory_updater.py`.

**Configuration** (`config.yaml` → `memory`):
- `enabled` / `injection_enabled` - Master switches
- `storage_path` - Path to memory.json (absolute path opts out of per-user isolation)
- `debounce_seconds` - Wait time before processing (default: 30)
- `model_name` - LLM for updates (null = default model)
- `max_facts` / `fact_confidence_threshold` - Fact storage limits (100 / 0.7)
- `max_injection_tokens` - Token limit for prompt injection (2000)

### Reflection System (`packages/harness/deerflow/reflection/`)

- `resolve_variable(path)` - Import module and return variable (e.g., `module.path:variable_name`)
- `resolve_class(path, base_class)` - Import and validate class against base class

### Config Schema

**`config.yaml`** key sections:
- `models[]` - LLM configs with `use` class path, `supports_thinking`, `supports_vision`, provider-specific fields
- vLLM reasoning models should use `deerflow.models.vllm_provider:VllmChatModel`; for Qwen-style parsers prefer `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking`, and DeerFlow will also normalize the older `thinking` alias
- `tools[]` - Tool configs with `use` variable path and `group`
- `tool_groups[]` - Logical groupings for tools
- `sandbox.use` - Sandbox provider class path
- `skills.path` / `skills.container_path` - Host and container paths to skills directory
- `title` - Auto-title generation (enabled, max_words, max_chars, prompt_template)
- `summarization` - Context summarization (enabled, trigger conditions, keep policy)
- `subagents.enabled` - Master switch for subagent delegation
- `memory` - Memory system (enabled, storage_path, debounce_seconds, model_name, max_facts, fact_confidence_threshold, injection_enabled, max_injection_tokens)
- `enterprise` - **Enterprise extension** (disabled by default; see "Enterprise Extension" below)

**`extensions_config.json`**:
- `mcpServers` - Map of server name → config (enabled, type, command, args, env, url, headers, oauth, description)
- `skills` - Map of skill name → state (enabled)

Both can be modified at runtime via Gateway API endpoints or `DeerFlowClient` methods.

### Enterprise Extension (`packages/harness/deerflow/enterprise/`)

Optional, opt-in extension that layers RBAC, audit, approval, and OIDC SSO on top of the OSS gateway. **Disabled by default — `config.yaml` without an `enterprise:` block is a fully working OSS install**.

**Foundation modules (M0, landed)**:
- `enterprise.config` — Pydantic v2 `EnterpriseConfig` with `model_validator(mode="after")` that:
  - Hard-fails on `approval.enabled=True` + `rbac.enabled=False` (approval grants depend on identity)
  - Hard-fails on `approval.enabled=True` + `audit.enabled=False` (approval decisions must be auditable)
  - Warns on `oidc.enabled=True` + `rbac.enabled=False` (SSO without role mapping silently grants `_ALL_PERMISSIONS`)
  - Warns on `enterprise.enabled=False` while any sub-module is enabled (silent inertness)
- `enterprise.middlewares.get_enterprise_middlewares(config)` — agent-layer middleware factory. Returns `[]` in M0; later milestones append `AuditMiddleware` and friends here. Wired into the lead-agent chain via `_build_middlewares(custom_middlewares=...)` so the enterprise stack lands as the second-to-last entry, with `ClarificationMiddleware` always at the tail (locked in by `tests/test_lead_agent_middleware_order.py`).
- `enterprise.persistence.database.EnterpriseDatabase` — async engine wrapper. **Reuses `deerflow.persistence.base:Base`** rather than creating a second declarative_base so the existing Alembic env detects enterprise tables automatically.
- `app.gateway.authz.PermissionProvider` (Protocol) — pluggable permission resolution backend. Registered via `set_permission_provider(provider)`; both `_authenticate()` and `AuthMiddleware.dispatch()` route through `_resolve_permissions_for_user(user)`, which delegates to the provider when registered and falls back to `_ALL_PERMISSIONS` otherwise. This single chokepoint avoids the "AuthMiddleware short-circuit" bug where decorator-level provider calls would never fire.
- Alembic env (`packages/harness/deerflow/persistence/migrations/env.py`) ImportError-tolerantly imports `deerflow.enterprise.{rbac,audit,approval}` modules so `alembic revision --autogenerate` will detect them once they land in M1/M2/M3.

**Roadmap (not yet implemented)**:
- M1 — RBAC tables, `RbacPermissionProvider`, role/permission CRUD routes
- M4 — `OIDCAuthProvider` for enterprise SSO

**Audit subsystem (M2, landed)**:

Append-only, HMAC-signed event log that records what every agent run did.
Wire-up: `enterprise.audit.enabled=true` in `config.yaml` causes the
gateway lifespan to instantiate `EnterpriseDatabase`, then
`get_enterprise_middlewares()` appends `AuditMiddleware` to every
lead-agent run. Reads are served by a dedicated router under
`/api/enterprise/audit/`.

- `enterprise.audit.events.AuditEvent` — Pydantic v2 row with `id`,
  `event_type` (`AuditEventType` enum), `timestamp` (UTC), `user_id`,
  `resource`, `action`, `details: dict`, `signature` (HMAC hex).
- `enterprise.audit.signer.AuditSigner` — HMAC-SHA256 over the row's
  canonical JSON (sorted keys, compact separators). Signed payload
  excludes only `signature` itself; `id` is included so tamper checks
  catch row-rewrite attacks. Verify uses `hmac.compare_digest`.
- `enterprise.audit.storage.AuditStorage` (ABC) →
  `SqliteAuditStorage` / `PostgresAuditStorage`. Single `audit_events`
  table shared via `deerflow.persistence.base:Base`. Indexes:
  `(user_id, timestamp)` and `(event_type, timestamp)` — the two
  hottest query shapes from the read API. SQLite backend gets WAL +
  `synchronous=NORMAL` automatically via a `connect` event listener
  in `EnterpriseDatabase`, taking append P99 from ~83 ms to ~6 ms.
- `enterprise.audit.tool_event_map.map_tool_to_event_type(tool_name)` —
  routes a sandbox/MCP/skill tool call to the right `AuditEventType`,
  returns `None` to skip (built-in conversation helpers). MCP server
  name is extracted from `mcp_<server>_<tool>` for the details payload.
- `enterprise.audit.middleware.AuditMiddleware` — emits
  `AGENT_TASK_STARTED` / `AGENT_TASK_COMPLETED` and one tool event per
  call. Signs each event before `await storage.append(event)`. Storage
  exceptions are logged and swallowed (RFC §5.4 — losing audit visibility
  is preferable to crashing the agent loop; we revisit in v2 with the
  outbox queue from the §10 backlog).
- `enterprise.middlewares.get_audit_storage` /
  `get_audit_signer` — process-wide singletons built once from
  `EnterpriseDatabase.session_factory`; clear with
  `reset_audit_singletons()` for tests.
- Alembic revision `20260518_m2_audit` creates the table + both indexes.
- Read API (mounted by lifespan, not by `create_app()` — see below):
  - `GET /api/enterprise/audit/events` — paginated list with
    `user_id` / `event_type` / `resource` / `since` / `until` / `limit` /
    `offset`. Returns `{data, total, limit, offset, has_more}`.
  - `GET /api/enterprise/audit/events/{event_id}` — single row, 404 if
    absent.
  - `GET /api/enterprise/audit/event-types` — static enum catalog for
    dashboard dropdowns.
  - `GET /api/enterprise/audit/stats` — per-event-type counts in the
    requested window (capped at 10k rows, sample-based).
  - `POST /api/enterprise/audit/verify` — recomputes HMAC for the
    sampled range; returns 503 if `sign_key` is unset rather than
    silently lying about integrity.
- All routes gated by `@require_auth @require_permission("audit", "read")`.

**Circular-import note**: the audit router transitively imports
`app.gateway.authz`, which re-enters the gateway package's `__init__`.
We therefore mount `enterprise_audit.router` inside the FastAPI
lifespan hook (after package init completes) rather than in
`create_app()`.

**Tests for M2**:
- `tests/enterprise/test_audit_signer.py` — determinism, dict order,
  tamper detection, unsigned-event verify=False, key isolation.
- `tests/enterprise/test_audit_tool_event_map.py` — parametrized
  routing for sandbox/MCP/skill tool names.
- `tests/enterprise/test_audit_storage_sqlite.py` — round-trip,
  filter combinations, `verify_integrity` happy + tamper paths.
- `tests/enterprise/test_audit_middleware.py` — abefore/aafter hook
  emission, tool wrapping, storage-failure swallowing.
- `tests/enterprise/test_audit_routes.py` — 5 routes end-to-end with
  in-memory storage + monkeypatched `_authenticate`.
- `tests/enterprise/integration/test_audit_end_to_end.py` — middleware
  → real SqliteAuditStorage → `verify_integrity` true.
- `tests/enterprise/bench_audit_append.py` — manual microbenchmark
  (1000 appends; reports min/avg/P50/P95/P99/max). With WAL pragmas
  applied by `EnterpriseDatabase`, observed P99 on Windows SQLite is
  ~6 ms — above the plan's aspirational 1 ms target, but well within
  the agent-loop budget.

**Roadmap (still not landed)**:
- M4 — `OIDCAuthProvider` for enterprise SSO

**Approval subsystem (M3 data layer, landed)**:

Human-in-the-loop guardrail for high-risk tool calls: an
`ApprovalRuleEngine` decides whether a tool invocation needs human
sign-off, the run is paused and a row is persisted, approvers are
notified out-of-band (Web SSE / Feishu / WeCom), and a background
`ApprovalTimeoutChecker` expires stale requests. **M3-8
(`ApprovalMiddleware` agent hook), M3-9 (HTTP/webhook router),
M3-10 (gateway lifespan wiring), M3-11 (true resume-run spawn +
read-path compat), and the M3 e2e integration test are all landed**.

- `enterprise.approval.models` — ORM rows (`Approval`,
  `ApprovalDecision`) + Pydantic v2 DTOs (`ApprovalDTO`,
  `ApprovalDecisionDTO`). Shared `Base` (not a new `declarative_base`).
  Enums: `ApprovalStatus` (`PENDING`/`GRANTED`/`DENIED`/`EXPIRED`/`CANCELLED`
  — `GRANTED`/`DENIED` chosen so the verb matches RBAC's
  `APPROVAL_GRANT` permission), `ApprovalAction`
  (`APPROVE`/`DENY`/`RESUBMIT`), `ApprovalUrgency`
  (`NORMAL`/`URGENT`/`CRITICAL`). Indexes: `(status, deadline)` for the
  timeout sweep, `(requested_by, requested_at)` for the per-user
  dashboard, `(thread_id, requested_at)` for the resume-on-recovery
  path. `revision_of` is a self-FK so resubmits link to the prior
  request. `action_detail` / `checkpoint` are TEXT JSON columns.
- `enterprise.approval.repository.ApprovalRepository` (ABC) →
  `SqliteApprovalRepository` / `PostgresApprovalRepository` (single
  shared `_SqlAlchemyApprovalRepository` body). `record_approval_decision`
  inserts the decision row and aggregates distinct approvers in the
  same transaction (`func.count(distinct(decided_by))` after flush),
  applying `min_approvals` atomically. `DENY` is immediately terminal,
  `RESUBMIT` is audit-only. `mark_expired` is a single UPDATE so the
  timeout sweep is race-free. Terminal-state writes raise `ValueError`;
  missing IDs raise `LookupError`.
- `enterprise.approval.engine.ApprovalRuleEngine` — pure (no DB,
  no clock) decision function over a list of `ApprovalRule`. Each rule
  declares `action_type` (prefix-matched against the tool name with
  colon boundaries — `sandbox` matches `sandbox` and `sandbox:bash`,
  not `sandboxed`), an optional Python `condition` expression evaluated
  by a hardened AST walker (`RestrictedExpressionEvaluator`) with a
  small `_ALLOWED_NODES` whitelist, `min_approvals`, `urgency`, and
  `approver_role` / `approver_users`. Subscripts are allowed but
  constrained to constant indices (rejects `x[i]` and slices) — wide
  enough for `tool_input["path"]` ergonomics, narrow enough that no
  attacker-controlled index reaches the evaluator. `eval()` runs with
  `{"__builtins__": {}}` as a defence-in-depth backstop. Broken rules
  are skipped with a warning rather than crashing the agent loop.
  Approver resolution goes through a constructor-injected `UserLookup`
  Protocol (`get_users_by_role`) so the engine never imports
  `app.UserRepository` — the app layer will pass in its own adapter.
- `enterprise.approval.checkpoint` — `STATE_FIELD_POLICY: dict[str,
  Literal["keep", "drop"]]` whitelist over every `ThreadState` field.
  `serialize_state` round-trips `keep` fields and drops the rest with
  a WARNING log for any unmapped field. A meta-test
  (`test_all_thread_state_fields_have_policy`) walks `ThreadState.__mro__`
  and fails if a new upstream field has no explicit classification —
  silent drops on resume are how you ship subtly broken state, so the
  invariant is enforced rather than documented. `keep`: `sandbox`,
  `thread_data`, `title`, `artifacts`, `todos`, `uploaded_files`.
  `drop`: `viewed_images` (megabytes of base64), `messages` /
  `remaining_steps` / `jump_to` / `structured_response` (owned by
  LangGraph / AgentState — duplicating them invites the two stores to
  disagree). `save_suspend_point` / `restore` are thin repo wrappers.
- `enterprise.approval.timeout.ApprovalTimeoutChecker` — long-lived
  `asyncio.Task` that periodically calls `repo.mark_expired(now)` and
  fans the resulting rows out to every registered notifier. Per-notifier
  `try/except` so one bad webhook does not kill the loop. `start()` /
  `close()` are both idempotent; `interval_seconds <= 0` is rejected
  at construction (catches the "0 means disabled" misconfiguration
  that would silently spin the loop).
- `enterprise.approval.notifiers` — `ApprovalNotifier` Protocol
  (`notify_requested` / `notify_decided` / `notify_expired`) with three
  implementations: `WebNotifier` puts events on a bounded
  `asyncio.Queue` (drops + warns on `QueueFull` rather than blocking
  the loop), `FeishuNotifier` posts a `msg_type=interactive` card with
  optional HMAC-SHA256 signing (`key = f"{timestamp}\n{secret}"`,
  `msg = b""`, base64 — the documented Feishu algorithm), `WecomNotifier`
  posts a `msgtype=markdown` card to a webhook URL with the secret
  embedded in the key parameter (WeCom does not sign outbound
  webhooks). Both support an `approval_url_template` for adding a
  dashboard button / link.
- `app.enterprise.webhooks.signature` — `verify_feishu` (SHA-256 hex
  over `(timestamp + nonce + encrypt_key).encode + body`) and
  `verify_wecom` (SHA-1 hex over `"".join(sorted([token, timestamp,
  nonce, body_str]))`). Both use `hmac.compare_digest`, enforce
  `MAX_SKEW_SECONDS = 300`, and accept a `now: float | None` parameter
  so tests can pin the clock. Replay protection (nonce store) is
  deliberately the router's responsibility, not the verifier's — the
  module docstring spells out why.
- Alembic revision `20260518_m3_approval` (down_revision
  `20260518_m2_audit`) creates `approvals` + `approval_decisions` and
  the four production indexes.
- `enterprise.approval.guardrail_provider.ApprovalMiddleware` —
  agent-loop hook (subclass of `langchain.agents.middleware.AgentMiddleware`,
  NOT a `GuardrailProvider`; the OSS protocol has no state input and
  cannot return `Command(goto=END)`). Per spike option (c), the
  middleware self-implements `awrap_tool_call` and pulls
  thread/user/run identifiers from `request.runtime` the same way
  `AuditMiddleware` does. Two independent paths:
    * Resume gate — checks `runtime.config["configurable"]["metadata"]["_approval_ids"]`,
      treats an entry as a bypass *only if* the matching approval row
      is `GRANTED` AND its stored `tool_input` equals the current
      call's `tool_input`. Defends against an attacker re-using a
      granted id for a different command. Reverse-evidence test:
      `test_granted_approval_for_different_tool_input_does_not_bypass`.
    * Engine call — on a fresh match, persists state via
      `save_suspend_point`, fires every registered notifier inside its
      own `try/except`, and returns `Command(goto=END,
      update={"messages": [ToolMessage(...)]} )` to pause the run.
  Engine misconfiguration fails *open* (run the tool) rather than
  closed (deny everything until config is fixed) — matches the
  `_safe_evaluate_condition` decision in the engine itself.
- `enterprise.middlewares` — extends the M2 singleton story to
  approval: `get_approval_repo` (lazy-built from
  `ApprovalRepositoryConfig`), `set_approval_user_lookup` (gateway
  registers an adapter that wraps the app-layer `UserRepository`,
  preserving the harness boundary), `set_approval_notifiers` (gateway
  passes the configured Web/Feishu/WeCom chain). Falls back to a
  `_NullUserLookup` if the gateway hasn't wired one yet so the harness
  still boots in tests.
- `enterprise.config.ApprovalRepositoryConfig` — mirrors
  `AuditStorageConfig`; defaults to `SqliteApprovalRepository` so a
  single-process deployment works with no extra config.

**Approval HTTP / webhook router (M3-9, landed)**:

Read + write HTTP API mounted at `/api/enterprise/approvals`, plus
two IM webhook endpoints for Feishu/WeCom card callbacks. All routes
are wired through `app.enterprise.deps.get_approval_repo` /
`get_approval_config` so the router and the M3-8 agent middleware
share the same row store and config tree.

- `app.enterprise.routers.approval` — 8 endpoints:
  - `GET /` — paginated list with `status` / `user_id` / `thread_id`
    filters; unknown status → 400 (the only place we surface the enum
    parse error to clients).
  - `GET /{id}` — single row; 404 on miss.
  - `POST /{id}/approve` — `@require_permission("approval", "grant")`;
    aggregates distinct approvers in `repo.record_approval_decision`,
    and on transition to `GRANTED` calls `_spawn_resume_run` to
    schedule a new run via `request.app.state.run_manager` with
    `metadata={"_approval_ids": [id]}`. `LookupError` → 404,
    `ValueError` (terminal-state guard) → 409. Response carries
    `resumed_run_id` (nullable when no `run_manager` is wired).
  - `POST /{id}/deny` — `approval:reject`; `DENY` is immediately
    terminal; no resume run.
  - `POST /{id}/resubmit` — audit-only (`approval:grant`); status
    unchanged.
  - `POST /{id}/cancel` — auth-only; the handler reads the row,
    rejects if `requested_by != ctx.user.id` (403), then issues an
    explicit `update(Approval).where(id==x, status==PENDING).values(
    status=CANCELLED, ...)` via `repo._sf()` (chosen over adding a
    one-off `cancel()` to the ABC). Non-PENDING → 409.
  - `POST /webhook/feishu`, `POST /webhook/wecom` — NO `@require_auth`;
    signature-authenticated via
    `app.enterprise.webhooks.signature.verify_feishu` /
    `verify_wecom`. Webhook secrets pulled from
    `request.app.state.approval_webhook_secrets`
    (`feishu_encrypt_key` / `wecom_token`). Missing secret → 503; bad
    sig → 401; missing fields → 400. Webhooks reuse the same
    `_record_and_respond` write path as the HTTP handlers so resume
    semantics are identical.
- `app.enterprise.deps` adds two request-scoped `Depends` helpers:
  - `get_approval_config` — 503 when approval is disabled (parallels
    `get_audit_config`).
  - `get_approval_repo` — proxies to
    `deerflow.enterprise.middlewares.get_approval_repo` so HTTP and
    middleware writes hit the same backend.

**Approval gateway lifespan wiring (M3-10, landed)**:

The gateway owns four pieces that the harness can't see: the
`UserLookup` adapter (it pulls from the app-layer users table), the
notifier chain (network-side config), the long-lived
`ApprovalTimeoutChecker`, and inbound webhook secrets. They're all
wired in one place so `app/gateway/app.py` lifespan stays free of
M3-specific imports.

- `app.enterprise.lifecycle` — owns `start_approval_subsystem(app,
  approval, *, user_repo)` and `stop_approval_subsystem(app)`. Both
  are idempotent. Each sub-step is wrapped in `try / except`; a
  failed enterprise sub-module degrades to "router returns 503"
  rather than crashing OSS chat / runs paths.
  1. **UserLookup adapter** — wraps the app-layer
     `UserRepository` in `AppUserLookup` (projects `[u.id for u in
     users]`, swallows repo exceptions to `[]`) and registers it via
     `set_approval_user_lookup`. Must run before the timeout checker
     so the engine doesn't see `_NullUserLookup`.
  2. **Notifier chain** — calls `_build_notifier(cfg)` per entry.
     `_build_notifier` resolves `cfg.use` via `resolve_class(...,
     ApprovalNotifier)` and forwards `cfg.model_dump(exclude={"use"})`
     as kwargs (Pydantic v2 `extra="allow"` carries
     `webhook_url` / `sign_secret` / `approval_url_template`
     through). Per-entry `try/except` so one bad notifier class
     doesn't break the others.
  3. **Timeout checker** — built from the same repo singleton the
     middleware writes to (`get_approval_repo`), `start()` is
     awaited, the instance is stored on
     `app.state.approval_timeout_checker` so shutdown can `close()`
     it.
  4. **Webhook secrets** — read from
     `DEER_FLOW_APPROVAL_FEISHU_ENCRYPT_KEY` /
     `DEER_FLOW_APPROVAL_WECOM_TOKEN` env vars (rotation without a
     config-file edit). Stored as `app.state.approval_webhook_secrets`
     dict — always set, possibly empty, so the router can
     distinguish "feature wired but no key" (503 per endpoint) from
     "lifespan never ran" (AttributeError, 500).
- `app.enterprise.adapters.user_lookup.AppUserLookup` — Protocol
  adapter that wraps `app.gateway.auth.repositories.SQLiteUserRepository`
  so the harness `ApprovalRuleEngine.get_users_by_role(role)` can
  return `list[str]` user ids without importing `app.*`. Exceptions
  from the repo degrade to `[]` rather than killing the engine.
- `app.gateway.deps.get_user_repo()` — exposes the cached
  `SQLiteUserRepository` instance the auth flow already builds. The
  approval lifespan reads through this so notifier-side role lookups
  share the same users table the auth flow does (no duplicate
  engine, no second cache).
- `app.gateway.app.py` lifespan — adds an M3 startup branch after
  the audit router mount: when `enterprise.approval.enabled`, calls
  `start_approval_subsystem` and `app.include_router(enterprise_
  approval.router)`. Mirror teardown branch before RBAC teardown
  calls `stop_approval_subsystem(app)` with the standard 30 s
  timeout. Errors during start log + skip the router mount; OSS
  paths remain available.
- Both router mount paths (audit at M2, approval at M3) live in
  lifespan, not `create_app()`, because importing
  `app.enterprise.routers.*` transitively imports
  `app.gateway.authz`, which re-enters the gateway package's
  `__init__`. Mounting after package init avoids the circular
  import.

**Approval resume-run spawn (M3-11, landed)**:

The approve endpoint must do more than persist a `RunRecord` — it
has to actually relaunch the agent graph so the previously-paused
tool call gets re-attempted with the granted approval id wired
into the runtime metadata. M3-11 closes that loop and fixes a
shape mismatch between the spike contract and the standard HTTP
run-create path.

- `app.enterprise.routers.approval._spawn_resume_run` — on a
  successful approve transition (`PENDING -> GRANTED`), in
  addition to `run_manager.create(...)`:
  1. Resolves the lead-agent factory via
     `services.resolve_agent_factory(None)` and normalizes a
     blank graph input via `services.normalize_input(None)` so
     the resume run starts cleanly from the checkpoint rather
     than re-feeding the original user message.
  2. Builds a `RunnableConfig` via
     `services.build_run_config(thread_id, request_config=None,
     metadata=None)`, then deep-sets
     `configurable.metadata._approval_ids` to the granted id
     (deduplicated with whatever was already there). This is the
     shape `ApprovalMiddleware._approval_ids_from_metadata`
     reads — the deep-set ensures the middleware's resume gate
     fires regardless of what `build_run_config` produced.
  3. Pulls `stream_bridge`, `run_context`, `run_manager` off
     `request.app.state` / `deps.get_run_context(...)` and
     schedules `worker.run_agent(bridge, run_mgr, record,
     ctx=..., agent_factory=..., graph_input=..., config=...)`
     via `asyncio.create_task`. The task handle is hung off
     `record.task` so the standard run lifecycle (cancel /
     join) keeps working.
  4. Best-effort fallback: any failure in the spawn block is
     logged and swallowed; the `RunRecord` row already exists
     so operators can manually trigger a resume from the
     dashboard if the launch fails (this keeps the test
     environment, which doesn't have a real graph wired,
     functional with record-only behavior).
- `deerflow.enterprise.approval.guardrail_provider._approval_ids_from_metadata`
  now accepts BOTH metadata shapes:
  - `config["configurable"]["metadata"]["_approval_ids"]` — the
    spike contract (M2.5 option c), what custom resume callers
    should target.
  - `config["metadata"]["_approval_ids"]` — what
    `app.gateway.services.build_run_config` produces when the
    HTTP run-create API forwards `body.metadata` (top-level on
    the RunnableConfig per LangGraph convention).
  Both shapes are walked, results deduplicated. This makes
  `ApprovalMiddleware` work regardless of which surface launched
  the resume run.
- Tests added (2):
  - `test_granted_approval_id_in_top_level_metadata_also_skips_engine`
    — proves the middleware accepts the HTTP shape.
  - `test_approve_spawns_resume_run_with_approval_id_in_configurable_metadata`
    — end-to-end intercept of `worker.run_agent` to verify
    `_spawn_resume_run` launches the graph with
    `configurable.metadata._approval_ids == [approval.id]`.
  Total enterprise test count: **239 passing**.

**Tests for M3 data + middleware + router + lifespan + spawn + e2e (241 passing)**:
- `tests/enterprise/test_approval_repository.py` — round-trip,
  filter combinations, decision aggregation (single / multi-approver
  threshold, duplicate decider dedup), `mark_expired` race-free path,
  terminal-state guard.
- `tests/enterprise/test_approval_engine.py` — rule matching,
  prefix-with-colon-boundary semantics, urgency selection, approver
  resolution via `UserLookup`, graceful degradation when lookup fails.
- `tests/enterprise/test_approval_engine_condition.py` — the
  `RestrictedExpressionEvaluator` whitelist: accepted shapes (literals,
  comparisons, `and`/`or`/`not`, `in`, constant-indexed subscripts) and
  rejected shapes (calls, attribute access, variable / slice
  subscripts, walrus, comprehensions); reverse-evidence test that the
  walker would crash on a payload like `__import__('os')` if the
  whitelist were widened.
- `tests/enterprise/test_approval_checkpoint.py` — meta-test over
  `ThreadState.__mro__`, `keep` / `drop` behaviour, unknown-field
  warning, full round-trip through SQLite via `save_suspend_point` →
  `restore`.
- `tests/enterprise/test_approval_timeout.py` — `_tick` fans out to
  every notifier, notifier failure isolation, `start` / `close`
  idempotency, end-to-end loop with a 1-second interval to prove the
  task actually fires.
- `tests/enterprise/test_approval_notifiers.py` — `WebNotifier`
  queue-full warning, `FeishuNotifier` payload shape (unsigned vs
  signed, cross-checked against an independent HMAC implementation),
  optional dashboard button, post-failure propagation; `WecomNotifier`
  markdown shape + dashboard link.
- `tests/enterprise/test_webhook_signature.py` — Feishu and WeCom
  signing cross-checked against second-source reference helpers
  (rejects wrong key / wrong body / wrong sort order / stale
  timestamp / non-UTF-8 body / non-numeric timestamp), and
  documents that replay protection is deliberately the router's
  responsibility.
- `tests/enterprise/test_approval_guardrail_provider.py` —
  `ApprovalMiddleware` paths: no rule match passes through, fresh
  match returns `Command(goto=END)` with the row + checkpoint + a
  notification fired, granted-id-in-metadata skips the engine,
  reverse-evidence that a granted id for a *different* `tool_input`
  does NOT skip, pending-status-id does NOT skip, notifier failure
  isolation, engine exception fails open, non-dict args coerced,
  checkpoint-write failure does not block the pause.
- `tests/enterprise/test_approval_routes.py` — 20 router tests:
  list pagination/filter/400, get hit + 404, approve happy +
  two-eyes threshold + 409 terminal + 404 missing + resume-run
  metadata round-trip, deny terminal (no resume), resubmit
  audit-only, cancel by requester + 403 for non-requester + 409 on
  non-PENDING, Feishu webhook valid/bad-sig/missing-key/missing-
  fields, WeCom webhook valid/bad-sig. Uses an in-memory repo with
  a `_StubSession` that cracks the cancel UPDATE's compiled SQL
  params instead of running a real SQLAlchemy session.
- `tests/enterprise/test_approval_lifecycle.py` — 7 lifespan
  tests: start wires `AppUserLookup` / notifier chain / timeout
  checker / webhook secrets correctly; stop closes the checker and
  clears harness singletons; stop is idempotent on a fresh app;
  empty webhook env yields `{}` not `None`; a broken notifier
  `use` path is skipped without aborting startup;
  `AppUserLookup` projects rows to `[u.id, ...]` and swallows
  repo failures to `[]`. Uses `monkeypatch` to bypass
  `resolve_class` and the harness `get_approval_repo` so tests
  don't need a real `EnterpriseDatabase`.
- `tests/enterprise/integration/test_approval_e2e.py` — 2 e2e
  tests over a real `SqliteApprovalRepository` +
  `SqliteAuditStorage` sharing one async SQLAlchemy engine.
  Happy path drives a `bash` call through `AuditMiddleware` →
  `ApprovalMiddleware` → engine intercept (pending row +
  notifier fire + `Command(goto=END)`) → repo grant → resume
  call with `_approval_ids` in `configurable.metadata` → handler
  runs, audit records `SANDBOX_COMMAND_EXECUTED`, no second
  pending row. Reverse-evidence test: a DENIED id in metadata
  does NOT bypass — a NEW pending row is created. This is the
  acceptance test for the M3 milestone.

**Tests for M0 foundation**:
- `tests/test_lead_agent_middleware_order.py` — locks the chain order contract (`custom_middlewares` injected immediately before `ClarificationMiddleware`)
- `tests/enterprise/test_authz_permission_provider.py` — covers no-provider fallback, provider override, provider call-count reverse evidence, `AuthMiddleware`/decorator short-circuit, and the `internal_auth` header branch

### Embedded Client (`packages/harness/deerflow/client.py`)

`DeerFlowClient` provides direct in-process access to all DeerFlow capabilities without HTTP services. All return types align with the Gateway API response schemas, so consumer code works identically in HTTP and embedded modes.

**Architecture**: Imports the same `deerflow` modules that Gateway API uses. Shares the same config files and data directories. No FastAPI dependency.

**Agent Conversation**:
- `chat(message, thread_id)` — synchronous, accumulates streaming deltas per message-id and returns the final AI text
- `stream(message, thread_id)` — subscribes to LangGraph `stream_mode=["values", "messages", "custom"]` and yields `StreamEvent`:
  - `"values"` — full state snapshot (title, messages, artifacts); AI text already delivered via `messages` mode is **not** re-synthesized here to avoid duplicate deliveries
  - `"messages-tuple"` — per-chunk update: for AI text this is a **delta** (concat per `id` to rebuild the full message); tool calls and tool results are emitted once each
  - `"custom"` — forwarded from `StreamWriter`
  - `"end"` — stream finished (carries cumulative `usage` counted once per message id)
- Agent created lazily via `create_agent()` + `_build_middlewares()`, same as `make_lead_agent`
- Supports `checkpointer` parameter for state persistence across turns
- `reset_agent()` forces agent recreation (e.g. after memory or skill changes)
- See [docs/STREAMING.md](docs/STREAMING.md) for the full design: why Gateway and DeerFlowClient are parallel paths, LangGraph's `stream_mode` semantics, the per-id dedup invariants, and regression testing strategy

**Gateway Equivalent Methods** (replaces Gateway API):

| Category | Methods | Return format |
|----------|---------|---------------|
| Models | `list_models()`, `get_model(name)` | `{"models": [...]}`, `{name, display_name, ...}` |
| MCP | `get_mcp_config()`, `update_mcp_config(servers)` | `{"mcp_servers": {...}}` |
| Skills | `list_skills()`, `get_skill(name)`, `update_skill(name, enabled)`, `install_skill(path)` | `{"skills": [...]}` |
| Memory | `get_memory()`, `reload_memory()`, `get_memory_config()`, `get_memory_status()` | dict |
| Uploads | `upload_files(thread_id, files)`, `list_uploads(thread_id)`, `delete_upload(thread_id, filename)` | `{"success": true, "files": [...]}`, `{"files": [...], "count": N}` |
| Artifacts | `get_artifact(thread_id, path)` → `(bytes, mime_type)` | tuple |

**Key difference from Gateway**: Upload accepts local `Path` objects instead of HTTP `UploadFile`, rejects directory paths before copying, and reuses a single worker when document conversion must run inside an active event loop. Artifact returns `(bytes, mime_type)` instead of HTTP Response. The new Gateway-only thread cleanup route deletes `.deer-flow/threads/{thread_id}` after LangGraph thread deletion; there is no matching `DeerFlowClient` method yet. `update_mcp_config()` and `update_skill()` automatically invalidate the cached agent.

**Tests**: `tests/test_client.py` (77 unit tests including `TestGatewayConformance`), `tests/test_client_live.py` (live integration tests, requires config.yaml)

**Gateway Conformance Tests** (`TestGatewayConformance`): Validate that every dict-returning client method conforms to the corresponding Gateway Pydantic response model. Each test parses the client output through the Gateway model — if Gateway adds a required field that the client doesn't provide, Pydantic raises `ValidationError` and CI catches the drift. Covers: `ModelsListResponse`, `ModelResponse`, `SkillsListResponse`, `SkillResponse`, `SkillInstallResponse`, `McpConfigResponse`, `UploadResponse`, `MemoryConfigResponse`, `MemoryStatusResponse`.

## Development Workflow

### Test-Driven Development (TDD) — MANDATORY

**Every new feature or bug fix MUST be accompanied by unit tests. No exceptions.**

- Write tests in `backend/tests/` following the existing naming convention `test_<feature>.py`
- Run the full suite before and after your change: `make test`
- Tests must pass before a feature is considered complete
- For lightweight config/utility modules, prefer pure unit tests with no external dependencies
- If a module causes circular import issues in tests, add a `sys.modules` mock in `tests/conftest.py` (see existing example for `deerflow.subagents.executor`)

```bash
# Run all tests
make test

# Run a specific test file
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

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
- Files stored in thread-isolated directories
- Duplicate filenames in a single upload request are auto-renamed with `_N` suffixes so later files do not truncate earlier files
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

See [docs/summarization.md](docs/summarization.md) for details.

### Vision Support

For models with `supports_vision: true`:
- `ViewImageMiddleware` processes images in conversation
- `view_image_tool` added to agent's toolset
- Images automatically converted to base64 and injected into state

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

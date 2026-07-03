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
│   │           ├── tools/builtins/    # Built-in tools (present_files, ask_clarification, view_image)
│   │           ├── mcp/               # MCP integration (tools, cache, client)
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
make dev        # Start all services (Gateway + Frontend + Nginx), with config.yaml preflight
make start      # Start production services locally
make stop       # Stop all services
```

**Backend directory** (for backend development only):
```bash
make install            # Install backend dependencies
make dev                # Run Gateway API with reload (port 8001)
make gateway            # Run Gateway API only (port 8001)
make test               # Run all backend tests
make test-blocking-io   # Run strict Blockbuster runtime gate on tests/blocking_io/
make lint               # Lint with ruff
make format             # Format code with ruff
make migrate-rev MSG="..."  # Autogenerate a new alembic revision (see Schema Migrations section)
```

The `detect-blocking-io` target parses `app/`, `packages/harness/deerflow/`,
and `scripts/` with AST. By default it reports only blocking IO candidates that
are inside async code, reachable from async code in the same file, or reachable
from sync-only `AgentMiddleware` before/after hooks that LangGraph can execute
on the async graph path. It prints a concise summary and writes complete JSON
findings to `.deer-flow/blocking-io-findings.json` at the repository root
(both `make detect-blocking-io` from the repo root and `cd backend && make
detect-blocking-io` resolve to the same repo-root path). JSON findings include
`priority`, `location`, `blocking_call`, `event_loop_exposure`, `reason`, and
`code` for model-assisted or manual review. `priority` is a deterministic
review ordering from operation type, not proof of a bug. Bare-name same-file
calls are resolved by function name, so duplicate helper names in one file can
conservatively over-report async reachability. It is intentionally
informational and is not run from CI in this round.

For a diff-scoped view of the same findings, `scripts/scan_changed_blocking_io.py`
(repo root) reports findings on the added lines of `git diff <base>...HEAD`
plus findings new versus the merge base (so a new async caller exposing an
untouched sync helper in the same file is still reported) — used by the
`blocking-io-guard` skill (`.agent/skills/blocking-io-guard/`) as the
deterministic scope step before routing each candidate to a fix and/or a
`tests/blocking_io/` runtime anchor.

Regression tests related to Docker/provisioner behavior:
- `tests/test_docker_sandbox_mode_detection.py` (mode detection from `config.yaml`)
- `tests/test_provisioner_kubeconfig.py` (kubeconfig file/directory handling)

Blocking-IO runtime gate (`tests/blocking_io/`):
- Wraps every item under `tests/blocking_io/` with a strict Blockbuster
  context scoped to `app.*` and `deerflow.*` (see
  `tests/support/detectors/blocking_io_runtime.py`). Any sync blocking IO
  call whose stack passes through DeerFlow business code while running on
  the asyncio event loop raises `BlockingError` and fails the test.
- Regression anchors live there: `test_skills_load.py` (locks the
  `asyncio.to_thread` offload around `LocalSkillStorage.load_skills`, fix
  for #1917); `test_sqlite_lifespan.py` (locks the offload around
  SQLite path resolution plus `ensure_sqlite_parent_dir`, fix for #1912);
  `test_jsonl_run_event_store.py` (locks `JsonlRunEventStore`'s async
  API offloading its file IO via `asyncio.to_thread`, fix #3084); and
  `test_uploads_middleware.py` (locks `UploadsMiddleware.abefore_agent`
  offloading the uploads-directory scan off the event loop).
- `test_gate_smoke.py` is a meta-test asserting the gate actually catches
  unoffloaded blocking IO and that the `@pytest.mark.allow_blocking_io`
  opt-out works.
- Coverage boundary: the gate only sees code that test execution actually
  touches. Static AST coverage is a separate concern (out of scope for
  this PR).
- CI: runs on every PR via `.github/workflows/backend-blocking-io-tests.yml`,
  hard-fail.

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
- Extends `AgentState` with: `sandbox`, `thread_data`, `title`, `artifacts`, `todos`, `uploaded_files`, `viewed_images`, `goal`, `promoted`, `delegations`, `skill_context`, `summary_text`
- Uses custom reducers: `merge_artifacts` (deduplicate), `merge_viewed_images` (merge/clear), `merge_goal` (preserve the active goal across ordinary state updates unless the goal writer replaces it), `merge_promoted` (catalog-hash-scoped deferred tool promotions), `merge_delegations` (append task delegation entries, same id latest wins, terminal status never downgraded, capped to the most recent entries), and `merge_skill_context` (dedupe active-skill references by path, keep the most recently read entries; entries store a name/path/description reference, not the SKILL.md body). `summary_text` is a LastValue channel updated by summarization and projected into model requests as durable context data instead of being stored as a `messages` item.

**Runtime Configuration** (via `config.configurable`):
- `thinking_enabled` - Enable model's extended thinking
- `model_name` - Select specific LLM model
- `is_plan_mode` - Enable TodoList middleware
- `subagent_enabled` - Enable task delegation tool

### Middleware Chain

Lead-agent middlewares are assembled in strict order across three functions: the shared base in `packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` (`_build_runtime_middlewares`, exposed via `build_lead_runtime_middlewares`), then the lead-only middlewares appended in `packages/harness/deerflow/agents/lead_agent/agent.py` (`build_middlewares`). Items marked *(optional)* are appended only when their config/runtime condition holds, so the live chain length varies.

**Shared runtime base** (`build_lead_runtime_middlewares`; subagents reuse most of this via `build_subagent_runtime_middlewares`):

1. **InputSanitizationMiddleware** - First, so it is the outermost `wrap_model_call` wrapper; every inner middleware (including LLM retries) sees sanitized messages
2. **ToolOutputBudgetMiddleware** - Caps tool output size (per app config) before it re-enters the model context
3. **ThreadDataMiddleware** - Creates per-thread directories under the user's isolation scope (`backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`); resolves `user_id` via `get_effective_user_id()` (falls back to `"default"` in no-auth mode)
4. **UploadsMiddleware** - Tracks and injects newly uploaded files into conversation (lead agent only)
5. **SandboxMiddleware** - Acquires sandbox, stores `sandbox_id` in state
6. **DanglingToolCallMiddleware** - Injects placeholder ToolMessages for AIMessage tool_calls that lack responses (e.g., user interruption), preserving raw provider tool-call payloads in `additional_kwargs["tool_calls"]`
7. **LLMErrorHandlingMiddleware** - Normalizes provider/model invocation failures into recoverable assistant-facing errors before later stages run
8. **GuardrailMiddleware** - *(optional, if `guardrails.enabled`)* Pre-tool-call authorization via pluggable `GuardrailProvider`; returns an error ToolMessage on deny. Providers: built-in `AllowlistProvider` (zero deps), OAP policy providers (e.g. `aport-agent-guardrails`), or custom. See [docs/GUARDRAILS.md](docs/GUARDRAILS.md)
9. **SandboxAuditMiddleware** - Audits sandboxed shell/file operations for security logging before tool execution
10. **ToolErrorHandlingMiddleware** - Converts tool exceptions into error `ToolMessage`s so the run can continue instead of aborting

**Lead-only middlewares** (`build_middlewares`, appended after the base):

11. **DynamicContextMiddleware** - Injects the current date (and optionally memory) as a `<system-reminder>` into the first HumanMessage, keeping the base system prompt fully static for prefix-cache reuse
12. **SkillActivationMiddleware** - Detects strict `/skill-name task` syntax on the latest real user message, resolves only enabled and runtime-allowed skills, injects the `SKILL.md` body as hidden current-turn context, and records a `middleware:skill_activation` audit event
13. **DurableContextMiddleware** - Captures `task` delegations into `ThreadState.delegations` (including in-progress dispatches and terminal result summaries) and loaded skill-file references (name/path/description, parsed in-memory - not the body) into `ThreadState.skill_context` before summarization can compact the paired tool-call/result messages, then projects durable context into each model request. Static authority rules are injected as a `SystemMessage`; untrusted field values (`summary_text`, delegation results, skill descriptions) are injected separately as a hidden `HumanMessage` data block so compressed history, delegated work, and which skills are active stay visible without being stored as `messages` or promoted to system-role instructions.
14. **SummarizationMiddleware** - *(optional, if enabled)* Context reduction when approaching token limits
15. **TodoListMiddleware** - *(optional, if `is_plan_mode`)* Task tracking with the `write_todos` tool
16. **TokenUsageMiddleware** - *(optional, if `token_usage.enabled`)* Records token usage metrics; subagent usage is merged back into the dispatching AIMessage by message position
17. **TitleMiddleware** - Auto-generates the thread title after the first complete exchange and normalizes structured message content before prompting the title model. If a first-turn run is interrupted before this middleware can write a title, `runtime/runs/worker.py` keeps the run in a finalizing state, persists a local fallback title from the latest checkpoint or original run input, and then syncs it to `threads_meta.display_name`. Replacement runs admitted by `multitask_strategy="interrupt"` / `"rollback"` wait for older same-thread finalization before entering the graph; the interrupted run only skips the fallback title write once a later run has started and may have advanced the checkpoint.
18. **MemoryMiddleware** - Queues conversations for async memory update (filters to user + final AI responses)
19. **ViewImageMiddleware** - *(optional, if the model supports vision)* Injects base64 image data before the LLM call
20. **DeferredToolFilterMiddleware** - *(optional, if `tool_search.enabled`)* Hides deferred (MCP) tool schemas from the bound model until `tool_search` promotes them (reads per-thread promotions from `ThreadState.promoted`, hash-scoped)
21. **SystemMessageCoalescingMiddleware** - Merges every SystemMessage into a single leading SystemMessage per request; provider-agnostic fix for strict backends (vLLM/SGLang/Qwen/Anthropic) that reject non-leading system messages. Touches the per-request payload only (checkpoint state unchanged); on midnight crossings only the latest `dynamic_context_reminder` SystemMessage survives
22. **SubagentLimitMiddleware** - *(optional, if `subagent_enabled`)* Truncates excess `task` tool calls to enforce the `MAX_CONCURRENT_SUBAGENTS` limit
23. **LoopDetectionMiddleware** - *(optional, if `loop_detection.enabled`)* Detects repeated tool-call loops; hard-stop clears both structured `tool_calls` and raw provider tool-call metadata before forcing a final text answer
24. **TokenBudgetMiddleware** - *(optional, if `token_budget.enabled`)* Enforces per-run token limits
25. **Custom middlewares** - *(optional)* Any `custom_middlewares` passed to `build_middlewares` are injected here, before the safety/clarification tail
26. **SafetyFinishReasonMiddleware** - *(optional, if `safety_finish_reason.enabled`)* Suppresses tool execution when the provider safety-terminated the response (e.g. `finish_reason=content_filter`); registered after custom middlewares so LangChain's reverse-order `after_model` dispatch runs it first
27. **ClarificationMiddleware** - Intercepts `ask_clarification` tool calls, interrupts via `Command(goto=END)` (must be last)

### Configuration System

**Main Configuration** (`config.yaml`):

Setup: Copy `config.example.yaml` to `config.yaml` in the **project root** directory.

**Config Versioning**: `config.example.yaml` has a `config_version` field. On startup, `AppConfig.from_file()` compares user version vs example version and emits a warning if outdated. Missing `config_version` = version 0. Run `make config-upgrade` to auto-merge missing fields. When changing the config schema, bump `config_version` in `config.example.yaml`.

**Config Caching**: `get_app_config()` caches the parsed config, but automatically reloads it when the resolved config path or file content signature changes. The signature includes file metadata and a content digest, so Gateway and LangGraph reads stay aligned with `config.yaml` edits even on object-store or network mounts where mtime can remain stale.

**Config Hot-Reload Boundary**: Gateway dependencies route through `get_app_config()` on every request, so per-run fields like `models[*].max_tokens`, `summarization.*`, `title.*`, `memory.*`, `subagents.*`, `tools[*]`, and the agent system prompt pick up `config.yaml` edits on the next message. `AppConfig` is intentionally **not** cached on `app.state` — `lifespan()` keeps a local `startup_config` variable for one-shot bootstrap work and passes it to `langgraph_runtime(app, startup_config)`.

Infrastructure fields are **restart-required**. The authoritative list lives in `packages/harness/deerflow/config/reload_boundary.py::STARTUP_ONLY_FIELDS` and is mirrored by the standardised `"startup-only:"` prefix on the corresponding `Field(description=...)` in `AppConfig`, so IDE hover on those fields surfaces the reason inline (no need to context-switch into this table). Currently registered: `database`, `checkpointer`, `run_events`, `stream_bridge`, `sandbox`, `log_level`, `logging`, `channels`, `channel_connections`. Adding a new restart-required field requires updating the registry; drift is pinned by `tests/test_reload_boundary.py`.

**Persistence backend resolution**: the unified `database` section selects the
Gateway's LangGraph checkpointer, LangGraph Store, and DeerFlow SQL repositories.
The deprecated `checkpointer` section remains backward compatible and, when
present, overrides `database` for the LangGraph checkpointer and Store only;
application repositories continue to use `database`.

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
| **Features** (`/api/features`) | `GET /` - report config-gated feature availability (currently `agents_api.enabled`) for frontend UI gating |
| **MCP** (`/api/mcp`) | `GET /config` - get config; `PUT /config` - update config (saves to extensions_config.json) |
| **Skills** (`/api/skills`) | `GET /` - list skills; `GET /{name}` - details; `PUT /{name}` - update enabled; `POST /install` - install from .skill archive (accepts standard optional frontmatter like `version`, `author`, `compatibility`) |
| **Memory** (`/api/memory`) | `GET /` - memory data; `POST /reload` - force reload; `GET /config` - config; `GET /status` - config + data |
| **Uploads** (`/api/threads/{id}/uploads`) | `POST /` - upload files (auto-converts PDF/PPT/Excel/Word); `GET /list` - list; `DELETE /{filename}` - delete |
| **Threads** (`/api/threads/{id}`) | `DELETE /` - remove DeerFlow-managed local thread data after LangGraph thread deletion; `GET /goal`, `PUT /goal`, `DELETE /goal` - read, set, and clear the active thread goal; unexpected failures are logged server-side and return a generic 500 detail |
| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - serve artifacts; active content types (`text/html`, `application/xhtml+xml`, `image/svg+xml`) are always forced as download attachments to reduce XSS risk; `?download=true` still forces download for other file types |
| **Suggestions** (`/api/suggestions`) | `GET /config` - returns global suggestions config boolean; `POST /threads/{id}/suggestions` - generate follow-up questions; rich list/block model content is normalized and inline reasoning (`<think>...</think>`, including unclosed/truncated blocks from reasoning models like MiniMax-M3) is stripped before JSON parsing |
| **Thread Runs** (`/api/threads/{id}/runs`) | `POST /` - create background run; `POST /stream` - create + SSE stream; `POST /wait` - create + block; `POST /regenerate/prepare` - prepare clean input + checkpoint metadata for regenerating the latest assistant answer; `GET /` - list runs; `GET /{rid}` - run details; `POST /{rid}/cancel` - cancel; `GET /{rid}/join` - join SSE; `GET /{rid}/messages` - paginated messages `{data, has_more}`; `GET /{rid}/events` - full event stream; `GET /../messages` - thread messages with feedback; `GET /../token-usage` - aggregate tokens |
| **Feedback** (`/api/threads/{id}/runs/{rid}/feedback`) | `PUT /` - upsert feedback; `DELETE /` - delete user feedback; `POST /` - create feedback; `GET /` - list feedback; `GET /stats` - aggregate stats; `DELETE /{fid}` - delete specific |
| **Runs** (`/api/runs`) | `POST /stream` - stateless run + SSE; `POST /wait` - stateless run + block; `GET /{rid}/messages` - paginated messages by run_id `{data, has_more}` (cursor: `after_seq`/`before_seq`); `GET /{rid}/feedback` - list feedback by run_id |

**RunManager / RunStore contract**:
- `RunManager.get()` is async; direct callers must `await` it.
- When a persistent `RunStore` is configured, `get()` and `list_by_thread()` hydrate historical runs from the store. In-memory records win for the same `run_id` so task, abort, and stream-control state stays attached to active local runs.
- `cancel()` and `create_or_reject(..., multitask_strategy="interrupt"|"rollback")` persist interrupted status through `RunStore.update_status()`, matching normal `set_status()` transitions.
- Store-only hydrated runs are readable history. If the current worker has no in-memory task/control state for that run, cancellation APIs can return 409 because this worker cannot stop the task.
- `POST /wait` (both thread-scoped and `/api/runs/wait`) drains the stream bridge via `wait_for_run_completion()` instead of bare `await record.task`, so it honours the run's `on_disconnect` setting and cancels the background run on real client disconnect rather than returning a stale checkpoint (issue #3265).
- Thread-scoped run creation accepts `checkpoint` / `checkpoint_id`; Gateway validates the checkpoint belongs to the request thread before writing `checkpoint_id` / `checkpoint_ns` into `config.configurable` for LangGraph branching.
- Thread-scoped Gateway runs evaluate an active `ThreadState.goal` after the visible turn completes. `runtime/goal.py` asks a non-thinking evaluator model to judge only visible conversation evidence and return a typed blocker; the evaluator model is created once per run and reused across hidden continuation checks. Satisfied goals are cleared; every non-satisfied evaluation — continuable or stand-down — is persisted with `last_evaluation` (the blocker, reason, and evidence summary; outcomes that stop the loop additionally record a `stand_down_reason` for observability), but only `goal_not_met_yet` evaluations are streamed as hidden `HumanMessage` continuations, and only when a durable assistant end-of-turn checkpoint exists, the run has not been aborted, the thread did not change during evaluation, and the no-progress breaker has not fired. The continuation cap is 8 — a hard maximum in the `0`–`8` range; callers requesting more are clamped (`set_goal`/TUI) or rejected with 422 (`PUT /goal`). The no-progress breaker keys on the latest visible assistant evidence (not the evaluator's free-text reason, which an LLM rewords every turn), so two consecutive continuations that add no new visible assistant output stop the loop after 2 attempts. Model-response cleanup helpers such as think-block stripping and code-fence stripping live in `deerflow.utils.llm_text` so `runtime/goal.py` and Gateway suggestion parsing share the same JSON-prep behavior.

Proxied through nginx: `/api/langgraph/*` → Gateway LangGraph-compatible runtime, all other `/api/*` → Gateway REST APIs.

### Sandbox System (`packages/harness/deerflow/sandbox/`)

**Interface**: Abstract `Sandbox` with `execute_command(command, env=None)`, `read_file`, `write_file`, `list_dir`. The optional `env` injects per-call environment variables (request-scoped secrets — see Request-Scoped Secrets below); `LocalSandbox` merges it via `subprocess.run(env=...)` and `AioSandbox` routes env-bearing commands through the `bash.exec(env=...)` API on a fresh session.
**Provider Pattern**: `SandboxProvider` with `acquire`, `acquire_async`, `get`, `release` lifecycle. Async agent/tool paths call async sandbox lifecycle hooks so Docker sandbox creation, discovery, cross-process locking, readiness polling, and release stay off the event loop.
**Environment policy** (`sandbox/env_policy.py`): `execute_command` no longer inherits the full `os.environ`. `build_sandbox_env()` scrubs secret-looking names (`*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASSWORD*`/`*CREDENTIAL*`) from the inherited environment before layering injected request secrets on top, so platform credentials (e.g. `OPENAI_API_KEY`) never leak into skill subprocesses. Benign vars (`PATH`, `HOME`, `LANG`, `VIRTUAL_ENV`, ...) are preserved.
**Implementations**:
- `LocalSandboxProvider` - Local filesystem execution. `acquire(thread_id)` returns a per-thread `LocalSandbox` (id `local:{thread_id}`) whose `path_mappings` resolve `/mnt/user-data/{workspace,uploads,outputs}` and `/mnt/acp-workspace` to that thread's host directories, so the public `Sandbox` API honours the `/mnt/user-data` contract uniformly with AIO. `acquire()` / `acquire(None)` keeps the legacy generic singleton (id `local`) for callers without a thread context. Per-thread sandboxes are held in an LRU cache (default 256 entries) guarded by a `threading.Lock`.
- `AioSandboxProvider` (`packages/harness/deerflow/community/`) - Docker-based isolation. Active-cache and warm-pool entries are checked with the backend during acquire/reuse; definitively dead containers are dropped from all in-process maps so the thread can discover or create a fresh sandbox instead of reusing a stale client. Backend health-check failures are treated as unknown, not dead; local discovery likewise treats an unverifiable container as not adoptable and falls through to create rather than failing acquire. `get()` remains an in-memory lookup for event-loop-safe tool paths.

**Virtual Path System**:
- Agent sees: `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`
- Physical: `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`, `deer-flow/skills/`
- Translation: `LocalSandboxProvider` builds per-thread `PathMapping`s for the user-data prefixes at acquire time; `tools.py` keeps `replace_virtual_path()` / `replace_virtual_paths_in_command()` as a defense-in-depth layer (and for path validation). AIO has the directories volume-mounted at the same virtual paths inside its container, so both implementations accept `/mnt/user-data/...` natively.
- Detection: `is_local_sandbox()` accepts both `sandbox_id == "local"` (legacy / no-thread) and `sandbox_id.startswith("local:")` (per-thread)

**Sandbox Tools** (in `packages/harness/deerflow/sandbox/tools.py`):
- `bash` - Execute commands with path translation and error handling. For `LocalSandbox` (host bash), POSIX output is captured through bounded pipe-drain threads and stdin is `/dev/null`, so a backgrounded long-lived process (`server &`) returns immediately instead of blocking the turn on an inherited pipe, while unredirected background output is drained without growing anonymous temp files. Commands that read stdin get immediate EOF. The command runs in its own process group with a wall-clock timeout (`sandbox.bash_command_timeout`, default 600s); on timeout the whole group is killed and the agent gets a notice telling it to background long-lived processes. The bash tool description itself also instructs the model to background long-lived processes (e.g. servers) up front so it doesn't waste the turn waiting on a foreground server. See `LocalSandbox.execute_command` / `_run_posix_command` and `bash_tool`'s docstring.
- `ls` - Directory listing (tree format, max 2 levels)
- `read_file` - Read file contents with optional line range
- `write_file` - Write/append to files, creates directories; overwrites by default and exposes the `append` argument in the model-facing schema for end-of-file writes
- `str_replace` - Substring replacement (single or all occurrences); same-path serialization is scoped to `(sandbox.id, path)` so isolated sandboxes do not contend on identical virtual paths inside one process

### Subagent System (`packages/harness/deerflow/subagents/`)

**Built-in Agents**: `general-purpose` (all tools except `task`) and `bash` (command specialist)
**Execution**: Dual thread pool - `_scheduler_pool` (3 workers) + `_execution_pool` (3 workers)
**Concurrency**: `MAX_CONCURRENT_SUBAGENTS = 3` enforced by `SubagentLimitMiddleware` (truncates excess tool calls in `after_model`); default subagent timeout `subagents.timeout_seconds=1800` (30 min) and built-in `general-purpose` `max_turns=150` (raised from 100/15-min so deep-research subtasks stop hitting `GraphRecursionError` out of the box)
**Flow**: `task()` tool → `SubagentExecutor` → background thread → poll 5s → SSE events → result
**Events**: `task_started`, `task_running`, `task_completed`/`task_failed`/`task_timed_out`
**Step capture & persistence (#3779)**: `executor.py` captures both assistant turns (`AIMessage`) **and** tool outputs (`ToolMessage`) via `subagents/step_events.py::capture_new_step_messages`, which walks the *newly-appended tail* of each `stream_mode="values"` chunk (not just `messages[-1]`) so a multi-tool-call turn — where LangGraph's `ToolNode` appends several `ToolMessage`s in one super-step — keeps every tool output instead of dropping all but the last. `runtime/runs/worker.py::_SubagentEventBuffer` additionally persists these `task_*` custom events to the `RunEventStore` as `subagent.start`/`subagent.step`/`subagent.end` (`category="subagent"`, `task_id` in `metadata`). It **batches** writes via `put_batch` (flushing on a terminal `subagent.end`, at `FLUSH_THRESHOLD` events, and in the worker's `finally`) rather than one `put()` per step, since `put()` is a documented low-frequency path (per-thread advisory lock per call) and a deep subagent (`max_turns=150`) emits hundreds of steps on the hot stream loop. `build_subagent_step` caps both the per-step `text` and each tool call's serialized `args` at `SUBAGENT_STEP_MAX_CHARS` (flagged `truncated` / `args_truncated`) so a large `write_file`/`bash` payload can't produce an unbounded row. The dedicated category keeps them out of `list_messages` (the thread feed) while `list_events` returns them for the frontend's fetch-on-expand backfill. `list_events` accepts `task_id` (filters on `metadata["task_id"]` — SQL-side in `DbRunEventStore` via `event_metadata["task_id"].as_string()`, in-memory in the JSONL/memory stores) plus an `after_seq` forward cursor, so the card pages through one subagent's steps without the run-wide `limit` truncating the tail (no schema migration: the filter rides the existing run-scoped index). `step_events.py` is a pure, unit-tested layer (`build_subagent_step` / `subagent_run_event`).
**Deferred MCP tools** (if `tool_search.enabled`): `SubagentExecutor._build_initial_state` assembles deferral after policy filtering via the shared `assemble_deferred_tools` (fail-closed), appends the `tool_search` tool, injects the `<available-deferred-tools>` section into the subagent's `SystemMessage`, and threads the setup to `_create_agent`, which attaches `DeferredToolFilterMiddleware` through `build_subagent_runtime_middlewares(deferred_setup=...)`. Subagents thus withhold full MCP schemas until promotion, same as the lead agent; each task run gets a fresh `ThreadState` so promotion is isolated per run
**Checkpointer isolation**: Subagent graphs are compiled with `checkpointer=False` to avoid inheriting the parent run's checkpointer, since subagents are one-shot and never resume.

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

**Community tools** (`packages/harness/deerflow/community/`): optional integrations, each in its own subpackage and wired through `config.yaml`. Documented examples:
- `tavily/` - Web search (5 results default) and web fetch (4KB limit)
- `jina_ai/` - Web fetch via Jina reader API with readability extraction
- `firecrawl/` - Web scraping via Firecrawl API
- `image_search/` - Image search
- `aio_sandbox/` - Docker-based isolation (`AioSandboxProvider`)

Additional providers also live here (`brave`, `browserless`, `crawl4ai`, `ddg_search`, `exa`, `fastcrw`, `groundroute`, `infoquest`, `searxng`, `serper`); see each subpackage for specifics.

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
- **Stdio file outputs**: Persistent stdio sessions are scoped by `user_id:thread_id`. For stdio transports only, DeerFlow pins the subprocess default `cwd` to the thread workspace and `TMPDIR`/`TMP`/`TEMP` to `workspace/.mcp/tmp/`, unless the operator explicitly configured `cwd` or temp env values. SSE/HTTP transports skip this filesystem prep entirely.
- **Stdio path translation**: MCP-returned local file references are not copied. If a `ResourceLink` or conservative free-text path resolves to an existing file inside the thread's mounted user-data tree, it is translated deterministically to `/mnt/user-data/...`; paths outside that tree remain unchanged.
- **Runtime updates**: Gateway API saves to extensions_config.json; the Gateway-embedded runtime detects changes via mtime

### Skills System (`packages/harness/deerflow/skills/`)

- **Location**: `deer-flow/skills/{public,custom}/`
- **Format**: Directory with `SKILL.md` (YAML frontmatter: name, description, license, allowed-tools, required-secrets)
- **Loading**: `load_skills()` recursively scans `skills/{public,custom}` for `SKILL.md`, parses metadata, and reads enabled state from extensions_config.json
- **Injection**: Enabled skills listed in agent system prompt with container paths
- **Slash activation**: `/skill-name task` loads that enabled skill's `SKILL.md` for the current model call only. The resolver rejects leading whitespace, missing separators, reserved channel commands (`/new`, `/help`, `/bootstrap`, `/status`, `/models`, `/memory`, `/goal`), disabled skills, and skills outside a custom agent's whitelist.
- **Installation**: `POST /api/skills/install` extracts .skill ZIP archive to custom/ directory

#### Request-Scoped Secrets (`required-secrets`)

Lets a caller pass per-request, short-lived end-user credentials (e.g. an ERP token) to a skill's sandbox scripts without the value entering the prompt, tool arguments, the executed command string, or traces (issue #3861).

- **Declare**: a skill lists the secrets it needs in `SKILL.md` frontmatter — `required-secrets:` as a string list or `{name, optional}` mappings. `name` is both the lookup key and the env var name exposed to scripts. Parsed by `skills/parser.py::parse_required_secrets` into `Skill.required_secrets` (`SecretRequirement`); malformed entries are dropped with a warning.
- **Carry**: the caller sends values out-of-band in the run request's `context.secrets` mapping (never a message). `runtime/secret_context.py` owns the contract (`SECRETS_CONTEXT_KEY`, `extract_request_secrets`). The existing `context` passthrough carries it to `runtime.context` without mirroring into `configurable`. `build_run_config` still sets `configurable.thread_id` on the context path — the checkpointer requires it.
- **Bind (point A)**: on slash-activation, `SkillActivationMiddleware._apply_skill_secrets` resolves the activated skill's declared secrets against `context.secrets` and writes the per-run injection set to `runtime.context[__active_skill_secrets]`. Slash activation reads the genuine user text via `get_original_user_content_text`; `InputSanitizationMiddleware` preserves it (`ORIGINAL_USER_CONTENT_KEY`) when it wraps input in BEGIN/END markers, so activation fires even after sanitization. The injected value always comes from the caller's request, never the host environment (scrubbed first — see below), so a declared name that also exists in the host env is safe: the caller's value wins and the host value is dropped (the #3861 per-user-key-overrides-shared-key case). Missing required secrets are logged, not injected.
- **Inject**: `bash_tool` reads the injection set and passes it as `execute_command(env=...)`. Scope is the activation turn/run only — a run without `/skill` activation injects nothing.
- **Inherited-env scrub**: `execute_command` no longer leaks the Gateway's `os.environ` to skill subprocesses — `env_policy.build_sandbox_env` drops secret-looking names (`*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASSWORD*`/`*CREDENTIAL*`/`*DSN*` + a connection-string denylist like `DATABASE_URL`/`REDIS_URL`/`GH_PAT`) so platform credentials never reach a skill; a skill that needs one must declare it.
- **Leak surfaces sealed** (verified by a real-gateway e2e run — secret reaches the sandbox but none of these): prompt (value never in a message), trace (`tracing/metadata.py` never copies `context`), checkpoint (secrets live on `runtime.context`, not graph state), audit (journal records names only), stdout (`tools.py::mask_secret_values` redacts injected values from bash output), and **run-record persistence + run API** (`services.py::start_run` stores `redact_config_secrets(body.config)` so `runs.kwargs_json` and `RunResponse.kwargs` never carry the secret).
- **Scope / non-goals**: only `/slash`-activated skills receive secrets (autonomously invoked enabled skills do not); no persistence/vaulting; the MCP per-user-credential gap (#3322) is a sibling, not covered here. Tests: `tests/test_skill_request_scoped_secrets.py`.

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

Bridges external messaging platforms (Feishu, Slack, Telegram, Discord, DingTalk) to the DeerFlow agent via Gateway's LangGraph-compatible API.

**Architecture**: Channels communicate with Gateway through the `langgraph-sdk` HTTP client (same as the frontend), ensuring threads are created and managed server-side. The internal SDK client injects process-local internal auth plus a matching CSRF cookie/header pair so Gateway accepts state-changing thread/run requests from channel workers without relying on browser session cookies.

**Components**:
- `message_bus.py` - Async pub/sub hub (`InboundMessage` → queue → dispatcher; `OutboundMessage` → callbacks → channels)
- `store.py` - JSON-file persistence mapping `channel_name:chat_id[:topic_id]` → `thread_id` (keys are `channel:chat` for root conversations and `channel:chat:topic` for threaded conversations)
- `manager.py` - Core dispatcher: creates threads via `client.threads.create()`, routes commands including `/goal` (setting a goal persists it through Gateway and then routes the objective as a chat turn), keeps Slack/Discord on `client.runs.wait()`, and uses `client.runs.stream(["messages-tuple", "values"])` for Feishu/Telegram incremental outbound updates
- `base.py` - Abstract `Channel` base class (start/stop/send lifecycle)
- `service.py` - Manages lifecycle of all configured channels from `config.yaml`
- `slack.py` / `feishu.py` / `telegram.py` / `discord.py` / `dingtalk.py` - Platform-specific implementations (`feishu.py` tracks the running card `message_id` in memory and patches the same card in place; `telegram.py` registers the "Working on it..." placeholder as the stream target and edits it in place via `editMessageText`; `dingtalk.py` optionally uses AI Card streaming for in-place updates when `card_template_id` is configured)
- `app/gateway/routers/channel_connections.py` - Browser-facing user connection and disconnect APIs
- `deerflow.persistence.channel_connections` - SQL-backed user-owned connection, optional credential, connect state, and conversation store

**Message Flow**:
1. External platform -> Channel impl -> `MessageBus.publish_inbound()`
2. `ChannelManager._dispatch_loop()` consumes from queue
3. For user-owned channel connections, incoming messages carry `connection_id`, `owner_user_id`, and `workspace_id`; `owner_user_id` becomes the DeerFlow run `user_id`, while the raw platform user id remains `channel_user_id`
4. For chat: look up/create thread through Gateway's LangGraph-compatible API
5. Feishu/Telegram chat: `runs.stream()` → accumulate AI text → publish multiple outbound updates (`is_final=False`) → publish final outbound (`is_final=True`)
6. Slack/Discord chat: `runs.wait()` → extract final response → publish outbound
7. Feishu channel sends one running reply card up front, then patches the same card for each outbound update (card JSON sets `config.update_multi=true` for Feishu's patch API requirement)
8. Telegram streaming: the "Working on it..." placeholder message is registered as the stream target; non-final updates `editMessageText` it in place (channel-side throttle: 1s in private chats, 3s in groups due to Telegram's 20 msg/min group cap; 4096-char truncation; rate-limited updates dropped); the final update performs the last edit and splits >4096 texts into follow-up messages
9. DingTalk AI Card mode (when `card_template_id` configured): `runs.stream()` → create card with initial text → stream updates via `PUT /v1.0/card/streaming` → finalize on `is_final=True`. Falls back to `sampleMarkdown` if card creation or streaming fails
10. For commands (`/new`, `/status`, `/models`, `/memory`, `/goal`, `/help`): handle locally or query Gateway API
11. Outbound → channel callbacks → platform reply

**Owner-scoped file storage**: inbound files, uploads, and output artifacts are staged under the DeerFlow owner's bucket so they land where the agent run reads/writes (`users/{user_id}/threads/{thread_id}/user-data/{uploads,outputs}`). `ChannelManager._handle_chat` resolves the storage owner once via `_channel_storage_user_id(msg)` (sanitized owner id, falling back to `safe(msg.user_id)` for unbound auth-enabled channels — mirroring `_resolve_run_params`'s run identity; `None` only when no identity is available) and threads it as the `user_id=` kwarg through the file pipeline:
- `Channel.receive_file(msg, thread_id, user_id=...)` — owner-bound channels persist downloaded files under the owner's bucket instead of the default bucket
- `_ingest_inbound_files(...)` and the underlying `ensure_uploads_dir` / `get_uploads_dir` — owner-scoped via the same kwarg
- `_resolve_attachments` / `_prepare_artifact_delivery` — resolve output artifacts from the bound owner's bucket
The cached value is reused for both the blocking (`runs.wait`) and streaming (`_handle_streaming_chat`) paths, so uploads and artifact delivery always target the same bucket even if a channel returns a rewritten `InboundMessage` from `receive_file`. The bucket id matches the memory bucket resolved by `_resolve_memory_user_id` (both normalize through `make_safe_user_id`).

**Configuration** (`config.yaml` -> `channels`):
- `langgraph_url` - LangGraph-compatible Gateway API base URL (default: `http://localhost:8001/api`)
- `gateway_url` - Gateway API URL for auxiliary commands (default: `http://localhost:8001`)
- In Docker Compose, IM channels run inside the `gateway` container, so `localhost` points back to that container. Use `http://gateway:8001/api` for `langgraph_url` and `http://gateway:8001` for `gateway_url`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` / `DEER_FLOW_CHANNELS_GATEWAY_URL`.
- Per-channel configs: `feishu` (app_id, app_secret), `slack` (bot_token, app_token), `telegram` (bot_token), `dingtalk` (client_id, client_secret, optional `card_template_id` for AI Card streaming)

**User-owned channel connections** (`config.yaml` -> `channel_connections`):
- Disabled by default. It is a user-binding layer on top of the existing `channels.*` runtime config, not a replacement for provider bot credentials.
- No public IP, OAuth callback URL, or provider webhook route is required by the current implementation.
- Telegram uses a deep-link `/start <code>` flow over the existing long-polling worker. Slack, Discord, Feishu/Lark, DingTalk, WeChat, and WeCom use `/connect <code>` over their existing outbound channel workers.
- Frontend APIs: `GET /api/channels/providers`, `GET /api/channels/connections`, `POST /api/channels/{provider}/connect`, and `DELETE /api/channels/connections/{connection_id}`.
- Browser APIs remain protected by normal Gateway auth/CSRF. Provider messages arrive through the already-configured channel workers.
- Provider-level `connection_status` reflects the user's newest connection row. With no binding it is `not_connected`, except in auth-disabled local mode where a configured running channel reports `connected` because all channel messages already route to the default user.
- Slack replies use the configured operator bot token from `channels.slack` unless per-connection credentials are present; unreadable or corrupt stored credentials are treated as unavailable.
- Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeChat, and WeCom workers resolve incoming platform identities to connection records before reaching `ChannelManager`.
- **Connect-code ordering vs `allowed_users`**: inbound workers consume a valid `/connect <code>` (or Telegram `/start <code>`) **before** applying the `allowed_users` filter, so a newly allowlisted-but-unbound user can bootstrap their first bind via the browser flow. Consequence: `allowed_users` is **not** a bind-time defense — any sender who possesses a valid code can consume it (not only allowlisted users). The bind security model rests on the code's confidentiality: `secrets.token_urlsafe(16)`, 600 s TTL, one-time `consume_oauth_state`, and codes surfaced only in the initiating browser (never echoed to chat). `allowed_users` still gates ordinary (non-bind) messages.
- **Single-active-owner transfer semantics**: an external identity is keyed by `(provider, external_account_id, workspace_id)`. The latest successful bind wins — `upsert_connection` revokes other owners' active rows for the same identity (ownership transfer). This invariant is enforced at the DB layer by the partial unique index `uq_channel_connection_active_identity` (`WHERE status != 'revoked'`), so concurrent connects from different owners cannot both end `connected`; the losing writer retries against the now-visible state. `find_connection_by_external_identity` therefore resolves deterministically.
- See `backend/docs/IM_CHANNEL_CONNECTIONS.md` for provider setup and operational notes.


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
- The `/api/memory*` endpoints resolve the owner through `_resolve_memory_user_id(request)`: trusted internal callers (IM channel workers carrying the `X-DeerFlow-Owner-User-Id` header, e.g. a bound `/memory` command) act for the connection owner; browser/API callers fall back to `get_effective_user_id()`. The header is only honored after `AuthMiddleware` validated the internal token, mirroring `get_trusted_internal_owner_user_id` used by the threads router
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

**Token counting** (`packages/harness/deerflow/agents/memory/prompt.py`):
- `_count_tokens` budgets the injection. In default `tiktoken` mode, the encoding is loaded lazily and cached.
- Failed tiktoken loads are cached with a timestamp. During the fixed cooldown (`_TIKTOKEN_RETRY_COOLDOWN_S`, 600s), callers fall back to char estimation immediately instead of re-triggering the blocking BPE download; after the cooldown, transient outages can self-heal without a restart.
- In-flight loads are cached as a LOADING sentinel so concurrent callers fall back instead of spawning more blocking threads.
- Set `memory.token_counting: char` to skip tiktoken entirely and use the network-free CJK-aware char estimate.

Focused regression coverage for the updater lives in `backend/tests/test_memory_updater.py`.

**Configuration** (`config.yaml` → `memory`):
- `enabled` / `injection_enabled` - Master switches
- `storage_path` - Path to memory.json (absolute path opts out of per-user isolation)
- `debounce_seconds` - Wait time before processing (default: 30)
- `model_name` - LLM for updates (null = default model)
- `max_facts` / `fact_confidence_threshold` - Fact storage limits (100 / 0.7)
- `max_injection_tokens` - Token limit for prompt injection (2000)
- `token_counting` - Token counting strategy for the injection budget: `tiktoken` (default, accurate but may download BPE data from a public endpoint on first use — can block for a long time in network-restricted environments, see issues #3402/#3429) or `char` (network-free CJK-aware char estimate, never touches tiktoken)

### Reflection System (`packages/harness/deerflow/reflection/`)

- `resolve_variable(path)` - Import module and return variable (e.g., `module.path:variable_name`)
- `resolve_class(path, base_class)` - Import and validate class against base class

### Schema Migrations (`packages/harness/deerflow/persistence/migrations/`)

DeerFlow's application tables (`runs`, `threads_meta`, `feedback`, `users`, `run_events`, plus the four `channel_*` tables) are owned by alembic via a **hybrid bootstrap** strategy. LangGraph's checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) live in the same database but are owned by LangGraph and excluded from alembic's view via `migrations/_env_filters.py::include_object`.

**Convention**: every ORM model change (new column, new table, new index) MUST ship as an alembic revision under `migrations/versions/`. The Gateway runs `alembic upgrade head` automatically on startup; users do not run `alembic` manually in production.

**Hybrid bootstrap** (`persistence/bootstrap.py::bootstrap_schema`, invoked from `persistence/engine.py::init_engine`):

| DB state                                  | Action                                  |
|-------------------------------------------|-----------------------------------------|
| empty (no DeerFlow tables)                | `create_all` + `alembic stamp head`     |
| legacy (DeerFlow tables, no `alembic_version`) | `create_all` (baseline tables only, backfill) + `alembic stamp 0001_baseline` + `upgrade head` |
| versioned (`alembic_version` row exists)  | `alembic upgrade head`                  |

The legacy branch handles pre-alembic databases that already have at least one DeerFlow-owned table. `create_all` runs first because stamping at `0001_baseline` makes alembic skip the baseline's own `create_table` DDL on the subsequent upgrade — so any baseline table introduced into `Base.metadata` after the user's DB was first provisioned (e.g. the `channel_*` tables from PR #1930 for users upgrading across multiple releases) would otherwise never be created, and the first request hitting that table would 500 with `no such table`. The backfill is **restricted to `_BASELINE_TABLE_NAMES`** so it does not also create tables that future revisions introduce — those revisions' own `op.create_table` would otherwise fail with `relation already exists`. A guard test pins `_BASELINE_TABLE_NAMES` against `0001_baseline.upgrade()`'s actual output, so editing 0001 to add or remove a table forces a matching update to the constant. Column-level shape (pre-#3658 vs post-#3658 vs manual-ALTER for `token_usage_by_model`) is answered by each `versions/*.py` revision via the idempotent helpers in `migrations/_helpers.py` (`safe_add_column` / `safe_drop_column`) which no-op when the change is already present and `logger.warning` on shape drift. **Adding a new ORM column / table only requires a new revision file — no edit to `bootstrap.py` is needed** *unless* the new revision adds a new baseline table (rare; only happens when a new model is part of the baseline rather than introduced by its own revision).

The empty-DB path keeps using `create_all` because `Base.metadata` is the only authoritative schema source — `create_all` renders both SQLite (JSON, type affinity) and Postgres (JSONB, partial indexes) correctly without anyone having to keep a hand-written baseline in lockstep. `0001_baseline.upgrade()` is therefore almost never executed in practice; it exists as a stamp target + chain root.

**Concurrency safety**: Postgres uses `pg_advisory_lock` to serialise concurrent Gateway instances. SQLite uses a per-engine `asyncio.Lock` for same-process startup and is best-effort across processes via SQLite's file-level write lock + `PRAGMA busy_timeout`; multi-instance deployments should use Postgres. Column revisions in `versions/` additionally use idempotent helpers (`_helpers.py::safe_add_column`, `safe_drop_column`) so repeated post-baseline changes and retries are no-ops when the change is already present.

**Authoring a new revision**:
```bash
cd backend && make migrate-rev MSG="add foo column to runs"
```
This invokes `alembic revision --autogenerate` against the live ORM models. Review the generated file under `migrations/versions/` and switch raw `op.add_column` / `op.drop_column` calls to the idempotent helpers from `_helpers.py` before committing. There is no `make migrate` / `make migrate-stamp` target on purpose — the only execution path is Gateway startup, which keeps operational mistakes off the table.

**Where things live**:
- `migrations/env.py` — alembic env, delegates filter to `_env_filters.py`, sets `render_as_batch=True` for SQLite ALTER support
- `migrations/_env_filters.py::include_object` — drops LangGraph checkpointer tables from alembic's view
- `migrations/_helpers.py` — `safe_add_column` / `safe_drop_column`
- `migrations/versions/0001_baseline.py` — chain root, matches the schema `create_all` produces from `Base.metadata`
- `migrations/versions/0002_runs_token_usage.py` — fixes issue #3682
- `persistence/bootstrap.py` — `bootstrap_schema(engine, backend=...)`, the three-branch decision + locking
- Tests: `tests/test_persistence_bootstrap.py` (branches), `tests/test_persistence_bootstrap_concurrency.py` (concurrency), `tests/test_persistence_bootstrap_regression.py` (issue #3682), `tests/test_persistence_migrations_env.py` (filter), `tests/blocking_io/test_persistence_bootstrap.py` (asyncio.to_thread anchor)

### Terminal Workbench / TUI (`packages/harness/deerflow/tui/`)

A terminal-native UI over the embedded harness, exposed as the `deerflow` console script (`[project.scripts]` in `packages/harness/pyproject.toml`). It is a UI shell over `DeerFlowClient` and does **not** fork agent behavior. `textual` is an optional dependency (`deerflow-harness[tui]`; also in the backend dev group); the console script degrades to headless help when it is absent. Full guide: [docs/TUI.md](docs/TUI.md).

**Module layout** (all layers except `app.py` are pure / Textual-free and unit-tested directly):
- `cli.py` — `plan_launch()` (pure launch-mode decision) + headless `--print` / `--json` + `main()` entry point. TTY → TUI, else headless help. Uses an **absolute** `from deerflow.tui.app import run_tui` so the `app.py` module name doesn't trip `test_harness_boundary.py` (which records relative import module names verbatim).
- `view_state.py` — `ViewState` + `reduce(state, action)`, the testable heart. Rows: user / assistant / tool / system. Title captured from `values` events.
- `runtime.py` — `translate(StreamEvent) -> [Action]` (pure) + `stream_actions()` which brackets a run with `RunStarted`/`RunEnded` and turns model errors into an `AssistantError` row.
- `message_format.py` / `command_registry.py` / `input_history.py` / `render.py` / `theme.py` — pure helpers (tool summaries, slash registry + `resolve()`, ↑/↓ history, Rich renderers).
- `app.py` — Textual `App`. Runs `DeerFlowClient.stream()` (sync) on a worker thread and marshals actions to the UI thread via `call_from_thread`. Slash palette with `/goal` management + model/thread modal pickers; priority key bindings gated by `check_action` so they never steal keys from overlays or the composer.
- `session.py` / `persistence.py` — builds the client + checkpointer and the `ThreadMetaWriter`.

**Web UI visibility**: the Web UI lists threads from the `threads_meta` SQL table (user-scoped), not the checkpointer. `persistence.py` writes a `threads_meta` row under the default user (`"default"`) into the same DB the Gateway reads — via the harness-only `deerflow.persistence.engine.init_engine_from_config()` — so TUI sessions appear in the Web UI sidebar **without** running the Gateway. Best-effort: a no-op on the `memory` backend. All DB work runs on one long-lived background event loop (a SQLAlchemy async engine is bound to its creating loop).

**Tests**: `tests/test_tui_*.py` — pure layers via plain pytest, the app/palette/overlays via Textual's pilot harness with a fake in-process session, and `test_tui_persistence.py` for the `threads_meta` round-trip.

### Request Trace Context (`packages/harness/deerflow/trace_context.py`)

Request trace correlation is controlled by `logging.enhance.enabled` at **both** entry points, gated through the shared helper `deerflow.config.app_config.is_trace_correlation_enabled` so the Gateway and embedded paths cannot drift:

- **Gateway HTTP**: `app.gateway.trace_middleware.TraceMiddleware` binds one request-level trace id per HTTP request, inheriting inbound `X-Trace-Id` when present or generating a new id otherwise. The middleware writes the final value to every HTTP response at `http.response.start`, which covers SSE / streaming responses without consuming the body.
- **Embedded / TUI / CLI**: `DeerFlowClient.stream()` mints (or inherits) a request-level trace id per turn only when the flag is on. When it is off, no fresh id is minted — a caller that explicitly wraps `stream()` in `request_trace_context(...)` still opts in, because the downstream `get_current_trace_id()` read propagates that value into Langfuse metadata regardless of the flag. Because `stream()` is a sync generator (which shares the caller's context), the id binding is set/reset around each `next()` step rather than around `yield from`: this keeps LangGraph node execution and its log records inside the binding, while returning control to the caller with the ContextVar restored — avoids cross-request leak between yields and `ValueError: <Token> was created in a different Context` on GC-driven close of an abandoned generator (regression pinned by `tests/test_client_langfuse_metadata.py::test_stream_does_not_leak_trace_id_to_caller_context_between_yields` and `::test_stream_abandoned_generator_close_does_not_raise_cross_context`).

The same ContextVar value is injected into enhanced log records as `trace_id` and into Langfuse metadata as `deerflow_trace_id`.

`logging` is registered as a **restart-required** field
(`STARTUP_ONLY_FIELDS["logging"]`): `configure_logging()` installs the trace-context
filter and enhanced formatter on root handlers only during app.py lifespan startup,
and `TraceMiddleware` captures `logging.enhance.enabled` once when the FastAPI app
is constructed (via `resolve_trace_enabled(get_app_config())` in `create_app()`,
itself a thin alias for `is_trace_correlation_enabled`). This keeps the response
`X-Trace-Id` header, log `trace_id` fields, and Langfuse `deerflow_trace_id`
coherent — a runtime `config.yaml` edit to `logging.enhance.*` needs a Gateway
restart to take effect. The `deerflow_trace_id` chain inherits this guarantee
transitively because every injection point ultimately reads the same
`trace_context` ContextVar that the middleware alone populates. `DeerFlowClient`
reads its own `self._app_config` snapshot (captured at `__init__`) through the
same helper for the embedded gate.

`deerflow_trace_id` is a DeerFlow correlation metadata key, not Langfuse's native
trace id and not a DeerFlow `run_id`. Keep the existing subagent `trace_id` field
separate: that short id is still only for subagent execution logs/status.

### Tracing System (`packages/harness/deerflow/tracing/`)

LangSmith and Langfuse are both supported. The wiring lives in two layers:

- `factory.py::build_tracing_callbacks()` — returns the LangChain `CallbackHandler` list for the providers currently enabled via env vars (`LANGSMITH_TRACING`, `LANGFUSE_TRACING`, etc.). The handlers are attached at the **graph invocation root** for in-graph runs (`make_lead_agent` and `DeerFlowClient.stream` both append them to `config["callbacks"]` before invoking the graph) so a single run produces one trace with all node / LLM / tool calls as child spans. Standalone callers — anything that invokes a model outside such a graph (e.g. `MemoryUpdater`) — keep `create_chat_model`'s default `attach_tracing=True`, which falls back to model-level callback attachment.
- `metadata.py::build_langfuse_trace_metadata()` — builds the Langfuse-reserved trace attributes for `RunnableConfig.metadata`. The Langfuse v4 `langchain.CallbackHandler` lifts these onto the root trace (see its `_parse_langfuse_trace_attributes`), but only when it sees `on_chain_start(parent_run_id=None)` — which is why the callbacks have to live at the graph root, not the model.

**Trace-attribute injection points**: both `runtime/runs/worker.py::run_agent` (gateway path) and `client.py::DeerFlowClient.stream` (embedded path) merge the metadata into `config["metadata"]` right before constructing the graph. `subagents/executor.py::_aexecute` does the same for every subagent run so subagent traces group under the parent thread's session card (carrying the parent `thread_id` → `langfuse_session_id`, the user_id captured at `task_tool` → `langfuse_user_id`, and a `subagent:<normalized-name>` trace name). Caller-supplied keys win via `setdefault`, so an external `session_id` override is preserved. Field mapping:

| Langfuse field         | Source                                       |
|-----------------------|----------------------------------------------|
| `langfuse_session_id` | LangGraph `thread_id`                         |
| `langfuse_user_id`    | `get_effective_user_id()` (`default` in no-auth); for subagents, captured from `runtime.context` at `task_tool` time via `resolve_runtime_user_id()` |
| `langfuse_trace_name` | `RunRecord.assistant_id` / client `agent_name` (defaults to `lead-agent`); for subagents, `subagent:<name>` (lowercased, `_` → `-`) |
| `langfuse_tags`       | `env:<DEER_FLOW_ENV>` + `model:<model_name>`  |
| `deerflow_trace_id`   | Current request/entry trace id from `deerflow.trace_context`; matches `X-Trace-Id` for enhanced Gateway HTTP requests. Gated by `logging.enhance.enabled` in both gateway and embedded paths via `is_trace_correlation_enabled` — off by default; embedded callers can still opt in per-turn by wrapping `stream()` in `request_trace_context(...)` |

Returns `{}` when Langfuse is not in the enabled providers — LangSmith-only deployments are unaffected. Set `DEER_FLOW_ENV` (or `ENVIRONMENT`) to tag traces by deployment environment. Tests live in `tests/test_tracing_factory.py`, `tests/test_tracing_metadata.py`, `tests/test_worker_langfuse_metadata.py`, `tests/test_client_langfuse_metadata.py`, and `tests/test_subagent_executor.py::TestSubagentTracingWiring`.

### Config Schema

**`config.yaml`** key sections:
- `models[]` - LLM configs with `use` class path, `supports_thinking`, `supports_vision`, provider-specific fields
- `logging.enhance` - Optional request trace correlation (`enabled`, `format`) for Gateway `X-Trace-Id`, log `trace_id`, and Langfuse `deerflow_trace_id`
- vLLM reasoning models should use `deerflow.models.vllm_provider:VllmChatModel`; for Qwen-style parsers prefer `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking`, and DeerFlow will also normalize the older `thinking` alias
- `tools[]` - Tool configs with `use` variable path and `group`
- `tool_groups[]` - Logical groupings for tools
- `sandbox.use` - Sandbox provider class path
- `skills.path` / `skills.container_path` - Host and container paths to skills directory
- `title` - Auto-title generation (enabled, max_words, max_chars, model_name; null model_name uses fast local fallback, explicit model_name uses the prompt_template LLM path)
- `summarization` - Context summarization (enabled, trigger conditions, keep policy)
- `subagents.enabled` - Master switch for subagent delegation
- `memory` - Memory system (enabled, storage_path, debounce_seconds, model_name, max_facts, fact_confidence_threshold, injection_enabled, max_injection_tokens)

**`extensions_config.json`**:
- `mcpServers` - Map of server name → config (enabled, type, command, args, env, url, headers, oauth, description)
- `skills` - Map of skill name → state (enabled)

Both can be modified at runtime via Gateway API endpoints or `DeerFlowClient` methods.

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
- Agent created lazily via `create_agent()` + `build_middlewares()`, same as `make_lead_agent`
- Supports `checkpointer` parameter for state persistence across turns
- `reset_agent()` forces agent recreation (e.g. after memory or skill changes)
- See [docs/STREAMING.md](docs/STREAMING.md) for the full design: why Gateway and DeerFlowClient are parallel paths, LangGraph's `stream_mode` semantics, the per-id dedup invariants, and regression testing strategy

**Gateway Equivalent Methods** (replaces Gateway API):

| Category | Methods | Return format |
|----------|---------|---------------|
| Models | `list_models()`, `get_model(name)` | `{"models": [...]}`, `{name, display_name, ...}` |
| MCP | `get_mcp_config()`, `update_mcp_config(servers)` | `{"mcp_servers": {...}}` |
| Skills | `list_skills()`, `get_skill(name)`, `update_skill(name, enabled)`, `install_skill(path)` | `{"skills": [...]}` |
| Goals | `get_goal(thread_id)`, `set_goal(thread_id, objective, max_continuations=8)`, `clear_goal(thread_id)` | `{"goal": {...}}` or `{"goal": None}` |
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
- Files stored in thread-isolated directories under the resolving user's bucket (`users/{user_id}/threads/{thread_id}/user-data/uploads`). For IM channels the owner is threaded explicitly via the `user_id=` kwarg (see IM Channels → Owner-scoped file storage); HTTP/embedded callers resolve it from `get_effective_user_id()`
- Duplicate filenames in a single upload request are auto-renamed with `_N` suffixes so later files do not truncate earlier files
- Gateway HTTP uploads stage bytes as `.upload-*.part` files and atomically replace the destination only after size validation. These staging files are hidden from upload listings, agent upload context, and sandbox listing/search tools, and swept on Gateway startup if a hard crash leaves one behind.
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

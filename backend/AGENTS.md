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
- Scheduled-task executions must reuse that same Gateway run lifecycle. The scheduler may decide *when* work runs, but it must dispatch through the existing run path rather than introducing a parallel execution stack.

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
│   │           ├── tools/builtins/    # Built-in tools (present_files, ask_clarification, view_image, review_skill_package)
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
conservatively over-report async reachability. The call graph also resolves
multi-hop `self.`/`cls.` attribute chains (`self.store.flush()`) and local
variables or parameters traced back — within the same function only — to a
`self.`/`cls.` attribute (`store = self.store; store.flush()`); both fall back
to the same bare-method-name resolution as an unresolvable receiver, so they
share its over-report risk rather than adding a new kind. Deeper cross-function
or cross-module aliasing is out of scope and stays an unreported false
negative.

That same-function alias tracing is deliberately narrower than the symbolic
names `dotted_name()` builds for blocking-call pattern matching elsewhere in
this module: receiver/alias extraction uses a restricted extractor that only
recognizes `Name`/`Attribute` chains, so a `Call` or `Subscript` result (e.g.
`factory().flush()`, or `client = factory(); client.flush()` /
`client = clients[0]; client.flush()`) is never treated as inheriting its
base's alias-worthiness — including when the unsupported node is buried
deeper in the chain (`factory().client.flush()`, `clients[0].client.flush()`):
an unrecognized shape anywhere in the chain makes the whole receiver
unresolved, it never falls back to just the chain's trailing attribute name,
or that name alone could still collide with an unrelated traced parameter or
local alias. Reassigning a traced name to a non-traceable value (anything
other than a `self.`/`cls.` attribute or an already-traced name) kills its
alias instead of leaving it traceable, so a stale alias from an earlier
assignment cannot keep exposing an unrelated same-named method after the
variable is reassigned to something else; the assignment's right-hand side is
always analyzed against the alias state as it stood *before* this kill-or-add
update, matching Python's own evaluate-then-bind order, so
`client = client.flush()` still resolves that call against `client`'s prior
(pre-reassignment) alias instead of the state after it's gone. `if`/`else`
branches get isolated alias state — an alias added in one branch cannot leak
into the other — and the state after the whole `if` is the union of what each
branch produced (a conservative may-alias join), so the result no longer
depends on which branch is textually `body` vs. `orelse`. This branch
isolation is deliberately scoped to `ast.If` only; `ast.Try`/`ast.Match` have
different, more complex control-flow semantics and keep the older unisolated
traversal. Finally, a function's decorators and parameter defaults are
analyzed in the *enclosing* scope rather than the new function's own, and
parameter/return annotations get the same enclosing-scope treatment unless
the module postpones annotation evaluation (`from __future__ import
annotations`), in which case they are skipped entirely, in either scope —
those expressions run at definition time, before the function has ever been
called (or, when postponed, never run at all), so a call there is never
attributed to the function being defined (it moves to whatever scope actually
contains the `def`, e.g. the enclosing function, or disappears if that scope
is module/class level and therefore never async-reachable). PEP 695
type-parameter bounds are not visited in either scope: CPython evaluates each
one lazily, in its own hidden function, only if something like `T.__bound__`
is actually accessed, never as part of running the `def` statement itself.
A `lambda`'s body and a bare generator expression's element/filters/later
`for` clauses are excluded from traversal ONLY while walking another
function's own definition-time expressions (decorators, parameter defaults/
annotations, return annotation): there, we know structurally that the
enclosing `def` statement is executing right now, and neither a lambda body
nor a generator's element runs just because the lambda/generator object is
created — only a lambda's own parameter defaults and a generator's
outermost iterable are genuinely eager at that moment. This exclusion is
absolute and has no exceptions: even a lambda that is immediately invoked at
its own definition site (`(lambda: ...)()`), or a generator passed directly
to an eager-consuming builtin, is still excluded when it appears inside
another function's decorator/default/annotation — a narrow, intentional
limitation given how rarely a definition-time expression contains an
executed call at all, preferred over special-casing specific shapes there.

Everywhere else — module level, class bodies, and ordinary function-body
statements — a lambda body or generator expression's element is scanned
unconditionally, the same conservative, over-report-rather-than-infer stance
this file already takes for reachability elsewhere (the `ast.If` may-alias
union, the bare-name call-graph resolution). This file does not attempt to
distinguish a lambda that is invoked immediately, invoked later through a
stored variable, passed as a callback, or never called at all, nor a
generator that is consumed by an eager builtin (`list`, `sum`, `any`, etc.),
wrapped in another lazy iterator (`map`, `filter`), or never consumed —
telling these apart in the general case would mean inferring evaluation
order and consumption across arbitrary code rather than reading a fixed,
structural fact, so none of them are special-cased; all are scanned the
same way. This is intentionally informational and is not run from CI in
this round.

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
- `tests/test_provisioner_request_threading.py` (keeps provisioner sandbox CRUD
  endpoints as sync FastAPI handlers so synchronous K8s client calls run in the
  Starlette worker pool instead of on the ASGI event loop)

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
  API offloading its file IO via `asyncio.to_thread`);
  `test_uploads_middleware.py` (locks `UploadsMiddleware.abefore_agent`
  offloading the uploads-directory scan off the event loop);
  `test_uploads_router.py` (locks Gateway upload/list/delete endpoints
  offloading upload directory creation, staged writes, chmod/cleanup,
  directory scans/deletes, and remote sandbox sync off the event loop); and
  `test_workspace_changes_recorder.py` (locks the offload around the snapshot
  text cache lifecycle — roots resolution, `mkdtemp`, and the `shutil.rmtree`
  on both the capture-failure branch and `record_workspace_changes`' `finally`).
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

Agentic browser sessions are process-local. The Gateway startup safety gate rejects
`GATEWAY_WORKERS > 1` when `browser_navigate` is configured, because ordinary
uvicorn worker dispatch does not provide thread affinity for browser tools, REST
navigation, and the Live WebSocket.

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
- `max_concurrent_subagents` - Per-response `task` call concurrency limit (clamped by `SubagentLimitMiddleware`)
- `max_total_subagents` - Optional per-run total delegation cap override (falls back to `subagents.max_total_per_run`, clamped to 1-50)
  Gateway and `DeerFlowClient.stream()` always provide the runtime `run_id`; custom
  graph integrations must do the same. If it is absent, enforcement deliberately
  counts the thread's full delegation ledger (fail-restrictive) and emits a warning.

### Middleware Chain

Lead-agent middlewares are assembled in strict order across three functions: the shared base in `packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` (`_build_runtime_middlewares`, exposed via `build_lead_runtime_middlewares`), then the lead-only middlewares appended in `packages/harness/deerflow/agents/lead_agent/agent.py` (`build_middlewares`). Items marked *(optional)* are appended only when their config/runtime condition holds, so the live chain length varies.

**Shared runtime base** (`build_lead_runtime_middlewares`; subagents reuse most of this via `build_subagent_runtime_middlewares`):

1. **InputSanitizationMiddleware** - First, so it is the outermost `wrap_model_call` wrapper; every inner middleware (including LLM retries) sees sanitized messages. `additional_kwargs.original_user_content` is server-owned provenance: Gateway strips caller-supplied values for non-internal run requests, trusted IM calls may carry the string they captured before adding transport/file context, and the middleware replaces any non-string value before wrapping. Uploads and sanitization retain first-writer-wins only for validated strings.
2. **ToolOutputBudgetMiddleware** - Caps tool output size (per app config) before it re-enters the model context
3. **ToolResultSanitizationMiddleware** - Neutralizes framework/injection tags (e.g. `<system-reminder>`) and boundary markers in *remote-content* tool results (`web_fetch`/`web_search`/`image_search`/`web_capture`) so attacker-controlled fetched pages cannot forge trusted framework context. Mirrors `InputSanitizationMiddleware`'s user-input guardrail for the other untrusted-content entry point; sits inner of `ToolOutputBudgetMiddleware` (neutralizes the raw output, then the budget truncates). Local tool output (bash/read_file) is left untouched. Scope is a name-based allowlist, so MCP remote-content tools registered under other names (e.g. `fetch_url`) are not yet covered — a metadata-tagging follow-up is tracked in the middleware source
4. **ThreadDataMiddleware** - Creates per-thread directories under the user's isolation scope (`backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`); resolves `user_id` via `get_effective_user_id()` (falls back to `"default"` in no-auth mode)
5. **UploadsMiddleware** - Tracks and injects newly uploaded files into conversation (lead agent only)
6. **SandboxMiddleware** - Acquires sandbox, stores `sandbox_id` in state
7. **DanglingToolCallMiddleware** - Injects placeholder ToolMessages for AIMessage tool_calls that lack responses (e.g., user interruption), preserving raw provider tool-call payloads in `additional_kwargs["tool_calls"]`; malformed tool-call names and arguments are sanitized in the model-bound request so strict OpenAI-compatible providers do not reject the next request
8. **LLMErrorHandlingMiddleware** - Normalizes provider/model invocation failures into recoverable assistant-facing errors before later stages run
9. **Authorization / GuardrailMiddleware** - Up to two independent pre-tool-call gates run here. When `authorization.enabled`, the `AuthorizationProvider` instance already used for Layer 1 capability filtering is wrapped by `GuardrailAuthorizationAdapter` and reused for Layer 2 execution checks. A generated `tool_search` bypasses the adapter's second provider call only when the current build has a concrete deferred setup; its catalog was already filtered by Layer 1, and an ordinary same-named tool without that deferred setup receives no exemption. When `guardrails.enabled`, the explicitly configured `GuardrailProvider` is appended after authorization and still evaluates every call, including `tool_search`. Authorization therefore runs outermost and can deny before an external guardrail call; both use the existing middleware's fail-closed, audit, sync/async, and error-`ToolMessage` behavior. See the authorization RFC and [docs/GUARDRAILS.md](docs/GUARDRAILS.md).
10. **SandboxAuditMiddleware** - Audits sandboxed shell/file operations for security logging before tool execution
11. **ReadBeforeWriteMiddleware** - *(optional, if `read_before_write.enabled`, default on)* Outermost write gate (issue #3857): `read_file` stamps a content hash onto its ToolMessage; `write_file` (append/overwrite-existing) and `str_replace` are blocked unless the newest mark for that path matches the file's current hash. Sits outside ToolProgressMiddleware and ToolErrorHandlingMiddleware so a blocked write returns immediately without consuming a ToolProgress slot. Blocked results call `normalize_tool_result` directly to stamp `deerflow_tool_meta` (`recoverable_by_model=True`) before returning, keeping the result well-formed for any outer consumer. Marks live on messages, so summarization dropping the read result invalidates the gate automatically; writes never refresh marks, forcing a re-read between consecutive edits. Gate check + tool execution are serialized per (thread, path) so same-turn parallel writes cannot reuse one stale mark; on sandboxes whose `read_file` reports failures as `"Error: ..."` strings instead of raising (AIO/E2B), uninspectable targets fail open (creation proceeds, no mark stamped)
12. **ToolProgressMiddleware** - *(optional, if `tool_progress.enabled`)* State-machine-based stagnation guard (RFC #3177). Outer wrapper around ToolErrorHandlingMiddleware so its `wrap_tool_call` receives results already stamped with `deerflow_tool_meta`. Tracks per-(thread, tool) consecutive "no-new-info" calls across three error categories: (a) `recoverable_by_model=True` (no_results, not_found, permission, Jaccard-duplicate success): ACTIVE → WARNED (terminal — hint re-injected on each subsequent problem); (b) `recoverable_by_model=False, action≠stop` (rate_limited, transient): ACTIVE → WARNED → BLOCKED after `warn_escalation_count` more problems; (c) `recoverable_by_model=False, action=stop` (auth, config, internal): immediately BLOCKED on first occurrence. **Division of labor with LoopDetectionMiddleware:** ToolProgressMiddleware is a result-quality guard — fires after tool execution and blocks specific tools that stop producing new information; LoopDetectionMiddleware is a call-pattern guard — fires after the model responds and hard-stops the whole turn when the model repeatedly issues identical tool_calls. Both can inject HumanMessage hints in the same model call without conflict; neither reads the other's internal state.
13. **ToolErrorHandlingMiddleware** - Receives `AppConfig`, converts tool exceptions into error `ToolMessage`s so the run can continue instead of aborting, stamps every result with `deerflow_tool_meta` (status / error_type / recoverable_by_model / recommended_next_action / source) via `tool_result_meta.normalize_tool_result`, stamps structured metadata for task exception wrappers, and stamps skill-read metadata for downstream durable-context capture. Task tool result text is generated from the same status/result/error inputs as the structured metadata so callers do not hand-write a second protocol string.

Authorization identity plumbing is independent of whether authorization enforcement is enabled. Gateway removes client-supplied `is_internal` / `authz_attributes` / `channel_user_id`, derives `is_internal` only from the server-owned `request.state.auth_source`, and accepts `channel_user_id` only from an internally authenticated IM caller's top-level `body.context`; free-form `body.config` can never supply it. `build_principal_from_context` is the shared Principal builder for assembly-time authorization and `GuardrailAuthorizationAdapter`; it applies `default_role`, strict-boolean internal provenance, and copy-on-read `authz_attributes`. The built-in RBAC provider validates `authorization.default_role` during provider resolution so an unknown fallback role fails agent construction instead of degrading into an empty tool set. Task delegation carries `is_internal` plus copied attributes through `SubagentExecutor`, while `GuardrailMiddleware` maps the same runtime fields into `GuardrailRequest`. Phase 1B applies Layer 1 before deferred-tool assembly on the lead, native-subagent, and embedded-client paths, then passes the same provider instance into Layer 2. Framework-provided `describe_skill` and memory tools are included in Layer 1 but restored to their legacy post-`tool_search` ordering afterward. `DeerFlowClient.stream()` treats its in-process caller as trusted and accepts the same identity fields as keyword overrides; it includes the complete Principal in its agent cache key and deep-copies nested attributes so caller mutation cannot make a stale tool set look current.

Before changing a later authorization phase, read the [authorization RFC](../docs/plans/2026-07-10-pluggable-authorization-rfc.md) and its [implementation notes](../docs/plans/2026-07-10-pluggable-authorization-implementation-notes.md). The notes are the cumulative handoff record for merged PR behavior, reviewer feedback, trust-boundary decisions, deferred scope, and required regression coverage.

**Lead-only middlewares** (`build_middlewares`, appended after the base):

14. **DynamicContextMiddleware** - Injects the current date (and optionally memory) as a `<system-reminder>` into the first HumanMessage, keeping the base system prompt fully static for prefix-cache reuse
15. **SkillActivationMiddleware** - Detects strict `/skill-name task` syntax on the latest real user message, resolves only enabled and runtime-allowed skills, injects the `SKILL.md` body as hidden current-turn context, and records a `middleware:skill_activation` audit event
16. **SkillToolPolicyMiddleware** - Applies `allowed-tools` only after real activation; passive enabled skills and a custom agent's configured skill allowlist do not clamp the lead toolset. A run-scoped slash activation is authoritative and suppresses `skill_context` as a policy source, so reading another skill cannot widen the explicit skill's tools; without slash activation, skills captured after configured `read_file` loads retain the existing union semantics. The middleware filters model-visible schemas and blocks unauthorized execution, resolving canonical paths against the live enabled/agent-allowed registry on every model call, then stores a versioned, JSON-safe, middleware-token-bound decision signed by policy source plus active paths in run context for the resulting tool calls to reuse. The next model call always refreshes it, and malformed, foreign, stale, or unmatched decisions fall back to live resolution. `tool_search` and `describe_skill` remain framework-safe discovery tools under a restrictive policy; they may reveal or promote metadata, but a deferred business tool must still be declared by the active policy before its schema or execution can survive the policy middleware. The decision's owner token is authorization-sensitive, so its reserved context key is owned by `runtime.secret_context` and included in `REDACTED_CONTEXT_KEYS` for observable and persisted context copies. Registry load failures and a non-empty active set with no authorized skill fail closed to framework-safe tools; an individual stale path is skipped only when at least one valid active skill remains. This is best-effort behavioral scoping rather than a hard security boundary: alternate loads such as `bash cat` are not captured, and bounded autonomous `skill_context` can evict old entries. `task` is not framework-exempt, so a restricted skill cannot delegate around its policy. The middleware must remain immediately after `SkillActivationMiddleware` (which publishes the slash source through `runtime.secret_context`'s public path helpers authenticated by a required token shared only within the assembled middleware chain) and immediately before `DurableContextMiddleware`; assembly and compiled-graph tests pin ordering, token sharing, schema filtering, and execution blocking.
17. **DurableContextMiddleware** - Captures `task` delegations into `ThreadState.delegations` (including in-progress dispatches and terminal result summaries) and loaded skill-file references (name/path/description, parsed in-memory - not the body) into `ThreadState.skill_context` before summarization can compact the paired tool-call/result messages, then projects durable context into each model request. Static authority rules are injected as a `SystemMessage`; untrusted field values (`summary_text`, delegation results, skill descriptions) are injected separately as a hidden `HumanMessage` data block so compressed history, delegated work, and which skills are active stay visible without being stored as `messages` or promoted to system-role instructions. `build_subagent_runtime_middlewares` also attaches this middleware immediately before subagent summarization so a compacted `summary_text` is projected ahead of a preserved assistant/tool tail instead of leaving strict providers with an assistant-first request.
18. **SummarizationMiddleware** - *(optional, if enabled)* Context reduction when approaching token limits
19. **TodoListMiddleware** - *(optional, if `is_plan_mode`)* Task tracking with the `write_todos` tool
20. **TokenUsageMiddleware** - *(optional, if `token_usage.enabled`)* Records token usage metrics; subagent usage is merged back into the dispatching AIMessage by message position
21. **TitleMiddleware** - Auto-generates the thread title after the first complete exchange and normalizes structured message content before prompting the title model. If a first-turn run is interrupted before this middleware can write a title, `runtime/runs/worker.py` keeps the run in a finalizing state, persists a local fallback title from the latest checkpoint or original run input, and then syncs it to `threads_meta.display_name`. Replacement runs admitted by `multitask_strategy="interrupt"` / `"rollback"` wait for older same-thread finalization before entering the graph; the interrupted run only skips the fallback title write once a later run has started and may have advanced the checkpoint.
22. **MemoryMiddleware** - Queues conversations for async memory update (filters to user + final AI responses)
23. **ViewImageMiddleware** - *(optional, if the model supports vision)* Injects a hidden HumanMessage with base64 image data, identified by a reserved ID prefix plus a server-owned metadata marker, before the LLM call. Because `before_model`, `model`, and `after_model` are separate graph nodes, the `before_model` and `model` node checkpoints for that call still contain the payload; `after_model` / `aafter_model` then emits `RemoveMessage`, so subsequent checkpoints do not retain it
24. **McpRoutingMiddleware** - *(optional, if `tool_search.enabled` and PR1 MCP routing metadata produce a routing index)* Auto-promotes matching deferred MCP tool schemas before the model call by writing a minimal `promoted` state update. It matches only the latest real `HumanMessage`, uses the global `tool_search.auto_promote_top_k` limit (default 3, clamped to 1..5), never executes tools, and must be installed before `DeferredToolFilterMiddleware`
25. **DeferredToolFilterMiddleware** - *(optional, if `tool_search.enabled`)* Hides deferred (MCP) tool schemas from the bound model until `tool_search` or `McpRoutingMiddleware` promotes them (reads per-thread promotions from `ThreadState.promoted`, hash-scoped)
26. **SystemMessageCoalescingMiddleware** - Merges every SystemMessage into a single leading SystemMessage per request; provider-agnostic fix for strict backends (vLLM/SGLang/Qwen/Anthropic) that reject non-leading system messages. Touches the per-request payload only (checkpoint state unchanged); on midnight crossings only the latest `dynamic_context_reminder` SystemMessage survives
27. **SubagentLimitMiddleware** - *(optional, if `subagent_enabled`)* Truncates excess `task` tool calls to enforce both the per-response concurrency limit (`max_concurrent_subagents`, clamped to 2-4) and the per-run total delegation cap (`max_total_subagents` runtime override or `subagents.max_total_per_run`, default 6, clamped to 1-50). The total cap counts current-run entries in the durable delegation ledger (entries are tagged with `run_id` when captured), so repeated planning checkpoints in one run cannot keep launching legal-sized batches indefinitely, while later user turns in the same thread get a fresh run budget. If the cap is exhausted, the middleware strips remaining `task` calls, forces `finish_reason="stop"`, and appends a visible limit note so the run can synthesize existing results instead of ending with an empty tool-call response.
28. **LoopDetectionMiddleware** - *(optional, if `loop_detection.enabled`)* Detects repeated tool-call loops; hard-stop clears both structured `tool_calls` and raw provider tool-call metadata before forcing a final text answer; stamps `loop_capped` via `consume_stop_reason` (#3875 Phase 2), symmetric to `TokenBudgetMiddleware`
29. **TokenBudgetMiddleware** - *(optional, if `token_budget.enabled`)* Enforces per-run token limits
30. **Custom middlewares** - *(optional)* Any `custom_middlewares` passed to `build_middlewares` are injected here, before config-declared extensions and the terminal-response/safety/clarification tail
31. **Configured extension middlewares** - *(optional, if `extensions.middlewares` is set in `config.yaml` or `extensions_config.json`)* Zero-argument `AgentMiddleware` classes loaded from `module.path:ClassName` entries via `deerflow.reflection.resolve_class`. Missing packages, invalid classes, and broken modules fail loudly at agent creation. These run after built-ins/programmatic custom middleware and after the lead/subagent loop/token guards, but before the terminal-response/safety/clarification tail; subagents receive the same configured extension middleware class list before their safety tail. Treat these files as trusted operator config because middleware paths instantiate arbitrary code. Gateway skill/MCP toggle endpoints preserve this field through `to_file_dict()` but must not add a write path for `extensions.middlewares` without an explicit trust-boundary review. Lead-only vs subagent-only middleware lists and per-context constructor parameters are not expressible in this MVP.
32. **TerminalResponseMiddleware** - When a provider returns an empty terminal `AIMessage` after tool execution, injects a hidden recovery prompt and retries the model once; a second empty response is replaced in checkpoint state by a visible error fallback marked for the run worker, so the run finishes as an error instead of a silent success
33. **SafetyFinishReasonMiddleware** - *(optional, if `safety_finish_reason.enabled`)* Repairs AIMessages the provider safety-terminated (e.g. `finish_reason=content_filter`): strips truncated tool calls so they are not executed (#3028), and — when the response is otherwise blank (no tool calls, no visible content) — backfills a user-facing explanation so the empty message is not persisted and then rejected by strict OpenAI-compatible providers on the next request (`message ... with role 'assistant' must not be empty`), which would otherwise strand the whole thread (#4393). A safety-terminated response that still carries visible text is left untouched. Registered after terminal-response/custom/configured middlewares so LangChain's reverse-order `after_model` dispatch runs it first
34. **ClarificationMiddleware** - Intercepts `ask_clarification` tool calls, writes a readable `ToolMessage.content` fallback plus structured `ToolMessage.artifact.human_input` request payload, and interrupts via `Command(goto=END)` (must be last). Because this middleware can short-circuit tool execution before LangChain emits `on_tool_end`, `RunJournal` performs a root-run final reconciliation for allowlisted clarification `ToolMessage`s whose `tool_call_id` was produced by the current run, so human-input request cards remain recoverable from `run_events` after checkpoint compaction. Human Input Card replies are submitted as `hide_from_ui` `HumanMessage`s with `additional_kwargs.human_input_response`; `RunJournal` persists only allowlisted hidden response sources (currently `ask_clarification`) as `llm.human.input`, which preserves answered-card state after compaction without exposing generic internal hidden context.

### Configuration System

**Main Configuration** (`config.yaml`):

Setup: Copy `config.example.yaml` to `config.yaml` in the **project root** directory.

**Config Versioning**: `config.example.yaml` has a `config_version` field. On startup, `AppConfig.from_file()` compares user version vs example version and emits a warning if outdated. Missing `config_version` = version 0. Run `make config-upgrade` to auto-merge missing fields. When changing the config schema, bump `config_version` in `config.example.yaml`.

**Config Caching**: `get_app_config()` caches the parsed config, but automatically reloads it when the resolved config path or file content signature changes. The signature includes file metadata and a content digest, so Gateway and LangGraph reads stay aligned with `config.yaml` edits even on object-store or network mounts where mtime can remain stale.

**Config Hot-Reload Boundary**: Gateway dependencies route through `get_app_config()` on every request, so per-run fields like `models[*].max_tokens`, `summarization.*`, `title.*`, `memory.*`, `subagents.*`, `tools[*]`, and the agent system prompt pick up `config.yaml` edits on the next message. `AppConfig` is intentionally **not** cached on `app.state` — `lifespan()` keeps a local `startup_config` variable for one-shot bootstrap work and passes it to `langgraph_runtime(app, startup_config)`.

Infrastructure fields are **restart-required**. The authoritative list lives in `packages/harness/deerflow/config/reload_boundary.py::STARTUP_ONLY_FIELDS` and is mirrored by the standardised `"startup-only:"` prefix on the corresponding `Field(description=...)` in `AppConfig`, so IDE hover on those fields surfaces the reason inline (no need to context-switch into this table). Currently registered: `database`, `checkpointer`, `run_events`, `stream_bridge`, `sandbox`, `log_level`, `logging`, `channels`, `channel_connections`, `scheduler`, `run_ownership`. Adding a new restart-required field requires updating the registry; drift is pinned by `tests/test_reload_boundary.py`.

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

Docker development mounts the project directory at `/app/project` and points
`DEER_FLOW_CONFIG_PATH` / `DEER_FLOW_EXTENSIONS_CONFIG_PATH` into that directory.
Keep mutable config files behind a directory bind mount: single-file bind mounts
can become stale or inaccessible when a host editor replaces a file on save.

Configuration priority:
1. Explicit `config_path` argument
2. `DEER_FLOW_EXTENSIONS_CONFIG_PATH` environment variable
3. `extensions_config.json` in current directory (backend/)
4. `extensions_config.json` in parent directory (project root - **recommended location**)

Extensions are optional only in the fallback *search* mode (priority 3-4 above): `ExtensionsConfig.resolve_config_path()` returns `None` when neither an explicit `config_path` nor `DEER_FLOW_EXTENSIONS_CONFIG_PATH` is given and the search locations find nothing. An explicit `config_path` argument or a set `DEER_FLOW_EXTENSIONS_CONFIG_PATH` (priority 1-2) is an operator assertion that one particular file must be used, so a missing file in either of those modes raises `FileNotFoundError` instead — including when the file existed earlier and has since been deleted. The MCP tools cache's staleness check (`deerflow.mcp.cache._resolve_config_path`) is a narrow, deliberate exception to that rule: it catches that `FileNotFoundError` locally and treats it as "unconfigured" so a previously-valid config disappearing mid-run degrades the cache to serving its last-known-good tools instead of raising out of a per-request hot path (see the MCP System section below).

### Gateway API (`app/gateway/`)

FastAPI application on port 8001 with health check at `GET /health`. Set `GATEWAY_ENABLE_DOCS=false` to disable `/docs`, `/redoc`, and `/openapi.json` in production (default: enabled).

CORS is same-origin by default when requests enter through nginx on port 2026. Split-origin or port-forwarded browser clients must opt in with `GATEWAY_CORS_ORIGINS` (comma-separated exact origins); Gateway `CORSMiddleware` and `CSRFMiddleware` both read that variable so browser CORS and auth-origin checks stay aligned.

Browser auth sessions are owned by `app.gateway.auth.session_cookie`. Login accepts a `remember_me` form flag, but the Gateway never stores passwords. `SessionCookiePolicy` persists the `HttpOnly access_token` cookie only for HTTPS/trusted-forwarded HTTPS, direct-host localhost HTTP, or explicit operator opt-in for insecure persistence; public HTTP sandbox URLs degrade to session cookies. Session-creating handlers stamp the final `max_age` on `request.state`, and CSRF cookie creation mirrors that value so the double-submit cookie pair expires together, including explicit re-issue after password changes and OIDC callbacks. A small `HttpOnly` preference cookie preserves the user's remember choice across token re-issue paths. Logout clears all auth cookies and suppresses CSRF re-issue on the logout response.

Localhost persistence deliberately reads the direct request `Host` and ignores `Forwarded` / `X-Forwarded-Host`. Scheme and auth-origin reconstruction still consume forwarding headers. The bundled nginx sets `X-Forwarded-Proto`, but preserves an upstream HTTPS value and does not overwrite every forwarded header, so the outer trusted proxy must replace or strip client-supplied forwarding headers before traffic reaches DeerFlow.

**Routers**:

| Router | Endpoints |
|--------|-----------|
| **Models** (`/api/models`) | `GET /` - list models; `GET /{name}` - model details |
| **Features** (`/api/features`) | `GET /` - report config-gated feature availability (`agents_api.enabled`, `browser_control.enabled`) for frontend UI gating |
| **Console** (`/api/console`) | Read-only cross-thread observability for the current user (the data layer for an operations dashboard or external monitoring): `GET /stats` - headline counters (runs/threads/agents/tokens/cost); `GET /runs` - paginated run history joined with thread titles (per-run cost); `GET /usage` - zero-filled daily token series + per-model breakdown with spend. Queries `runs`/`threads_meta` directly as a reporting layer (no new `RunStore` methods); requires a SQL database backend — returns 503 on `database.backend: memory`. Real-cost estimation reads optional `models[*].pricing` (`currency`, `input_per_million`, `output_per_million`, `input_cache_hit_per_million`; `ModelConfig` is `extra="allow"`, so no schema change) and prices each run from its `token_usage_by_model` input/output split. Pricing is **cache-aware**: `RunJournal` accumulates prompt-cache hits from `usage_metadata.input_token_details.cache_read` into a sparse `cache_read_tokens` bucket key (also threaded through `SubagentTokenCollector` → `record_external_llm_usage_records`), and cache-hit input tokens are billed at `input_cache_hit_per_million` (omitted → billed at the miss price, a conservative upper bound). Legacy rows fall back to run-level totals at `model_name`; unpriced models yield `cost: null` and cost fields are null when no pricing is configured |
| **MCP** (`/api/mcp`) | `GET /config` - get config; `PUT /config` - update config (saves to extensions_config.json) |
| **Skills** (`/api/skills`) | `GET /` - list skills; `GET /{name}` - details; `PUT /{name}` - update enabled; `POST /install` - install from .skill archive (accepts standard optional frontmatter like `version`, `author`, `compatibility`); `POST /reload` - admin-only process-local prompt-cache invalidation after trusted external filesystem changes |
| **Memory** (`/api/memory`) | `GET /` - memory data; `POST /reload` - force reload; `GET /config` - config; `GET /status` - config + data |
| **Uploads** (`/api/threads/{id}/uploads`) | `POST /` - upload files (auto-converts PDF/PPT/Excel/Word); `GET /list` - list; `DELETE /{filename}` - delete |
| **Threads** (`/api/threads/{id}`) | `DELETE /` - remove DeerFlow-managed local thread data after LangGraph thread deletion; `POST /branches` - create a new main-thread branch from a completed assistant turn checkpoint and, when an addressable pre-user replay checkpoint exists, materialize it into the branch namespace so the inherited response remains regeneratable. Workspace files are not checkpointed, so the branch only best-effort copies the current workspace when branching from the **latest** turn (`workspace_clone_mode="current_thread_best_effort"`); branching from an older/historical turn skips the copy (`workspace_clone_mode="skipped_historical_turn"`) so the branch never inherits files that only exist in a later timeline. Branch creation also seeds the new thread's run-event feed from the branch checkpoint's visible messages (`history_seed_mode` in the response): the thread feed reads run_events, not checkpoints, so without the seed the inherited history disappears from the UI after the branch's first run (#4380); `GET /goal`, `PUT /goal`, `DELETE /goal` - read, set, and clear the active thread goal; `POST /compact` - manually summarize older active context into `summary_text` and retain the recent message window, blocked while a run is in flight; unexpected failures are logged server-side and return a generic 500 detail |
| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - serve artifacts; active content types (`text/html`, `application/xhtml+xml`, `image/svg+xml`) are always forced as download attachments to reduce XSS risk; `?download=true` still forces download for other file types |
| **Suggestions** (`/api/suggestions`) | `GET /config` - returns global suggestions config boolean; `POST /threads/{id}/suggestions` - generate follow-up questions; rich list/block model content is normalized and inline reasoning (`<think>...</think>`, including unclosed/truncated blocks from reasoning models like MiniMax-M3) is stripped before JSON parsing |
| **Input Polish** (`/api/input-polish`) | `POST /` - rewrite a composer draft before it is sent. This is a short authenticated `runs:create` LLM request using `input_polish` config; it does not create a LangGraph run, persist a message, or modify thread state. Shares the non-graph one-shot LLM path (`deerflow.utils.oneshot_llm.run_oneshot_llm`) with the suggestions route so model build + Langfuse metadata + invoke stay in one place; validates the same stripped view of the draft it sends to the model, and preserves literal `<think>` substrings in the rewrite (`strip_think_blocks(truncate_unclosed=False)`) |
| **Thread Runs** (`/api/threads/{id}/runs`) | `POST /` - create background run; `POST /stream` - create + SSE stream; `POST /wait` - create + block; `POST /regenerate/prepare` - prepare clean input + checkpoint metadata for regenerating the latest assistant answer; `GET /` - list runs; `GET /{rid}` - run details; `POST /{rid}/cancel` - cancel; `GET /{rid}/join` - join SSE; `GET /{rid}/messages` - paginated per-run messages `{data, has_more}`; `GET /{rid}/events` - full event stream; `GET /{rid}/workspace-changes` - workspace/output file change summary and optional diffs; `GET /../messages` - legacy thread message array; `GET /../messages/page` - backward thread-global `seq` history page with middleware/successful-regenerate filtering and page-run-scoped feedback enrichment; `GET /../token-usage` - aggregate tokens |
| **Feedback** (`/api/threads/{id}/runs/{rid}/feedback`) | `PUT /` - upsert feedback; `DELETE /` - delete user feedback; `POST /` - create feedback; `GET /` - list feedback; `GET /stats` - aggregate stats; `DELETE /{fid}` - delete specific |
| **Runs** (`/api/runs`) | `POST /stream` - stateless run + SSE; `POST /wait` - stateless run + block; `GET /{rid}/messages` - paginated messages by run_id `{data, has_more}` (cursor: `after_seq`/`before_seq`); `GET /{rid}/feedback` - list feedback by run_id |
| **GitHub Webhooks** (`/api/webhooks/github`) | `POST /` - receive GitHub App / repo webhook deliveries. Verifies `X-Hub-Signature-256` against `GITHUB_WEBHOOK_SECRET`; exempt from auth + CSRF because authenticity is enforced by HMAC. The route is fail-closed: mounted only when `GITHUB_WEBHOOK_SECRET` is set, or when explicit dev opt-in `DEER_FLOW_ALLOW_UNVERIFIED_GITHUB_WEBHOOKS=1` is set. Recognized events include `ping`, `issues`, `issue_comment`, `pull_request`, `pull_request_review`, and `pull_request_review_comment`; unknown events return 200 with `handled=false`. Fan-out runtime failures return 503, keeping the delivery recorded as failed for manual/API/scripted redelivery (GitHub does not automatically retry any failed delivery, 5xx included); permanent/non-retryable conditions such as `channels.github.enabled: false`, unknown events, malformed payloads, or unavailable channel service return 200 with a skipped/handled response. |
| **GitHub Event-Driven Agents** | Custom agents can declare a `github:` block in their `config.yaml` to bind to repos and event triggers. Webhook fan-out publishes one `InboundMessage` per matching binding to the channel bus; `GitHubChannel` routes those messages through `ChannelManager`. The response `dispatch` summarizes matched/fired/skipped agents. |

**Workspace change review**: `packages/harness/deerflow/workspace_changes/`
captures a pre-run and post-run snapshot of the thread-owned `workspace` and
`outputs` directories. `runtime/runs/worker.py` performs the filesystem scan via
`asyncio.to_thread` and writes a `workspace_changes` event with category
`workspace` when changes exist. Uploads are intentionally excluded. Text diffs
are size-limited; binary, large, and sensitive-looking paths are persisted as
metadata only.

**RunManager / RunStore contract**:
- `RunManager.get()` is async; direct callers must `await` it.
- The history batch helpers `list_successful_regenerate_sources()` and `get_many_by_thread()` default to `user_id=AUTO`: they resolve the request user and fail closed when no user context exists. Migration/admin callers that intentionally need an unscoped read must pass `user_id=None` explicitly.
- When a persistent `RunStore` is configured, `get()` and `list_by_thread()` hydrate historical runs from the store. In-memory records win for the same `run_id` so task, abort, and stream-control state stays attached to active local runs.
- `cancel()` returns a :class:`~deerflow.runtime.CancelOutcome` enum: `cancelled` (local cancel), `taken_over` (non-owning worker claimed the run because the owner's lease expired — marks it as `error`), `lease_valid_elsewhere` (owner's lease is still alive — caller should return 409 + `Retry-After`), `not_active_locally` (heartbeat disabled, preserving the old 409 path), `not_cancellable` (terminal state), or `unknown` (not found in memory or store). `create_or_reject(..., multitask_strategy="interrupt"|"rollback")` persists interrupted status through `RunStore.update_status()`, matching normal `set_status()` transitions.
- Store-only hydrated runs are readable history. In multi-worker mode with heartbeat enabled, cancel on a store-only run can take over (mark `error`) when the owner's lease has expired past the grace window; otherwise it fails with 409 + `Retry-After`. In single-worker mode (heartbeat off), store-only runs still return 409.
- Startup/orphan reconciliation must claim stale active rows with `RunStore.claim_for_takeover()`, not a plain `update_status()`. The final claim re-checks `status` and lease expiry atomically, so a heartbeat renewal between the candidate scan and the recovery write keeps the run active.
- `POST /wait` (both thread-scoped and `/api/runs/wait`) drains the stream bridge via `wait_for_run_completion()` instead of bare `await record.task`, so it honours the run's `on_disconnect` setting and cancels the background run on real client disconnect rather than returning a stale checkpoint (issue #3265).
- Redis `StreamBridge` keys use a rolling retained-buffer TTL (`stream_bridge.stream_ttl_seconds`, refreshed on `publish()` / `publish_end()`) as a leak safety net, not as a run timeout. Startup orphan recovery publishes `END_SENTINEL` and schedules stream cleanup for recovered runs; malformed `Last-Event-ID` reconnect values live-tail new Redis events rather than replaying the retained buffer. Do not broaden this into a shared-database multi-pod reaper without adding worker ownership/liveness first.
- Thread-scoped run creation accepts `checkpoint` / `checkpoint_id`; Gateway validates the checkpoint belongs to the request thread before writing `checkpoint_id` / `checkpoint_ns` into `config.configurable` for LangGraph branching.
- Thread-scoped Gateway runs evaluate an active `ThreadState.goal` after the visible turn completes. `runtime/goal.py` asks a non-thinking evaluator model to judge only visible conversation evidence and return a typed blocker; the evaluator model is created once per run and reused across hidden continuation checks. The evaluator runs after the graph root's tracing scope has already closed, so `create_goal_evaluator_model`/`evaluate_goal_completion` attach their own model-level tracing callbacks (`attach_tracing=True`) and inject Langfuse trace metadata (`thread_id`/`user_id`/`deerflow_trace_id`) directly onto the `ainvoke` call — the same standalone-caller pattern as `oneshot_llm.run_oneshot_llm` and `MemoryUpdater` (see Tracing System below). Satisfied goals are cleared; every non-satisfied evaluation — continuable or stand-down — is persisted with `last_evaluation` (the blocker, reason, and evidence summary; outcomes that stop the loop additionally record a `stand_down_reason` for observability), but only `goal_not_met_yet` evaluations are streamed as hidden `HumanMessage` continuations, and only when a durable assistant end-of-turn checkpoint exists, the run has not been aborted, the thread did not change during evaluation, and the no-progress breaker has not fired. The continuation cap is 8 — a hard maximum in the `0`–`8` range; callers requesting more are clamped (`set_goal`/TUI) or rejected with 422 (`PUT /goal`). The no-progress breaker keys on the latest visible assistant evidence (not the evaluator's free-text reason, which an LLM rewords every turn), so two consecutive continuations that add no new visible assistant output stop the loop after 2 attempts. Model-response cleanup helpers such as think-block stripping and code-fence stripping live in `deerflow.utils.llm_text` so `runtime/goal.py` and Gateway suggestion parsing share the same JSON-prep behavior.
- Run event stream changes must keep producer code, `deerflow/constants.py`, `runtime/events/catalog.py`, `contracts/run_event_stream_contract.json`, `backend/docs/RUN_EVENT_STREAM.md`, and `tests/test_run_event_stream_contract.py` in sync. The dependency-free constants module owns the persisted envelope limits (`event_type` 32 characters, `category` 16) and cross-layer workspace event identity; the catalog owns validated runtime definitions and categories. Dynamic middleware tags are limited to 21 characters after the `middleware:` prefix. The JSON contract owns payload schemas, backend-specific storage semantics, legacy aliases, and compatibility rules; conformance tests require both views and all producer groups to agree. `run.end.content` remains opaque and may retain nested Python values in memory while JSONL/database stores stringify non-JSON nested values, so consumers must not assume backend-identical nested output representations.

Proxied through nginx: `/api/langgraph/*` → Gateway LangGraph-compatible runtime, all other `/api/*` → Gateway REST APIs.

**Branch/regenerate checkpoint invariant**: `app/gateway/checkpoint_lineage.py`
walks `parent_config` rather than globally ordered checkpoint history so replay
anchors stay on the selected lineage after regenerations create sibling branches.
New conversation branches persist the pre-user replay anchor before their visible
head through the state mutation graph, which preserves materialized state in both
full and delta checkpoint modes. Only an explicitly absent legacy parent link may
use chronological compatibility lookup; cycles, dangling links, and depth-limit
exhaustion fail closed. Existing single-checkpoint branches are never repaired by
copying a raw checkpoint because delta state is not self-contained in one tuple.

### Sandbox System (`packages/harness/deerflow/sandbox/`)

**Interface**: Abstract `Sandbox` with `execute_command(command, env=None)`, `read_file`, `write_file`, `list_dir`. The optional `env` injects per-call environment variables (request-scoped secrets — see Request-Scoped Secrets below); `LocalSandbox` merges it via `subprocess.run(env=...)` and `AioSandbox` routes env-bearing commands through the `bash.exec(env=...)` API on a fresh session.
**Provider Pattern**: `SandboxProvider` with `acquire`, `acquire_async`, `get`, `release` lifecycle. Async agent/tool paths call async sandbox lifecycle hooks so Docker sandbox creation, discovery, cross-process locking, readiness polling, and release stay off the event loop.
**Environment policy** (`sandbox/env_policy.py`): `execute_command` no longer inherits the full `os.environ`. `build_sandbox_env()` scrubs secret-looking names (`*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASS*`/`*CREDENTIAL*`) from the inherited environment before layering injected request secrets on top, so platform credentials (e.g. `OPENAI_API_KEY`) never leak into skill subprocesses. Benign vars (`PATH`, `HOME`, `LANG`, `VIRTUAL_ENV`, ...) are preserved.
**Implementations**:
- `LocalSandboxProvider` - Local filesystem execution. `acquire(thread_id)` returns a per-thread `LocalSandbox` (id `local:{thread_id}`) whose `path_mappings` resolve `/mnt/user-data/{workspace,uploads,outputs}` and `/mnt/acp-workspace` to that thread's host directories, so the public `Sandbox` API honours the `/mnt/user-data` contract uniformly with AIO. `acquire()` / `acquire(None)` keeps the legacy generic singleton (id `local`) for callers without a thread context. Per-thread sandboxes are held in an LRU cache (default 256 entries) guarded by a `threading.Lock`. Legacy global-custom mounts are gated by the same user-scoped skill discovery rule used for prompt/list visibility; providers must not infer visibility from raw directory presence alone.
- `AioSandboxProvider` (`packages/harness/deerflow/community/`) - Docker-based isolation. Active-cache and warm-pool entries are checked with the backend during acquire/reuse; definitively dead containers are dropped from all in-process maps so the thread can discover or create a fresh sandbox instead of reusing a stale client. Backend health-check failures are treated as unknown, not dead; local discovery likewise treats an unverifiable container as not adoptable and falls through to create rather than failing acquire. `get()` remains an in-memory lookup for event-loop-safe tool paths — it never touches the ownership store (that would be blocking IO on the event loop); ownership is published on acquire/reclaim and refreshed off the event loop by the dedicated renewal thread (`_renew_owned_leases`). Legacy global-custom mounts follow the same shared visibility helper as local and remote providers.
- `E2BSandboxProvider` (`packages/harness/deerflow/community/e2b_sandbox/`) - E2B-backed remote isolation. Acquire and the complete release transition (output sync, timeout refresh, client close, and warm-pool publication) share a per-user/thread lock, so a same-process acquire cannot discover or create a replacement while release is between active and warm states. The provider-wide registry lock is not held across remote IO.
  - **Cross-instance ownership store** (`aio_sandbox/ownership/`, #4206): gateway instances sharing a container backend coordinate container ownership through a pluggable lease store, selected by `sandbox.ownership.type` (`memory` | `redis`) and resolved like `stream_bridge` (`factory.py`, lazy per-branch import, `redis` optional extra, `DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL` env escape hatch; a set `DEER_FLOW_STREAM_BRIDGE_REDIS_URL` implies a multi-instance deployment and infers `redis`). `memory` is single-instance only and declares `supports_cross_process = False`.
    - **A lease answers "who reaps this container", not "who may use it".** That splits the interface in two: `take()` transfers ownership on the **acquire** path (a container is deterministic per user/thread, so consecutive turns legitimately land on different instances — a conditional claim there would strand the thread until the previous lease expired), while `claim()` succeeds only if the container is unowned or already ours and gates every **adopt/reap** path. `release()` never clears a peer's lease.
    - **A lease carries a state, and that is what makes the destroy window safe.** `own:` = responsible for this container; `del:` = tearing it down (`claim(..., for_destroy=True)`). `take()` is refused against a `del:` lease, so a container cannot be re-acquired between a destroy path's claim and its container stop. Without the two states an unconditional `take()` would silently overwrite the destroyer's claim and the peer's stop would land on a container the new owner had already handed to an agent — i.e. #4206 again. That pairing is what replaced the previous same-host `flock` guard, which is gone; Redis makes the scope genuinely multi-instance instead of same-host. A destroyer that dies mid-stop leaves a `del:` marker that lapses with the TTL. On the acquire path a refused take raises `SandboxBeingDestroyedError`: the reuse/reclaim paths drop the container and cold-start, and the discover path propagates (falling through to create would collide with the not-yet-removed container name).
    - **The `del:` state has to be *held* for the stop, not just written before it.** The two states alone do not make `flock` redundant — a held lock cannot expire, whereas a lease can, and `claim(..., for_destroy=True)` writes the marker with the ordinary lease TTL. Nothing else refreshes it: `renew()` extends only `own:` and deliberately reports a teardown as `LOST`, and the destroy paths drop the sandbox from the maps `_renew_owned_leases` iterates. So a container stop that outlived the TTL let the marker lapse, a peer's `take()` succeeded against the still-running container, and the stop then landed on the turn that had just been handed it — the exact window `del:` exists to close, reopened by its own expiry. `_held_teardown_lease` wraps **every** `del:`-marked stop — `_destroy_warm_entry`, `destroy()`, and `_drop_unhealthy_sandbox` — and re-claims the marker every `renewal_interval_seconds` until the stop returns. `_drop_unhealthy_sandbox` needs it most: it untracks *before* claiming (under its `expected_info` TOCTOU guard), so `_renew_owned_leases` cannot see the id either. **The final release is the heartbeat's own last act, not the caller's** — a refresh `claim` still in flight when the context exits (the store's socket timeout bounds it, but it can be mid-round-trip) would otherwise land *after* a caller-side release and rewrite `del:` on a container whose stop already completed, stranding a fresh `take()` (or rolling back a fresh create) until the TTL. Releasing from inside the heartbeat, after its loop stops, sequences the release strictly after the last refresh, so no claim can follow it; the context join is bounded and, on a genuine wedge, defers the release to that thread rather than clearing the marker itself. This covers a **failed** stop too (the container is probably still up, and a marker left behind refuses its own thread's `take()` until the TTL lapses); `destroy()` still lets the error propagate out of the `with` — `shutdown()` logs per sandbox off it. `RedisOwnershipStore` sets a `socket_timeout` so no store round trip — and so no heartbeat refresh — can block unbounded, keeping that deferred release finite. This needs no abnormal backend: the schema bounds only `renewal_interval_seconds` (> 0) and `ttl_multiplier` (>= 2), so a legal config puts the TTL below a normal container stop. `LocalContainerBackend._stop_container` now passes a `timeout` to `subprocess.run` (`_STOP_TIMEOUT_SECONDS`) so a wedged daemon cannot block unbounded — that bounds the residual window independently of the ownership layer, for the case where the `del:` marker lapses mid-stop (a store outage longer than the TTL) and the stop then lands on a container a peer has been handed. A timed-out stop propagates rather than being swallowed like a `CalledProcessError`: the container is probably still running, so reporting a clean stop would drop the warm entry and leak it. The TTL stays finite on purpose — the heartbeat dies with the process, so a destroyer that crashes mid-stop still releases the container one TTL later instead of marking it undestroyable forever. Raising a separate teardown TTL instead would only be sufficient if it were bounded above every backend's real stop deadline.
    - **Fail-closed both directions.** Establishment: a sandbox whose ownership cannot be published is never handed out (a just-created container is destroyed rather than leaked as an adoptable orphan) — acquiring raises `OwnershipBackendError`, matching the stream bridge's fail-hard v1 policy. Reaping: a store that cannot answer is treated as peer-owned, so an outage never turns live peer containers into orphans. **Renewal is the deliberate exception**: an unanswerable store there means *unknown*, not lost, so `_refresh_ownership` keeps the sandbox and retries — failing closed on that path would evict every live sandbox on every instance the moment the store blinked. The TTL still bounds how long a genuinely dead owner holds a lease. Both paths that stop a container they still track — `destroy()` and `_destroy_warm_entry` — claim **before** untracking, so a refused claim cannot leave a container running and untracked. (`_drop_unhealthy_sandbox` untracks first, under its `expected_info` TOCTOU guard, then claims before the stop; a refused claim there leaves the container to the next reconcile, which re-adopts it after the grace.)
    - **A lease excludes peers, never ourselves — same-process exclusion is the provider's job.** `claim()` and `take()` both succeed against this instance's own `own:` lease by design (that is what lets a destroy path claim what it already owns), so `del:` says nothing to this process's *other* threads. Every reaper — idle checker, renewal, warm eviction, unhealthy drop — decides outside `self._lock`, because a store round trip must not be held under the lock that guards every acquire; so each one acts on a decision its own acquire path may already have invalidated. Two guards cover the two directions, and both live in `AioSandboxProvider`, not the store:
      - **Reaping** (`_reserve_local_teardown` / `_local_teardown`): the reaper marks the id, and every promote path — `_reuse_in_process_sandbox`, `_reclaim_warm_pool_sandbox`, `_register_discovered_sandbox` — refuses a marked id exactly as it refuses a peer's `del:` (drop and cold-start). The "is this still reapable?" check runs **in the same critical section as the mark**, passed down as a `still_reapable` predicate rather than run by the caller beforehand: checking first and marking second *is* the window, not a narrower version of it. This matters most where the entry deliberately stays visible during the stop — both warm reapers defer their pop so a refused claim cannot lose the container — and where the maps are cleared first (`_drop_unhealthy_sandbox`), which leaves backend discovery as the open path. On `main` the mixin's `_evict_oldest_warm` / `_reap_expired_warm` popped under the lock, so the deferred pop is what made this reachable.
      - **Forgetting** (`_acquire_epoch`): when `renew()` reports `LOST` the peer legitimately wins, so here the *promote* is the thing to detect. `_publish_ownership` bumps a per-id acquire epoch; `_renew_owned_leases` and `release()` snapshot it before the round trip and hand it to `_forget_lost_sandbox`, which skips the pop if it moved. Object identity is not enough: the reuse path re-publishes ownership while handing out the **same** tracked `AioSandbox`, so an identity check sees nothing and the pop closes a client mid-turn.
      - **A guard must become visible no later than the transition it guards.** The epoch cannot satisfy that for `take()`: the takeover is durable before `take()` returns (redis has committed the SET while the reply is in flight), and the epoch can only be written afterwards, so a renewal holding an older `LOST` walks through the gap, drops the maps, and closes the client the acquire is about to hand back — acquire then returns an id whose `get()` is `None`. `_publish_ownership` therefore publishes an **intent mark** (`_acquire_inflight`) under `_lock` *before* the round trip; the epoch covers the other half, "an acquire completed since you decided". `_forget_lost_sandbox` honours the intent mark unconditionally, not only when an epoch is supplied — "no epoch" must not read as "no guard".
      - **A reservation must cover the removal, not just the stop.** `_destroy_warm_entry` pops the warm entry itself, inside the reservation. Releasing the reservation when the stop returns and letting the caller pop afterwards leaves a gap where the container is stopped, the entry is still in `_warm_pool`, and nothing marks it — a reclaim there hands out a dead container. The pop stays deferred relative to the *stop* (a refused or failed stop keeps the entry), just no longer relative to the reservation.
      - **A check taken before a round trip must be retaken after it.** `_reuse_in_process_sandbox` re-verifies both its map entry and the local teardown reservation, `_reclaim_warm_pool_sandbox` re-checks the reservation, and `_register_discovered_sandbox` re-checks before installing its client, all after publishing ownership. Before the intent mark is set a renewal's `LOST` is both current and correct, so the forget can legitimately remove the entry the acquire decided to hand out; independently, a local reaper can reserve an id while reuse is outside `_lock` for its health/store calls and deliberately leaves the map entry present until its destroy claim succeeds. Falling through re-discovers or cold-starts instead of returning/installing a client for either stale decision. The pre-round-trip checks remain as early-outs that skip backend and store work on an already-doomed entry.
      - **Adoption is a promote too.** `_reconcile_orphans` honours the reservation: a container being torn down is untracked and still running, which is exactly the shape that loop adopts, and neither the claim (ours) nor the recovery grace (skipped entirely on `memory`, where `supports_cross_process` is `False`) excludes it.
      - **Active and warm are exclusive, and only a promote can violate it.** Both register paths pop `_warm_pool` inside the same locked section that inserts into `_sandboxes`: a warm entry for an id is stale the moment that id becomes active, and leaving it gives the container *two* reapers — `_reap_expired_warm` judges it by the warm timestamp and never consults `_last_activity`, so it stops a container an agent is using while `_sandboxes` still hands out its client. Reachable because reconciliation adopts into the warm pool inside the register's publish → track window, and on `memory` it adopts on sight (`_adoptable_after_grace` short-circuits when `supports_cross_process` is `False`, so an id carrying this process's own lease reads as adoptable). On `main` the track was a single locked insert with nothing before it, so the window did not exist.
      A non-destroy `claim()` is the one case the store does police against its own owner: it refuses to overwrite our own `del:`, because the stop it marks is already in flight and downgrading the marker would let a `take()` hand out a container about to die. Enforced in both backends (Lua and Python) so they cannot drift.
    - **Renewal is independent of `idle_timeout`** (`_start_lease_renewal`, own daemon thread; TTL = `renewal_interval_seconds × ttl_multiplier`). Renewal used to ride on the idle checker, which `__init__` only starts when `idle_timeout > 0` — so `idle_timeout: 0` ("keep warm VMs until shutdown", a documented config) let every lease lapse. Liveness and reaping must not share a switch. Renewal covers warm entries as well as active ones; losing a lease drops the sandbox from this instance's maps **without touching the container** (`_forget_lost_sandbox`) — destroying it there would be the very cross-instance kill this store prevents.
      - A warm teardown is the local exception to that forget rule: `_destroy_warm_entry` deliberately keeps the entry in `_warm_pool` until the backend stop succeeds, while its own `del:` marker makes ordinary `renew()` report `LOST`. `_forget_lost_sandbox` therefore honours `_local_teardown`; otherwise the renewal thread can pop the retained entry mid-stop and a failed stop leaves a running container untracked.
    - **`renew()` distinguishes lapsed from lost** (`RenewOutcome`), and the two must not be collapsed. `LAPSED` means the lease is simply absent — nobody took it — so `_refresh_ownership` re-establishes it; `LOST` means a peer holds it and it is never re-taken. Treating an absent lease as lost meant a Redis restart without persistence (every key gone) evicted every in-flight sandbox on every instance at once.
      - Renewal's fail-open rule covers both store round trips. If `renew()` returns `LAPSED` but the follow-up `claim()` cannot answer, ownership is still unknown rather than lost, so the provider keeps the sandbox and retries. The ordinary `_claim_ownership` helper remains fail-closed for adopt/reap callers and is intentionally not used for this re-claim.
    - **Teardown join budget covers refresh plus release.** Redis bounds each ownership operation at five seconds, and context exit can catch the heartbeat in one final refresh before its `finally` performs the final release. `_TEARDOWN_JOIN_TIMEOUT_SECONDS` is therefore 12 seconds — greater than both sequential operation bounds — so a normal pair of socket timeouts does not emit the deferred-release warning; a still-running heartbeat continues to own the release safely.
    - **An absent lease means the same thing on both paths, and reconciliation must say so too.** The `LAPSED` rule above only covers an owner renewing its *own* lease; on its own it does not make state loss safe, because reconciliation reads the same absent key as "orphan, adopt". After a Redis flush (restart without persistence, or eviction under `maxmemory`) every owner is alive and merely pre-renewal-tick, so whichever instance reconciles first would adopt every live container, each real owner's next renewal would report `LOST`, and it would drop a sandbox mid-turn for the adopter to idle-destroy — #4206 through the back door. `_adoptable_after_grace` closes it: an untracked container must be seen unowned (`owner()`, a read-only peek — the atomic `claim()` is still what actually gates adoption) across a full lease TTL before it can be adopted, tracked per container in `_unowned_since`. That rebuilds the delay the flush erased — a live owner republishes within one renewal interval, shorter than the TTL by construction (`ttl_multiplier >= 2`) — while a genuinely crashed owner never republishes, so its containers are still adopted one grace later rather than leaking. A republished lease **resets** the grace; a pausing-only timer would still expire over a live owner's lease. The grace is skipped when `supports_cross_process` is `False`: no peer can hold a lease such a store would show us, so single-instance deployments keep instant orphan cleanup, and a grace could not help a multi-worker gateway on `memory` anyway (peers are invisible to each other's leases with or without it).
    - **The `memory` store is single-instance only** and says so via `supports_cross_process = False`; the provider logs a warning at startup when the configured store cannot see peers. A multi-worker gateway on `memory` has no cross-process coordination at all — same contract as `stream_bridge`'s memory backend. This is why the redis inference matters: it reads `app_config.stream_bridge` **and** the env var, in the same order the bridge's own resolver does, so any deployment already pointing the bridge at Redis (i.e. every multi-instance one) gets a redis ownership store without extra config.
    - `get()` stays a pure in-memory lookup and must never call the store (that is blocking filesystem/network IO on the event loop); anchored by `tests/blocking_io/test_aio_sandbox_get.py`, which injects a deliberately-blocking probe store so the anchor keeps its teeth regardless of the configured backend. Tests: `tests/test_sandbox_ownership_store.py` (store contract, defined once for **both** backends — but the redis tier is `@pytest.mark.integration` + opt-in via `DEER_FLOW_TEST_REDIS_URL` and self-skips, and **CI provisions no redis**, so the merge gate runs the memory tier only and the Lua scripts never execute there; drift between the backends is caught only when the suite runs against a live redis. There is no fake-redis tier because the redis exclusion lives in Lua a fake would not execute) and `tests/test_sandbox_orphan_reconciliation.py` (provider behaviour, two providers sharing one store).
- `BoxliteProvider` (`packages/harness/deerflow/community/boxlite/`) - BoxLite micro-VM isolation. The `boxlite` runtime is optional (`deerflow-harness[boxlite]`) and lazy-imported only when this provider is selected. The provider owns one private asyncio event loop on a daemon thread because BoxLite handles are loop-affine; sync `Sandbox` calls marshal onto that loop with `run_coroutine_threadsafe`.
  Boxes are named deterministically from `user_id:thread_id`, released into an in-process warm pool after each agent turn, and reclaimed only by the same user/thread. Warm-pool health checks use a short explicit timeout and forward that timeout through both BoxLite `exec(timeout=...)` and the private-loop `.result(timeout)` bridge so a hung VM cannot pin the per-thread acquire lock indefinitely.
  `sandbox.replicas` caps active + warm VMs per gateway process; if capacity is exhausted, only warm-pool VMs are evicted. `sandbox.idle_timeout` stops idle warm VMs after the configured seconds. `reset()` is intentionally a lightweight registry clear for `reset_sandbox_provider()` and does not close boxes, stop the idle reaper, or close the private loop; full teardown remains `shutdown()`.


**Shared warm-pool lifecycle:** community sandbox providers that keep released sandboxes alive for fast reuse share `deerflow.community.warm_pool_lifecycle.WarmPoolLifecycleMixin`. The mixin owns the common `DEFAULT_IDLE_TIMEOUT=600`, `IDLE_CHECK_INTERVAL=60`, `DEFAULT_REPLICAS=3`, idle-checker loop, warm-pool expiry, oldest-warm eviction, replica counting, and soft-cap logging. Providers remain responsible for their own active registries, creation/discovery, health checks, and destroy hook (`_destroy_warm_entry`): AIO destroys `SandboxInfo` through its backend; Boxlite closes loop-affine `BoxliteBox` handles. AIO keeps active-idle cleanup outside the mixin and delegates only warm-pool expiry to the shared helper.

**Virtual Path System**:
- Agent sees: `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`
- Physical: `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`, `deer-flow/skills/`
- Translation: `LocalSandboxProvider` builds per-thread `PathMapping`s for the user-data prefixes at acquire time; `tools.py` keeps `replace_virtual_path()` / `replace_virtual_paths_in_command()` as a defense-in-depth layer (and for path validation). AIO has the directories volume-mounted at the same virtual paths inside its container, so both implementations accept `/mnt/user-data/...` natively.
- Detection: `is_local_sandbox()` accepts both `sandbox_id == "local"` (legacy / no-thread) and `sandbox_id.startswith("local:")` (per-thread)

**Sandbox Tools** (in `packages/harness/deerflow/sandbox/tools.py`):
- `bash` - Execute commands with path translation and error handling. For `LocalSandbox` (host bash), POSIX output is captured through bounded pipe-drain threads and stdin is `/dev/null`, so a backgrounded long-lived process (`server &`) returns immediately instead of blocking the turn on an inherited pipe, while unredirected background output is drained without growing anonymous temp files. Commands that read stdin get immediate EOF. The command runs in its own process group with a wall-clock timeout (`sandbox.bash_command_timeout`, default 600s); on timeout the whole group is killed and the agent gets a notice telling it to background long-lived processes. The bash tool description itself also instructs the model to background long-lived processes (e.g. servers) up front so it doesn't waste the turn waiting on a foreground server. See `LocalSandbox.execute_command` / `_run_posix_command` and `bash_tool`'s docstring.
- `ls` - Directory listing (tree format, max 2 levels)
- `read_file` - Read file contents with optional line range
- `write_file` - Write/append to files, creates directories; overwrites by default and exposes the `append` argument in the model-facing schema for end-of-file writes; subject to the read-before-write gate when `read_before_write.enabled` (see Middleware Chain)
- `str_replace` - Substring replacement (single or all occurrences); same-path serialization is scoped to `(sandbox.id, path)` so isolated sandboxes do not contend on identical virtual paths inside one process; subject to the read-before-write gate when `read_before_write.enabled` (see Middleware Chain)

### Subagent System (`packages/harness/deerflow/subagents/`)

**Built-in Agents**: `general-purpose` (all tools except `task`) and `bash` (command specialist)
**User-scoped Skills**: Subagents resolve their configured skills through `get_or_new_user_skill_storage(user_id)` using the parent runtime identity, with `DEFAULT_USER_ID` only when no identity is available. This keeps custom-skill shadowing and visibility aligned with the lead agent instead of reading the global-only catalog.
**Execution**: Dual thread pool - `_scheduler_pool` (3 workers) + `_execution_pool` (3 workers)
**Concurrency and total delegation cap**: `MAX_CONCURRENT_SUBAGENTS = 3` is enforced by `SubagentLimitMiddleware` (truncates excess tool calls in `after_model`; runtime `max_concurrent_subagents` is clamped to 2-4). The same middleware also enforces `subagents.max_total_per_run` (default 6, config schema 1-50, runtime override `max_total_subagents` clamped to the same range) against current-run entries in the durable delegation ledger, so a long lead-agent run cannot bypass concurrency limits by launching repeated legal-sized batches at each planning checkpoint, but historical delegations from previous runs in the same thread do not consume the new run's budget. The lead-agent prompt uses the same clamped values, so model-visible limits match enforcement. Gateway `run_agent()` and embedded `DeerFlowClient.stream()` both provide a per-invocation `run_id` in runtime context; `DeerFlowClient.stream()` also tags its input `HumanMessage` with that same id so durable-context capture can identify the current request boundary. Gateway resume paths may not append a new `HumanMessage`, so the worker also exposes the pre-run checkpoint's message ids in runtime context; durable-context capture uses that as the current-run boundary and never re-tags older task calls as the resumed run. When no delegation slots remain, task calls are stripped, provider raw tool-call metadata is synced, `finish_reason` is forced to `stop`, and a visible "subagent delegation limit" note is appended so the agent can synthesize already-collected results. Default subagent timeout `subagents.timeout_seconds=1800` (30 min) and built-in `general-purpose` `max_turns=150` (raised from 100/15-min so deep-research subtasks stop hitting `GraphRecursionError` out of the box)
**Flow**: `task()` tool → `SubagentExecutor` → background thread → poll 5s → SSE events → result. `task_started` carries the resolved effective model name. The per-subagent `SubagentTokenCollector` publishes a cumulative usage snapshot to the shared `SubagentResult` after every completed LLM response; the next `task_running` event carries that snapshot, so collapsed workspace cards can update without re-accounting parent-run totals. Terminal ToolMessage metadata (`subagent_model_name`, `subagent_token_usage`) and the persisted `subagent.end` event retain the model/usage after reload; absent provider usage stays absent rather than being estimated as zero.
**Events**: `task_started`, `task_running`, `task_completed`/`task_failed`/`task_timed_out`
**Handled LLM failures**: `LLMErrorHandlingMiddleware` deliberately converts provider/model exceptions into an `AIMessage` so the graph can end cleanly, stamping `additional_kwargs.deerflow_error_fallback=true` plus error metadata. Clean graph termination does not imply subagent success: `SubagentExecutor` inspects the last assistant message at terminalization and maps a marked fallback to `SubagentStatus.FAILED`, which then emits `task_failed` and the existing structured `subagent_error`. Only the marker is authoritative — error-looking assistant prose without it remains a normal completed result, so neither the executor nor frontend parses display text as a status protocol.
**Guardrail caps & `stop_reason` (#3875 Phase 2)**: three independent axes can end a subagent run early, and all now surface *why* through one additive field rather than a new status enum. **Turn axis**: `recursion_limit` on the subagent `run_config` equals `max_turns`, so exhausting the turn budget raises `GraphRecursionError` from `agent.astream`; `executor.py::_aexecute` catches it specifically (before the generic `except Exception`). **Token axis**: `TokenBudgetMiddleware` is attached per-agent via `build_subagent_runtime_middlewares` from `subagents.token_budget` (default `max_tokens` **coupled to `summarization.enabled`** — 1,000,000 when subagent summarization is on, 2,000,000 when off, warn at 0.7, hard-stop at 1.0; a user-set budget always wins regardless of the switch — #3875 Phase 3; a backstop against a subagent that burns tokens on trivial work). It does *not* raise: at the hard-stop threshold it strips the in-flight turn's tool calls, forces `finish_reason="stop"`, and lets the run complete naturally with a final answer. **Loop axis**: `LoopDetectionMiddleware` (attached at the same point) catches repeated identical tool-call sets — or one tool *type* called many times with varying args — and its hard-stop likewise strips `tool_calls` and forces a final answer without raising, recording `loop_capped`. Each guard exposes its cap on a per-`run_id` `consume_stop_reason(run_id)` accessor; `_aexecute` collects **every** middleware with that method (duck-typed via `hasattr`, so the executor has no import coupling to the guard classes) and surfaces the first non-`None` reason — adding a future guard needs no executor change. **Surfacing**: whichever axis fired, `_aexecute` stamps a normal status plus an additive reason — `completed` + `stop_reason=token_capped|turn_capped|loop_capped` when a usable final answer (or partial recovered from the last streamed chunk via `_extract_final_result` → `utils/messages.py::message_content_to_text`, returning a `"No response Generated"` sentinel when no text survived) was produced; `failed` + `stop_reason=turn_capped` when nothing usable survived. `SubagentResult.stop_reason` flows through `task_tool.py::_task_result_command` → `format_subagent_result_message` (renders `Task Succeeded (capped: ...)` / `Task failed (capped: ...)`) and `make_subagent_additional_kwargs`, which stamps the additive `subagent_stop_reason` key alongside the normal `subagent_status`. **Why additive, not an enum**: a new status value would break v1 consumers; an optional field is ignored by older frontends and ledger readers, so the cross-language contract (`contracts/subagent_status_contract.json` v2 + `subagents/status_contract.py` + `frontend/.../subtask-result.ts`, pinned by `test_status_values_match_contract` / `test_stop_reason_values_match_contract`) stays backward-compatible. The durable delegation ledger captures `stop_reason` onto the entry and renders model-facing guidance ("hit a guardrail cap with a partial result; reuse it, retry tighter, or raise the per-agent budget (`max_turns` / `token_budget`)") so the lead reuses a capped completion knowingly instead of mistaking it for a clean one. (Phase 1 shipped this surfacing as a `MAX_TURNS_REACHED` status enum in #3949; Phase 2 replaced that enum with the additive `stop_reason` field per the agreed design — the `max_turns_reached` status value and `SubagentStatus.MAX_TURNS_REACHED` are gone.)
**Context compaction (#3875 Phase 3, #4039)**: subagents inherit `DeerFlowSummarizationMiddleware` via `build_subagent_runtime_middlewares`, gated on the **same** `summarization.enabled` switch the lead reads (one config covers both chains; trigger/keep/model/prompt come from the shared `summarization` config so they cannot drift). The subagent builder attaches `DurableContextMiddleware` immediately before summarization, using the same skills path/read-tool settings as the lead chain. Compaction stores the generated summary in `ThreadState.summary_text` rather than as a `messages` item; the durable-context wrapper therefore projects it into the next model request as guarded hidden human data. This is required when a message-count keep policy preserves only an assistant tool-call plus its tool results: without the injected summary the next request begins with assistant/tool history and strict OpenAI-compatible providers can reject it. Because `DurableContextMiddleware` inserts a second `SystemMessage(authority_contract)` after the subagent's leading system prompt, the builder also appends `SystemMessageCoalescingMiddleware` innermost (mirroring the lead chain, appended after the optional summarization middleware so it is unconditionally last) to merge every `SystemMessage` into one leading `system_message` — otherwise the durable fix would trade #4039's assistant-first HTTP 400 for a duplicate-system 400 on the same strict backends (#4040). The factory is called with `skip_memory_flush=True` on the subagent path: the lead's `memory_flush_hook` (attached when `memory.enabled`) flushes pre-compaction messages into durable memory keyed by `thread_id`, and subagents share the parent's `thread_id`, so without skipping the hook a subagent's internal turns would pollute the **parent** thread's durable memory. Placement differs from the lead chain (lead appends summarization *before* the guard trio; subagent appends it *after*) — benign because the middleware implements only `before_model` (compaction) with no `after_model`/`consume_stop_reason`, so it cannot disturb the Phase 2 guard-cap stop-reason channel. Compaction rewrites the messages channel via `RemoveMessage(id=REMOVE_ALL_MESSAGES)`, which shrinks `len(messages)` below the step-capture cursor mid-run; `capture_new_step_messages` (see Step capture below) resets the cursor to the new tail on contraction so steps appended after the compaction point are not silently dropped.
**Step capture & persistence (#3779)**: `executor.py` captures both assistant turns (`AIMessage`) **and** tool outputs (`ToolMessage`) via `subagents/step_events.py::capture_new_step_messages`, which walks the *newly-appended tail* of each `stream_mode="values"` chunk (not just `messages[-1]`) so a multi-tool-call turn — where LangGraph's `ToolNode` appends several `ToolMessage`s in one super-step — keeps every tool output instead of dropping all but the last. `runtime/runs/worker.py::_SubagentEventBuffer` additionally persists these `task_*` custom events to the `RunEventStore` as `subagent.start`/`subagent.step`/`subagent.end` (`category="subagent"`, `task_id` in `metadata`). It **batches** writes via `put_batch` (flushing on a terminal `subagent.end`, at `FLUSH_THRESHOLD` events, and in the worker's `finally`) rather than one `put()` per step, since `put()` is a documented low-frequency path (per-thread advisory lock per call) and a deep subagent (`max_turns=150`) emits hundreds of steps on the hot stream loop. `subagent_run_event` rejects malformed chunks that lack a non-empty `task_id`; running chunks additionally require a non-negative integer `message_index` and a message object, so persisted records always satisfy the required lifecycle envelope. `build_subagent_step` caps both the per-step `text` and each tool call's serialized `args` at `SUBAGENT_STEP_MAX_CHARS` (flagged `truncated` / `args_truncated`) so a large `write_file`/`bash` payload can't produce an unbounded row. The dedicated category keeps them out of `list_messages` (the thread feed) while `list_events` returns them for the frontend's fetch-on-expand backfill. `list_events` accepts `task_id` (filters on `metadata["task_id"]` — SQL-side in `DbRunEventStore` via `event_metadata["task_id"].as_string()`, in-memory in the JSONL/memory stores) plus an `after_seq` forward cursor, so the card pages through one subagent's steps without the run-wide `limit` truncating the tail (no schema migration: the filter rides the existing run-scoped index). `step_events.py` is a pure, unit-tested layer (`build_subagent_step` / `subagent_run_event`). **History contraction (#3875 Phase 3)**: `capture_new_step_messages` assumes append-only growth, but `DeerFlowSummarizationMiddleware` rewrites the messages channel via `RemoveMessage(id=REMOVE_ALL_MESSAGES)`, shrinking `len(messages)` below the cursor mid-run. On contraction (`total < processed_count`) the cursor resets to the new tail; `capture_step_message`'s id/content dedup prevents re-emitting pre-compaction steps, so steps appended after the compaction point are still captured instead of being dropped until `total` overtakes the stale cursor.
**Deferred MCP tools** (if `tool_search.enabled`): `SubagentExecutor._build_initial_state` assembles deferral after policy filtering via the shared `assemble_deferred_tools` (fail-closed), appends the `tool_search` tool, injects the `<available-deferred-tools>` section into the subagent's `SystemMessage`, and threads the setup to `_create_agent`, which attaches `McpRoutingMiddleware` (when PR1 routing metadata matches deferred tools) before `DeferredToolFilterMiddleware` through `build_subagent_runtime_middlewares(...)`. Subagents thus withhold full MCP schemas until promotion, same as the lead agent; each task run gets a fresh `ThreadState` so promotion is isolated per run
**Checkpointer isolation**: Subagent graphs are compiled with `checkpointer=False` to avoid inheriting the parent run's checkpointer, since subagents are one-shot and never resume.
**Checkpoint lineage / stream isolation**: `_aexecute` deliberately omits checkpoint-coordinate keys (`thread_id`, `checkpoint_ns`, `checkpoint_id`, `checkpoint_map`) from the child `RunnableConfig`. LangGraph must inherit those coordinates from the copied parent ContextVar so the delegated graph retains a non-root subgraph namespace; explicitly re-supplying even the same parent `thread_id` starts a new root lineage on LangGraph 1.2.6+ and can route child AI/tool frames into the parent `messages` stream. DeerFlow business components still receive the parent `thread_id` through `runtime.context`, which is the preferred lookup path for sandbox, middleware, and attribution code. Regression coverage in `tests/test_subagent_executor.py::TestSubagentCheckpointLineage` keeps the invocation-contract assertion active on every supported version and version-gates the production-shaped parent-stream test to LangGraph 1.2.6+, where the leak exists.

### Tool System (`packages/harness/deerflow/tools/`)

`get_available_tools(groups, include_mcp, model_name, subagent_enabled)` assembles:
1. **Config-defined tools** - Resolved from `config.yaml` via `resolve_variable()`
2. **MCP tools** - From enabled MCP servers (lazy initialized, cached with resolved-path + content-signature invalidation)
3. **Built-in tools**:
   - `present_files` - Make output files visible to user (only `/mnt/user-data/outputs`)
   - `ask_clarification` - Request clarification (intercepted by ClarificationMiddleware, which preserves text fallback and adds `artifact.human_input` for Web UI Human Input Cards)
   - `view_image` - Read image as base64 (added only if model supports vision)
   - `setup_agent` - Bootstrap-only: persist a brand-new custom agent's `SOUL.md` and `config.yaml`. Bound only when `is_bootstrap=True`.
   - `update_agent` - Custom-agent-only: persist self-updates to the current agent's `SOUL.md` / `config.yaml` from inside a normal chat (partial update + atomic write). Bound when `agent_name` is set and `is_bootstrap=False`.
4. **Subagent tool** (if enabled):
   - `task` - Delegate to subagent (description, prompt, subagent_type)

Scheduled-task runtime note:
- Scheduled background runs set `context.non_interactive=true` and therefore exclude `ask_clarification` from the lead-agent tool list. This keeps scheduler-triggered runs from stalling on human confirmation mid-execution. `non_interactive` is an internal-only context key: it is merged from `body.context` only when the request authenticated as the process-internal user (the scheduler path), never from arbitrary HTTP/IM clients.

**Community tools** (`packages/harness/deerflow/community/`): optional integrations, each in its own subpackage and wired through `config.yaml`. Documented examples:
- `tavily/` - Web search (5 results default) and web fetch (4KB limit)
- `jina_ai/` - Web fetch via Jina reader API with readability extraction
- `firecrawl/` - Web scraping via Firecrawl API
- `image_search/` - Image search via DuckDuckGo
- `aio_sandbox/` - Docker-based isolation (`AioSandboxProvider`)
- `browser_automation/` - Agentic browser control (stateful `navigate → observe → click/type` loop) via Playwright, distinct from the read-only `web_fetch`/`web_capture` tools. Tools: `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_back`, `browser_screenshot`, `browser_close` (config `group: browser`). A process-local `BrowserSessionManager` owns one private, loop-affine Playwright event-loop thread (same pattern as the BoxLite provider) so a per-thread browser session survives across turns regardless of the caller's loop (Gateway / TUI / test). Each action returns a fresh page snapshot whose interactive elements are addressed by a stable numeric `[ref]` index (stamped as `data-df-ref` during snapshot), so the model acts on what it just observed instead of holding stale handles or guessing selectors. URLs are SSRF-screened via the shared `validate_public_http_url` (opt-out `allow_private_addresses` only for intentional internal targets). CDP attachment cannot install the request guard on an existing Chrome context, so `cdp_url` fails closed unless the operator explicitly sets `allow_unguarded_cdp: true` for a trusted local browser. Browser REST/Live access also requires an exact non-NULL thread owner, rather than the general legacy shared-thread policy, because retained pages may contain authenticated state. Session admission is a hard `max_sessions` cap: pinned Live/operation sessions are never evicted, and a new thread is rejected when no unpinned session can be closed; one Live viewer owns a session at a time. Optional dependency: `cd backend && uv sync --extra browser && uv run playwright install chromium`; `scripts/detect_uv_extras.py` preserves the extra when `config.yaml` enables `browser_navigate`, and Gateway startup fails fast if configured browser control cannot import Playwright. Tests: `tests/test_browser_automation.py` (mocked tools + a real-Chromium integration test guarded by `importorskip`); `tests/manual_browser_live_check.py` is a manual DeepSeek-driven end-to-end check (not collected by pytest).
  Live UI input dispatch is kept independent from JPEG capture: non-move actions start a rate-limited background refresh loop, so pointer, wheel, or keyboard input stays responsive while continuous gestures still produce frames throughout the interaction.

Additional providers also live here (`boxlite`, `brave`, `browserless`, `crawl4ai`, `ddg_search`, `e2b_sandbox`, `exa`, `fastcrw`, `groundroute`, `infoquest`, `searxng`, `serper`); see each subpackage for specifics. E2B bootstrap is required. If it fails, the provider kills and closes the unusable remote sandbox. New sandbox creation raises an error. Warm-pool reclaim and remote discovery discard the sandbox and continue acquisition. E2B mounts remain optional.

E2B output sync records remote file versions and actual host file metadata in a thread-local manifest. The manifest binds to the remote sandbox ID. A complete output listing removes entries for deleted files. This avoids repeat downloads when the host filesystem rounds modification times. A single release-time sync pass is bounded by aggregate ceilings (`_MAX_SYNC_TOTAL_BYTES`, `_MAX_SYNC_FILES`, `_SYNC_DEADLINE_SECONDS`) on top of the per-file `_MAX_DOWNLOAD_SIZE` cap, so a pathological outputs tree cannot make release download unboundedly; a truncated pass logs what it dropped and leaves the manifest un-pruned (only entries observed in that pass are reconciled), so files it never reached are retried on the next release rather than being forgotten.

**ACP agent tools**:
- `invoke_acp_agent` - Invokes external ACP-compatible agents from `config.yaml`
- ACP launchers must be real ACP adapters. The standard `codex` CLI is not ACP-compatible by itself; configure a wrapper such as `npx -y @zed-industries/codex-acp` or an installed `codex-acp` binary
- Missing ACP executables now return an actionable error message instead of a raw `[Errno 2]`
- Each ACP agent uses a per-thread workspace at `{base_dir}/users/{user_id}/threads/{thread_id}/acp-workspace/`. The workspace is accessible to the lead agent via the virtual path `/mnt/acp-workspace/` (read-only). In docker sandbox mode, the directory is volume-mounted into the container at `/mnt/acp-workspace` (read-only); in local sandbox mode, path translation is handled by `tools.py`

### MCP System (`packages/harness/deerflow/mcp/`)

- Uses `langchain-mcp-adapters` `MultiServerMCPClient` for multi-server management
- **Lazy initialization**: Tools loaded on first use via `get_cached_mcp_tools()`
- **Cache invalidation**: Detects extensions-config changes by comparing the resolved config path and a `(mtime, size, sha256)` content signature against the values recorded at initialization, not a strict mtime `>` comparison. This catches same-second edits, mtime that stays put or moves backward (`git checkout`, `cp -p` / backup restore, `tar` / `rsync`, object-store / network mounts), and a switch to a different config file with an equal-or-older mtime. The signature helper (`config/file_signature.py::get_config_signature`) is shared with `config/app_config.py::get_app_config()` for the sibling runtime-editable config file, rather than each maintaining its own copy. `ExtensionsConfig.resolve_config_path()` raises `FileNotFoundError` for an explicit `config_path`/`DEER_FLOW_EXTENSIONS_CONFIG_PATH` that points at a missing file — an operator-asserted path going missing is a real misconfiguration, so this is intentionally loud for callers that load the config for actual use (e.g. `from_file()` via `get_mcp_tools()`); only the fallback search mode returns `None`. The MCP cache's own path resolution (`mcp/cache.py::_resolve_config_path`) is narrower: it catches that specific `FileNotFoundError` locally and treats it the same as "unconfigured", so this staleness check degrades to "not stale" instead of propagating an exception when a previously-valid explicit/env-var config disappears mid-run
- **Transports**: stdio (command-based), SSE, HTTP
- **OAuth (HTTP/SSE)**: Supports token endpoint flows (`client_credentials`, `refresh_token`) with automatic token refresh + Authorization header injection
- **Routing hints**: `extensions_config.json -> mcpServers.<server>.routing` and
  `tools.<original_tool_name>.routing` are soft preference metadata. The effective
  routing is resolved while `mcp/tools.py::get_mcp_tools()` still has both
  `source_name` and the original MCP tool name, then stored on `tool.metadata`
  under `deerflow_mcp_routing`. Prompt rendering uses
  `tools/builtins/tool_search.py::get_mcp_routing_hints_prompt_section`, which
  references `tool_search` when a hinted MCP tool is currently deferred; do not
  add a parallel routing middleware for PR1-style preference hints.
- **Stdio file outputs**: Persistent stdio sessions are scoped by `user_id:thread_id`. For stdio transports only, DeerFlow pins the subprocess default `cwd` to the thread workspace and `TMPDIR`/`TMP`/`TEMP` to `workspace/.mcp/tmp/`, unless the operator explicitly configured `cwd` or temp env values. SSE/HTTP transports skip this filesystem prep entirely.
- **Stdio path translation**: MCP-returned local file references are not copied. If a `ResourceLink` or conservative free-text path resolves to an existing file inside the thread's mounted user-data tree, it is translated deterministically to `/mnt/user-data/...`; paths outside that tree remain unchanged.
- **Runtime updates**: Gateway API saves to extensions_config.json; the Gateway-embedded runtime detects changes via the resolved-path + content-signature check above, so multi-worker / stale-mtime deployments still pick up an added/removed MCP server without a restart (the `PUT /api/mcp/config` reset only clears the cache in its own worker)

### Skills System (`packages/harness/deerflow/skills/`)

- **Location**: `deer-flow/skills/{public,custom}/`
- **Format**: Directory with `SKILL.md` (YAML frontmatter: name, description, license, allowed-tools, required-secrets)
- **Loading**: `load_skills()` recursively scans namespace directories under `skills/{public,custom}`, but stops descending once it finds a `SKILL.md`; that directory is a package boundary, so no nested `SKILL.md` is registered as a runtime skill. SkillScan has a deliberately narrower packaging rule: known eval fixtures are permitted as support data, while other nested `SKILL.md` files are reported as package defects. It parses runtime metadata and reads enabled state from extensions_config.json.
- **External reload**: `POST /api/skills/reload` is an admin-only, process-local invalidation hook for trusted MinIO/NFS/CSI writes. `SkillStorage` instances do not cache a catalog — `load_skills()` scans on every call — so the route clears all `(app_config, user_id)` entries and the rendered prompt-section LRU, then waits up to the shared refresh timeout for the existing off-loop single-flight refresh. Each invalidation receives a generation-bound result handle; a successful scan atomically replaces the global enabled-skills cache, while a loader-level failure propagates to the HTTP waiter and preserves the last-known-good global cache. Per-user/config scans capture the refresh version and cannot repopulate shared caches if invalidation occurs while they are loading. A timed-out HTTP wait fails generically while the daemon refresh worker continues. Subsequent runs rescan after a successful reload; active runs keep their existing snapshot. Each Uvicorn worker/Kubernetes Pod must be targeted separately. Direct mount writes bypass install/edit validation, SkillScan, and history, so mounted roots are an operator-controlled trust boundary.
- **Tool policy**: Lead-agent `allowed-tools` declarations apply dynamically only to slash-activated skills and skills captured in `ThreadState.skill_context` through configured `read_file` loads; passive enabled skills and custom-agent skill allowlists remain discoverable without clamping the global toolset. Slash policy is dominant for its run, preventing subsequently read skills from widening explicit authority; autonomous captured skills use the existing union only when no slash source exists. `tool_search` and `describe_skill` stay available as framework discovery infrastructure, while every discovered or promoted business tool still requires active-policy permission for schema visibility and execution; `task` likewise requires an explicit declaration. Each active model call intentionally reloads the full live registry so enable/disable changes, frontmatter edits, and custom/public name-shadow winners take effect without a stale TTL or unsafe direct-path cache; all tool calls produced by that model step reuse the resulting source-and-path-signed decision. Registry failures and all-invalid active sets fail closed, while stale individual paths are skipped when another valid skill remains. This is best-effort behavioral scoping, not a hard security boundary: alternate loading paths are not captured and bounded autonomous context may evict entries. Subagents still filter statically because their configured skills are all loaded into the session at startup.
- **Injection (legacy / default)**: Enabled skills are listed in the agent system prompt with full metadata and container paths (`<available_skills>` block). Controlled by `skills.deferred_discovery: false` (default).
- **Deferred discovery** (`skills.deferred_discovery: true`): Skills are listed by name only in a compact `<skill_index>` block, keeping the system prompt prefix-cache friendly. The agent calls the `describe_skill` tool at runtime to fetch full metadata for skills it wants to use, then loads the SKILL.md via `read_file`. Two new modules support this path:
  - `skills/catalog.py` — `SkillCatalog` (immutable, searchable; query forms: `select:a,b`, `+prefix`, free-text regex); `select:` returns all requested skills without a result cap; other modes cap at `MAX_RESULTS=5`.
  - `skills/describe.py` — `build_describe_skill_tool(catalog)` builds the `describe_skill` tool as a closure; `build_skill_search_setup(skills, enabled, ...)` produces a `SkillSearchSetup(describe_skill_tool, skill_names)` that is wired into both the LangGraph agent factory (`agent.py`) and the embedded client (`client.py`).
- **Slash activation**: `/skill-name task` loads that enabled skill's `SKILL.md` for the current model call only. The resolver rejects leading whitespace, missing separators, reserved channel commands (`/new`, `/help`, `/bootstrap`, `/status`, `/models`, `/memory`, `/goal`), disabled skills, and skills outside a custom agent's whitelist.
- **Installation**: `POST /api/skills/install` extracts .skill ZIP archive to custom/ directory
- **SkillScan**: `packages/harness/deerflow/skills/skillscan/` is the native deterministic scanner for `.skill` archives and agent-managed skill writes. It runs offline before the LLM scanner, emits structured findings (`rule_id`, `severity`, `file`, `line`, `message`, `remediation`, redacted `evidence` — category/analyzer are encoded in the `rule_id` prefix), blocks `CRITICAL`, and passes warning findings into `scan_skill_content()`. `scan_archive_preflight()` / `scan_skill_dir()` are pure sync functions (dispatch off the event loop); `enforce_static_scan()` applies the blocking policy and the `skill_scan.enabled` kill switch. The Python instance-client signal deliberately follows only a one-level, same-scope evidence chain (PR #4265 review): a proven imported constructor bound to a simple name, optional name-to-name alias propagation, rebinding invalidation, and a constructor-supported outbound method or context-manager use; bare canonical-looking names never fall back to module identity. Nested scopes never inherit client handles and inherit only constructor aliases proven stable by a binding-only enclosing-scope prepass. Comprehensions, walrus-bearing statements, annotations, executable expressions inside complex binding targets, unsupported operations, and ambiguous flows produce no finding from this signal; skipped constructs invalidate all names they may bind, while representative false negatives are pinned by `test_python_declared_false_negatives_stay_unreported`. Compound bodies are walked from isolated copies so wrapping code in `if True:` is not a bypass, while copied scope entries, binding-only prepasses, and AST visits consume a deterministic work budget and the walk stops after its first sink. Budget or recursion exhaustion skips only this best-effort signal and retains deterministic findings already collected for the file. Do not add Semgrep/OpenGrep or YAML rule-engine dependencies to the core path; Phase 1 rule specs live in Python constants next to their analyzers in `skillscan/orchestrator.py`.
- **Skill Review Core**: `packages/harness/deerflow/skills/review/` provides read-only package snapshots, deterministic facts, resource/eval analysis, report rendering, and the CLI (`python -m deerflow.skills.review.cli`). It reuses the shared frontmatter helper and SkillScan; it must not import `app.*`, execute target scripts, install dependencies, or call networks. JSON contracts live in `contracts/skill_review/`. The `review_skill_package` built-in tool labels results with `review_subject_entry` and never `skill_context_entry`, so reviewing a target does not activate it, bind its `required-secrets`, or apply its `allowed-tools`. Its model-visible `ToolMessage.content` is a compact JSON payload with untrusted control tags neutralized; the full raw review payload, including Markdown renders, stays in `ToolMessage.artifact`. CI should run the CLI with `--fail-on error --fail-on-incomplete` so blocker/error findings and truncated/not-assessed packages fail the gate. The public `skills/public/skill-reviewer` skill owns semantic readiness review and suggestions only; mutation and runtime experiments remain owned by `skill-creator`.

#### Request-Scoped Secrets (`required-secrets`)

Lets a caller pass per-request, short-lived end-user credentials (e.g. an ERP token) to a skill's sandbox scripts without the value entering the prompt, tool arguments, the executed command string, or traces (issue #3861).

- **Declare**: a skill lists the secrets it needs in `SKILL.md` frontmatter — `required-secrets:` as a string list or `{name, optional}` mappings. `name` is both the lookup key and the env var name exposed to scripts. Parsed by `skills/parser.py::parse_required_secrets` into `Skill.required_secrets` (`SecretRequirement`); malformed entries are dropped with a warning.
- **Carry**: the caller sends values out-of-band in the run request's `context.secrets` mapping (never a message). `runtime/secret_context.py` owns the contract (`SECRETS_CONTEXT_KEY`, `extract_request_secrets`). The existing `context` passthrough carries it to `runtime.context` without mirroring into `configurable`. `build_run_config` still sets `configurable.thread_id` on the context path — the checkpointer requires it.
- **Bind (point A+)**: `SkillActivationMiddleware._resolve_secret_bindings` recomputes the injection set (`runtime.context[__active_skill_secrets]`) on every model call from two unioned sources, then REPLACES the key. (1) *Slash*: the run's most recent `/skill` activation, persisted as a source on the run context (only the activated skill's **canonical container path**, never its declared secrets) so the whole tool loop after the activation call keeps the binding; a new activation replaces it. Slash reads the genuine user text via `get_original_user_content_text`; `InputSanitizationMiddleware` preserves it (`ORIGINAL_USER_CONTENT_KEY`), so activation fires even after sanitization. (2) *In-context* (autonomous invocation): skills the model actually loaded in this thread — `ThreadState.skill_context` entries. **Both sources resolve the live registry skill by normalized container path on every call** (`_resolve_registry_skill`) and bind only that skill's own declared secrets — enabled + allowlist checked for both; the `secrets-autonomous: false` opt-out (malformed values fail closed to `false`) additionally gates the in-context path but exempts explicit slash. Resolving by registry — not by trusting the source's stored data — is what makes a caller-forged `__slash_skill_secret_source` harmless (`runtime.context` is caller-mergeable; the gateway also strips caller `__`-keys in `build_run_config`), #3938. Authorization is three-gated regardless of activation style: skill **enabled** by the operator × values **supplied per-request** by the caller (`context.secrets`) × names **declared** in frontmatter (∩ semantics). Because the set is recomputed per call, a skill evicted from `skill_context` (capacity) or a caller that stops supplying a value loses injection on the next call. The injected value always comes from the caller's request, never the host environment (scrubbed first — see below), so a declared name that also exists in the host env is safe: the caller's value wins and the host value is dropped (the #3861 per-user-key-overrides-shared-key case). Missing required secrets are logged once per binding change, not injected; binding changes are recorded as a `middleware:skill_secrets` journal event (skill and secret names only, never values).
- **Inject**: `bash_tool` reads the injection set and passes it as `execute_command(env=...)`. Scope is the activation turn/run only — a run without `/skill` activation injects nothing.
- **AIO image requirement**: on `AioSandbox` the env path uses the `bash.exec` API (`POST /v1/bash/exec`), which upstream all-in-one-sandbox only ships since `1.9.3` — older images (including a `latest` tag frozen on the `1.0.0.x` line) 404 the whole `/v1/bash/*` namespace. `AioSandbox` detects the 404, remembers the capability gap on the instance, and fails fast with an actionable upgrade error instead of letting the model retry raw 404s; there is deliberately **no** fallback through the legacy shell path because none keeps the secret values out of the command string (#3921). Regression tests: `tests/test_aio_sandbox.py::TestBashExecUnsupportedFailFast`.
- **Inherited-env scrub**: `execute_command` no longer leaks the Gateway's `os.environ` to skill subprocesses — `env_policy.build_sandbox_env` drops secret-looking names (`*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASS*`/`*CREDENTIAL*`/`*DSN*` + a connection-string denylist like `DATABASE_URL`/`REDIS_URL`/`GH_PAT`, plus no-flag credential sources like `MYSQL_PWD`/`REDISCLI_AUTH`/`PGPASSFILE`/`PGSERVICEFILE`) so platform credentials never reach a skill; a skill that needs one must declare it.
- **Leak surfaces sealed** (verified by a real-gateway e2e run — secret reaches the sandbox but none of these): prompt (value never in a message), trace (`tracing/metadata.py` never copies `context`), checkpoint (secrets live on `runtime.context`, not graph state), audit (journal records names only), stdout (`tools.py::mask_secret_values` redacts injected values from bash output), and **run-record persistence + run API** (`services.py::start_run` stores `redact_config_secrets(body.config)` so `runs.kwargs_json` and `RunResponse.kwargs` never carry the secret).
- **Scope / non-goals**: no persistence/vaulting — values are request-scoped and never stored server-side, so long-lived use means the caller re-supplies `context.secrets` on each request while the skill stays in `skill_context`; subagents do not inherit the injection set; the MCP per-user-credential gap (#3322) is a sibling, not covered here. Tests: `tests/test_skill_request_scoped_secrets.py`.

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

Bridges external messaging platforms (Feishu, Slack, Telegram, Discord, DingTalk, GitHub) to the DeerFlow agent via Gateway's LangGraph-compatible API.

**Architecture**: Channels communicate with Gateway through the `langgraph-sdk` HTTP client (same as the frontend), ensuring threads are created and managed server-side. The internal SDK client injects process-local internal auth plus a matching CSRF cookie/header pair so Gateway accepts state-changing thread/run requests from channel workers without relying on browser session cookies.

**Components**:
- `message_bus.py` - Async pub/sub hub (`InboundMessage` → queue → dispatcher; `OutboundMessage` → callbacks → channels)
- `store.py` - JSON-file persistence mapping `channel_name:chat_id[:topic_id]` → `thread_id` (keys are `channel:chat` for root conversations and `channel:chat:topic` for threaded conversations)
- `manager.py` - Core dispatcher: creates threads via `client.threads.create()`, routes commands including `/goal` (setting a goal persists it through Gateway and then routes the objective as a chat turn), keeps Slack/Discord on `client.runs.wait()`, uses `client.runs.stream(["messages-tuple", "values"])` for Feishu/Telegram incremental outbound updates, serializes same-thread Feishu turns in-manager when the channel's `ChannelRunPolicy.serialize_thread_runs=True` so rapid follow-ups queue instead of tripping the runtime busy reply, and switches to `client.runs.create()` (fire-and-forget, returns once the run is `pending`) for channels whose `ChannelRunPolicy.fire_and_forget=True` so long autonomous runs do not hit the SDK default 300s `httpx.ReadTimeout`
  A swallowed streaming failure publishes its final outbound before releasing the inbound dedupe key, so a provider redelivery can retry without overtaking the terminal reply.
- `base.py` - Abstract `Channel` base class (start/stop/send lifecycle)
- `service.py` - Manages lifecycle of all configured channels from `config.yaml`
- `slack.py` / `feishu.py` / `telegram.py` / `discord.py` / `dingtalk.py` - Platform-specific implementations (`feishu.py` tracks the running card `message_id` in memory and patches the same card in place; `telegram.py` registers the "Working on it..." placeholder as the stream target and edits it in place via `editMessageText`; `dingtalk.py` optionally uses AI Card streaming for in-place updates when `card_template_id` is configured)
- `github.py` - Webhook-driven GitHub channel. Inbound messages come from `POST /api/webhooks/github`; outbound is log-only because GitHub agents post explicitly with `gh` from their sandbox when they choose to comment or create a PR
- `app/gateway/routers/channel_connections.py` - Browser-facing user connection and disconnect APIs
- `deerflow.persistence.channel_connections` - SQL-backed user-owned connection, optional credential, connect state, and conversation store

**Message Flow**:
1. External platform -> Channel impl -> `MessageBus.publish_inbound()`
   - For GitHub, the webhook router verifies the delivery then calls `fanout_event(bus, ...)`; matching agent bindings publish one `InboundMessage` each instead of a long-polling channel worker.
2. `ChannelManager._dispatch_loop()` consumes from queue
3. For user-owned channel connections, incoming messages carry `connection_id`, `owner_user_id`, and `workspace_id`; `owner_user_id` becomes the DeerFlow run `user_id`, while the raw platform user id remains `channel_user_id`. The Gateway accepts `channel_user_id` only from an internally authenticated channel caller's top-level `body.context`, clears it from both free-form `body.config` sections, and writes it into runtime context only (never `configurable`, which is checkpointed). `bash_tool` exposes it to sandbox commands as the fixed env var `DEERFLOW_CHANNEL_USER_ID` — via a shell-quoted command-string prefix, NOT the `execute_command(env=...)` channel, which is reserved for request-scoped secrets and would switch `AioSandbox` onto the `bash.exec` path (image >= 1.9.3, fresh session per call). Per-call injection keeps group-chat identity correct (one thread/sandbox, many senders) **without depending on the AIO shell's session semantics**: every IM-channel command carries an explicit `export VAR=<id>; ` (valid id) or `unset VAR; ` (empty / non-str / over the 256-char cap). The AIO no-env path reuses a persistent shell session (the reason for the class lock, #1433), so a bare command could otherwise resolve a stale id an earlier sender exported; the `unset` closes the window the length/type guard would open (a dropped id would inherit the previous sender's value). Non-IM runs (no `channel_user_id` in context) are left untouched. Not injected on the Windows local sandbox (its PowerShell/cmd.exe fallback has no `export`/`unset`). Propagates across `task` delegation: `task_tool` captures the dispatching turn's id and the subagent executor forwards it into the subagent's runtime context, same as the guardrail attribution fields. The runtime-context value is authorization-grade at the Gateway/guardrail boundary, but the exported shell variable remains informational because any bash command can overwrite its own environment; skills must not treat the shell variable itself as authenticated identity. Tests: `tests/test_gateway_services.py`, `tests/test_channel_user_id_env.py`
4. For chat: look up/create thread through Gateway's LangGraph-compatible API
5. Feishu/Telegram chat: `runs.stream()` → accumulate AI text → publish multiple outbound updates (`is_final=False`) → publish final outbound (`is_final=True`)
6. Slack/Discord chat: `runs.wait()` → extract final response → publish outbound
6b. GitHub chat (`ChannelRunPolicy.fire_and_forget=True`): `runs.create()` returns once the run is `pending`; the manager does not wait for the final state and does not publish an outbound. The agent posts its own reply mid-run via `gh` from the sandbox. `ConflictError` on a busy thread still trips the standard `THREAD_BUSY_MESSAGE` path (log-only on GitHub).
7. Feishu channel sends one running reply card up front, then patches the same card for each outbound update (card JSON sets `config.update_multi=true` for Feishu's patch API requirement). Messages already sent inside an existing Feishu topic carry a compact source-message preview in that card, and queued same-thread follow-ups patch their own source message's card from queued → running → final without falling back to the generic busy reply.
8. Telegram streaming: the "Working on it..." placeholder message is registered as the stream target; non-final updates `editMessageText` it in place (channel-side throttle: 1s in private chats, 3s in groups due to Telegram's 20 msg/min group cap; 4096-char truncation; rate-limited updates dropped); the final update performs the last edit and splits >4096 texts into follow-up messages
9. DingTalk AI Card mode (when `card_template_id` configured): `runs.stream()` → create card with initial text → stream updates via `PUT /v1.0/card/streaming` → finalize on `is_final=True`. Falls back to `sampleMarkdown` if card creation or streaming fails
10. For commands (`/new`, `/status`, `/models`, `/memory`, `/goal`, `/help`): handle locally or query Gateway API
11. Outbound → channel callbacks → platform reply
    - GitHub is the exception: the channel logs the final assistant message and does **not** auto-post it to GitHub. Agents use the sandbox `gh` CLI (`gh issue comment`, `gh pr comment`, `gh pr create`, etc.) for intentional writeback, so silence is cheap when several agents fan out on the same event.

**Owner-scoped file storage**: inbound files, uploads, and output artifacts are staged under the DeerFlow owner's bucket so they land where the agent run reads/writes (`users/{user_id}/threads/{thread_id}/user-data/{uploads,outputs}`). `ChannelManager._handle_chat` resolves the storage owner once via `_channel_storage_user_id(msg)` (sanitized owner id, falling back to `safe(msg.user_id)` for unbound auth-enabled channels — mirroring `_resolve_run_params`'s run identity; `None` only when no identity is available) and threads it as the `user_id=` kwarg through the file pipeline:
- `Channel.receive_file(msg, thread_id, user_id=...)` — owner-bound channels persist downloaded files under the owner's bucket instead of the default bucket
- `_ingest_inbound_files(...)` and the underlying `ensure_uploads_dir` / `get_uploads_dir` — owner-scoped via the same kwarg
- `_resolve_attachments` / `_prepare_artifact_delivery` — resolve output artifacts from the bound owner's bucket
The cached value is reused for both the blocking (`runs.wait`) and streaming (`_handle_streaming_chat`) paths, so uploads and artifact delivery always target the same bucket even if a channel returns a rewritten `InboundMessage` from `receive_file`. The bucket id matches the memory bucket resolved by `_resolve_memory_user_id` (both normalize through `make_safe_user_id`).

**Configuration** (`config.yaml` -> `channels`):
- `langgraph_url` - LangGraph-compatible Gateway API base URL (default: `http://localhost:8001/api`)
- `gateway_url` - Gateway API URL for auxiliary commands (default: `http://localhost:8001`)
- In Docker Compose, IM channels run inside the `gateway` container, so `localhost` points back to that container. Use `http://gateway:8001/api` for `langgraph_url` and `http://gateway:8001` for `gateway_url`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` / `DEER_FLOW_CHANNELS_GATEWAY_URL`.
- Per-channel configs: `feishu` (app_id, app_secret), `slack` (bot_token, app_token), `telegram` (bot_token), `dingtalk` (client_id, client_secret, optional `card_template_id` for AI Card streaming), `github` (operator kill-switch `enabled`, plus `default_mention_login` for mention-required GitHub triggers)

**User-owned channel connections** (`config.yaml` -> `channel_connections`):
- Disabled by default. It is a user-binding layer on top of the existing `channels.*` runtime config, not a replacement for provider bot credentials.
- No public IP, OAuth callback URL, or provider webhook route is required by the current implementation.
- Telegram uses a deep-link `/start <code>` flow over the existing long-polling worker. Slack, Discord, Feishu/Lark, DingTalk, WeChat, and WeCom use `/connect <code>` over their existing outbound channel workers.
- WeChat timing settings (`polling_timeout`, `polling_retry_delay`, `qrcode_poll_interval`, `qrcode_poll_timeout`) accept only positive finite seconds; invalid values fall back to their defaults so polling cannot enter a hot loop or sleep forever.
- Frontend APIs: `GET /api/channels/providers`, `GET /api/channels/connections`, `POST /api/channels/{provider}/connect`, and `DELETE /api/channels/connections/{connection_id}`.
- Browser APIs remain protected by normal Gateway auth/CSRF. Provider messages arrive through the already-configured channel workers.
- Provider-level `connection_status` reflects the user's newest connection row. With no binding it is `not_connected`, except in auth-disabled local mode where a configured running channel reports `connected` because all channel messages already route to the default user.
- Slack replies use the configured operator bot token from `channels.slack` unless per-connection credentials are present; unreadable or corrupt stored credentials are treated as unavailable.
- Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeChat, and WeCom workers resolve incoming platform identities to connection records before reaching `ChannelManager`.
- **Connect-code ordering vs `allowed_users`**: inbound workers consume a valid `/connect <code>` (or Telegram `/start <code>`) **before** applying the `allowed_users` filter, so a newly allowlisted-but-unbound user can bootstrap their first bind via the browser flow. Consequence: `allowed_users` is **not** a bind-time defense — any sender who possesses a valid code can consume it (not only allowlisted users). The bind security model rests on the code's confidentiality: `secrets.token_urlsafe(16)`, 600 s TTL, one-time `consume_oauth_state`, and codes surfaced only in the initiating browser (never echoed to chat). `allowed_users` still gates ordinary (non-bind) messages.
- **Single-active-owner transfer semantics**: an external identity is keyed by `(provider, external_account_id, workspace_id)`. The latest successful bind wins — `upsert_connection` revokes other owners' active rows for the same identity (ownership transfer). This invariant is enforced at the DB layer by the partial unique index `uq_channel_connection_active_identity` (`WHERE status != 'revoked'`), so concurrent connects from different owners cannot both end `connected`; the losing writer retries against the now-visible state. `find_connection_by_external_identity` therefore resolves deterministically.
- See `backend/docs/IM_CHANNEL_CONNECTIONS.md` for provider setup, operational notes, and the architecture diagrams (connect-code flow, single-active-owner transfer, sync vs streaming dispatch, owner-scoped file storage pipeline).

**GitHub event-driven agents** (webhook-driven IM channel):
- Custom agents declare a `github:` block in their `config.yaml` to bind to repos and event triggers; the webhook route is fail-closed by default (mounted only when `GITHUB_WEBHOOK_SECRET` is set) and exempt from auth/CSRF because authenticity is enforced by HMAC.
- Outbound is **log-only** by design: each agent posts its own reply mid-run via the `gh` CLI from its sandbox, so the manager uses `fire_and_forget=True` and `runs.create()` returns once pending.
- See [backend/docs/GITHUB_AGENTS.md](docs/GITHUB_AGENTS.md) for the architecture diagrams: webhook → fan-out → `InboundMessage` dispatch, `preferred_thread_id = UUID5(repo, number, agent_name)` thread determinism, mention-handle precedence chain, GH token lifecycle via `GH_TOKEN`/`GITHUB_TOKEN` per-call `extra_env`, and the narrow `ConflictError` (HTTP 409) thread-create race recovery.


### Memory System (`packages/harness/deerflow/agents/memory/`)

**Components**:
- `updater.py` - LLM-based memory updates with fact extraction, whitespace-normalized fact deduplication, optimistic revision checks, and repository change sets
- `queue.py` - Debounced update queue (per-thread deduplication, configurable wait time); captures `user_id` at enqueue time so it survives the `threading.Timer` boundary
- `prompt.py` - Prompt templates for memory updates
- `storage.py` - File repository with one user-global summary JSON, agent-owned single-fact Markdown, target-only journaled changes, strict fact validation, shared-user plus per-fact optimistic revisions, lock-protected migration, deep-copy caching, and an optional retrieval adapter
- `tools.py` - Tool-driven memory mode (`memory_search`, `memory_add`, `memory_update`, `memory_delete`) using the same storage/update primitives

**Per-User Isolation**:
- Memory is stored per-user at `{base_dir}/users/{user_id}/memory.json`
- Per-agent facts at `{base_dir}/users/{user_id}/agents/{agent_name}/facts/{sha256-prefix}/{fact-id}.md`, where the prefix is the first two hexadecimal characters of `SHA-256(fact_id)`; there is no per-agent `memory.json`
- Custom agent definitions (`SOUL.md` + `config.yaml`) are also per-user at `{base_dir}/users/{user_id}/agents/{agent_name}/`. The legacy shared layout `{base_dir}/agents/{agent_name}/` remains read-only fallback for unmigrated installations
- Middleware mode captures `user_id` via `get_effective_user_id()` at enqueue time; tool mode resolves `user_id` and `agent_name` from `ToolRuntime.context` via `resolve_runtime_user_id(runtime)` so tool calls stay scoped to the authenticated user and active custom agent
- The `/api/memory*` endpoints resolve the owner through `_resolve_memory_user_id(request)`: trusted internal callers (IM channel workers carrying the `X-DeerFlow-Owner-User-Id` header, e.g. a bound `/memory` command) act for the connection owner; browser/API callers fall back to `get_effective_user_id()`. The header is only honored after `AuthMiddleware` validated the internal token, mirroring `get_trusted_internal_owner_user_id` used by the threads router
- In no-auth mode, `user_id` defaults to `"default"` (constant `DEFAULT_USER_ID`)
- Absolute `storage_path` in config opts out of per-user isolation
- **Migration**: Run `PYTHONPATH=. python scripts/migrate_user_isolation.py` to move legacy `memory.json`, `threads/`, and `agents/` into per-user layout. Supports `--dry-run` (preview changes) and `--user-id USER_ID` (assign unowned legacy data to a user, defaults to `default`).

**Data Structure**:
- **User Context**: `workContext`, `personalContext`, `topOfMind` (1-3 sentence summaries)
- **History**: `recentMonths`, `earlierContext`, `longTermBackground`
- **Global JSON**: `{base_dir}/users/{user_id}/memory.json` stores only `version`, shared revision/time, `user`, and `history`; it never stores facts or a fact index
- **Facts**: Schema-v2 Markdown documents under `agents/{agent_name}/facts/{sha256-prefix}/{fact-id}.md`; YAML front matter contains structure and the body contains the atomic fact
- **Default agent compatibility**: DeerMem resolves an omitted `agent_name` to the reserved `__default__` fact bucket at the manager boundary. The sentinel is accepted only by DeerMem storage and is outside the custom-agent name grammar, so a real custom `lead-agent` remains isolated. Public agent identifiers are case-insensitive and canonicalized to lowercase before storage
- **Compatibility view**: direct global storage reads return `facts: []`, while DeerMem Manager/API reads select the explicit agent or reserved default and return its facts, so existing Settings and embedded-client schemas remain stable. Markdown keeps structured `source` metadata internally; the manager projects it to the historical string field before returning a public document
- **Incremental result contract**: `FileMemoryStorage.apply_changes()` returns `complete: false` plus `upsertedFacts`/`deletedFactIds`; it never presents a partial cache as a complete memory document. Public compatibility callers explicitly reload a fresh complete view only where their response contract requires it, including after successful disjoint-create rebases
- **Repository**: `get/list/upsert/delete_fact`, `apply_changes`, summary operations, migration, index lifecycle/status, and scoped search. `apply_changes` and direct fact CRUD touch only target Markdown files; direct fact CRUD accepts separate expected user-memory and fact revisions. Supplied summary child keys merge over their persisted section, while import normalizes complete replacement sections first. Whole-document `load/save` remains for compatibility but validates the complete `facts` list and diffs it before persistence. An unscoped manager clear first migrates facts from unread legacy agent JSON without adopting potentially conflicting summaries, then removes the global summaries and every agent's canonical facts while preserving agent configuration; an explicit agent clear removes only that bucket's facts and preserves the shared summaries

**Workflow**:
- `memory.mode: middleware` (default) keeps the passive path: `MemoryMiddleware` filters messages (user inputs + final AI responses), captures `user_id` via `get_effective_user_id()`, queues conversation with the captured `user_id`, and the debounced background thread invokes the LLM to extract context updates and facts using the stored `user_id`.
- `memory.mode: tool` skips `MemoryMiddleware` and registers `memory_search`, `memory_add`, `memory_update`, and `memory_delete` on the agent. The model decides when to search, add, update, or delete facts; this is opt-in/experimental and should not be described as better than middleware mode without eval evidence.
- Both modes share `FileMemoryStorage`, per-user/per-agent isolation, prompt injection, manual CRUD primitives, and the updater backend.
- Middleware mode queue debounces (30s default), batches updates, and commits global summaries plus the selected/default agent's fact delta through a user-level lock, optimistic user-memory revisions, per-fact revisions, and a recoverable target-file journal. Only explicitly marked point operations may rebase a stale shared revision, and only while every addressed fact still satisfies its original absent/revision precondition. Snapshot-derived clear/trim/consolidation operations instead reload the complete document and recompute their intent on a manifest conflict, with a bounded retry. Typed manifest/fact conflict subclasses keep that decision independent of exception text, and same-ID creates and stale same-fact writes fail. Scope-lock objects are weakly cached so inactive users do not grow a process-lifetime map. Cache validation does not scale with the fact-file count: its token combines the shared JSON's `(mtime_ns, size, revision)`, so the persisted revision invalidates stale caches even when a coarse-mtime filesystem reports identical metadata for same-size writes; direct out-of-band Markdown edits require `reload()`. Atomic replacement also syncs the parent directory on POSIX so the rename is durable. DeerMem translates private storage conflict/corruption exceptions to the backend-neutral MemoryManager contract; the Gateway maps them to HTTP 409 and a stable HTTP 500 response respectively. A normal default-manager read automatically migrates legacy facts from the global JSON into `__default__`; it also adopts the earlier implicit `lead-agent` fact bucket only when that directory has no custom-agent `config.yaml`, and rejects unexpected files instead of deleting them. The v1-to-v2 migration is one-way for the running application: operators must stop DeerFlow and snapshot the configured storage root before upgrade. Before any destructive v2 write, every migrated JSON source is durably retained as `{manifest_filename}.v1.bak`; a missing-write or mismatched existing backup aborts without modifying v1 data. Legacy per-agent JSON is deleted only after its non-empty summaries are safely adopted or confirmed identical; summary conflicts keep the source file and fail loudly.
- **Proactive Markdown migration CLI**: from `backend/`, run `PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run` to audit and omit `--dry-run` to migrate before serving traffic. Use repeated `--user-id` values when selecting exact original identities, especially standalone raw IDs containing `@` or other characters that are normalized in directory names; `--storage-path` selects a non-default DeerMem root. The CLI reuses `FileMemoryStorage.migrate`, is idempotent, continues across per-user failures, and exits non-zero if any user fails. It is optional because the first normal read still performs the same migration automatically.
- A configured `retrieval_adapter` owns indexing and semantic retrieval. File storage sends upsert/remove notifications for normal writes and both explicit and lazy migrations after releasing durable storage locks, then delegates search; without an adapter it declares and uses `substring_fallback`.
- Staleness pass (same LLM invocation as the regular updater, no extra API call): when `staleness_review_enabled` is `true` and at least `staleness_min_candidates` aged facts exist, `_select_stale_candidates` selects facts older than their individual review window (`expected_valid_days`, or the global `staleness_age_days` fallback) that are not in `staleness_protected_categories` (default: `correction`), surfaces them in the prompt with a `valid:Nd` annotation, and the LLM judges each as KEEP, REMOVE, or EXTEND. REMOVE entries go in `staleFactsToRemove`; EXTEND entries go in `staleFactsToExtend` with an `extend_by_days` value, which sets the fact's `expected_valid_days` to `min(days_since_created + extend_by_days, staleness_max_extension_days)`. The LLM assigns `expected_valid_days` when creating a fact; it is clamped at write time to `staleness_age_days × staleness_max_lifetime_multiplier` (creation cap). `_apply_updates` enforces the guardrail unconditionally at apply time: it intersects both the removal and extension sets with `_select_stale_candidates` output before applying the per-cycle cap (`staleness_max_removals_per_cycle`), so protected and non-aged facts can never be targeted regardless of model behavior or the feature flag setting. Facts the LLM proposed for removal are excluded from extension even if the per-cycle cap prevented their actual deletion that cycle. Extensions use an absolute ceiling (`staleness_max_extension_days`) rather than the creation multiplier so a deliberate review decision can advance the window beyond the initial cap while preventing `timedelta` overflow from a malformed `extend_by_days`.
- Consolidation pass (same LLM invocation as the regular updater, no extra API call): when `consolidation_enabled` is `true` and at least one category holds `consolidation_min_facts` or more facts, `_select_consolidation_candidates` identifies fragmented categories and surfaces at most `consolidation_max_groups_per_cycle` of them (largest first) in the prompt. The LLM decides which groups to merge and proposes a synthesised fact per group. `_apply_updates` enforces guardrails: source IDs must exist and must not overlap across groups, group size is capped at `consolidation_max_sources`, the merged fact's confidence cannot exceed the source maximum, and facts below `fact_confidence_threshold` are not written. The merged fact carries the newest source's `createdAt` (so the staleness clock reflects the underlying information, not synthesis time) and inherits `expected_valid_days` set so the merged fact is re-reviewed at the earliest source review deadline (`min(createdAt + effective_lifetime)` across sources, where a source's effective lifetime is its `expected_valid_days` or the global `staleness_age_days` fallback for legacy facts without one - so a legacy source's default window is not swallowed by a long-lived sibling), relative to the merged `createdAt`, clamped to a minimal positive window if a source is already past its deadline, then capped at the creation-time `staleness_max_lifetime_multiplier`; this keeps a volatile or legacy sub-detail from inheriting a stable source's long window and escaping staleness review for years, while a merge of uniformly stable sources does not re-enter review prematurely.
- Next interaction injects selected facts + context into `<memory>` tags in the system prompt when `injection_enabled` is true.

**Run-level memory identity**:
- Every Gateway run with an effective hidden memory block hashes the exact `HumanMessage.content`, including the `<memory>` wrapper, and records one `context:memory` event through its run-scoped `RunJournal`. Later runs and checkpoint-based branches reuse the frozen message without reloading memory; goal continuations are deduplicated to one event per run.
- A first-run block is trusted only when it comes from `DynamicContextMiddleware`'s current update. A reused block must have existed in the checkpoint before the run, and the Gateway strips dynamic-context markers from untrusted input so a caller cannot forge the identity event by reusing a known message ID.
- The production consumer is the existing debug/audit endpoint `GET /api/threads/{thread_id}/runs/{run_id}/events?event_types=context:memory`. Event content has exactly one field, `content_sha256`, which operators use to compare the effective memory identity across runs. The full memory text stays in checkpoint state and is not duplicated into `run_events`.

**Token counting** (`packages/harness/deerflow/agents/memory/prompt.py`):
- `_count_tokens` budgets the injection. In default `tiktoken` mode, the encoding is loaded lazily and cached.
- Failed tiktoken loads are cached with a timestamp. During the fixed cooldown (`_TIKTOKEN_RETRY_COOLDOWN_S`, 600s), callers fall back to char estimation immediately instead of re-triggering the blocking BPE download; after the cooldown, transient outages can self-heal without a restart.
- In-flight loads are cached as a LOADING sentinel so concurrent callers fall back instead of spawning more blocking threads.
- Set `memory.token_counting: char` to skip tiktoken entirely and use the network-free CJK-aware char estimate.

Focused regression coverage for the updater lives in `backend/tests/test_memory_updater.py`.

**Configuration** (`config.yaml` → `memory`):
- `enabled` / `injection_enabled` - Master switches
- `mode` - Operation mode: `middleware` (default passive background extraction) or `tool` (experimental model-driven memory tools). Modes are mutually exclusive.
- `storage_path` - DeerMem storage root; one global summary JSON lives under each user and Markdown facts remain under agent buckets
- `storage_class` - `file` or a dotted `MemoryStorage` class; invalid persistent backends fail fast
- `strict_user_scope` - Require `user_id` for all storage access (default `false` for no-auth/legacy compatibility)
- `manifest_filename` - User-global summary JSON filename (kept for configuration compatibility)
- `file_lock_timeout_seconds` - Scope-lock wait; Markdown facts and the recovery journal are required storage invariants rather than configurable modes
- `retrieval_adapter` - Optional dotted factory receiving `DeerMemConfig` and returning a retrieval-port implementation
- `debounce_seconds` - Wait time before processing (default: 30)
- `shutdown_flush_timeout_seconds` - Host-shared hard budget (seconds) to drain the memory backend's pending-update buffer on Gateway graceful shutdown (default: 30; 1–300). Each pending item does one LLM call, so large IM batches may need more. The Gateway lifespan calls `MemoryManager.shutdown_flush(timeout)` after channels/scheduler stop; the backend short-circuits on an idle buffer, so the host calls it unconditionally (no pending/processing gate). Must fit inside the pod's K8s `terminationGracePeriodSeconds` (gateway Helm chart sets this; default 45s) or K8s SIGKILLs the drain mid-flight.
- `model_name` - LLM for updates (null = default model)
- `max_facts` / `fact_confidence_threshold` - Fact storage limits (100 / 0.7)
- `max_injection_tokens` - Token limit for prompt injection (2000)
- `token_counting` - Token counting strategy for the injection budget: `tiktoken` (default, accurate but may download BPE data from a public endpoint on first use — can block for a long time in network-restricted environments, see issues #3402/#3429) or `char` (network-free CJK-aware char estimate, never touches tiktoken)
- `staleness_review_enabled` - Enable proactive staleness pruning of aged facts (default: `true`; only triggers when aged candidates exist)
- `staleness_age_days` - Age in days before a fact becomes a staleness candidate (default: 90; range: 30–365)
- `staleness_min_candidates` - Minimum aged candidates required to trigger a review cycle (default: 3; range: 1–50)
- `staleness_max_removals_per_cycle` - Maximum facts removed in a single cycle; lowest-confidence entries are kept when the LLM requests more (default: 10; range: 1–50)
- `staleness_protected_categories` - Fact categories that are never pruned by staleness review (default: `["correction"]`)
- `staleness_max_lifetime_multiplier` - Creation-time cap multiplier for a fact's LLM-assigned `expected_valid_days`: stored value is clamped to `staleness_age_days × multiplier` so the model cannot defer first review indefinitely (default: 20.0; range: 1.0–100.0). Default 20.0 (90 × 20 = 1800 d ≈ 5 years) is generous enough to support the very-stable prompt tier without needing multiple review cycles to escape the cap.
- `staleness_max_extension_days` - Absolute upper bound (in days) on `expected_valid_days` after a lifetime extension (`staleFactsToExtend`). Applied at write time as `min(days_since + extend_by, staleness_max_extension_days)`. Uses an absolute ceiling rather than the multiplier because extensions are deliberate review decisions; prevents `timedelta` overflow and LLM misfire from permanently deferring a fact (default: 3650 = 10 years; range: 90–36500).
- `consolidation_enabled` - Enable memory consolidation (default: `true`; no extra API call — runs in the same LLM invocation as the normal memory update)
- `consolidation_min_facts` - Minimum facts in a category to trigger consolidation review (default: 8; range: 3–30)
- `consolidation_max_groups_per_cycle` - Maximum categories the LLM can merge in one cycle (default: 3; range: 1–10; also controls the LLM's prompt instruction)
- `consolidation_max_sources` - Maximum source facts per merge group; prevents over-merging (default: 8; range: 2–20)

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

### Checkpoint Channel Modes (`full` / `delta`)

Checkpointer storage runs in one of two channel modes, selected by `checkpoint_channel_mode` in `config.yaml` (default `full`). `delta` mode adopts LangGraph 1.2's `DeltaChannel` for `messages`: checkpoints store a sentinel + per-step writes instead of the full message list, so storage/serde grows O(N) instead of O(N²) in turns. All checkpointer backends (memory/sqlite/postgres) serve both modes unchanged — the semantics live in the compiled graph's channel table, not in the saver.

**Mode is process-frozen and restart-required.** `make_lead_agent` freezes the resolved mode (`runtime/checkpoint_mode.py::freeze_checkpoint_channel_mode`) before compiling the graph with the mode-matched schema (`agents/thread_state.py::get_thread_state_schema`, plus `adapt_state_schema_for_mode` / `normalize_middleware_state_schemas` for middleware state). A second, different mode in the same process raises `CheckpointModeReconfigurationError`. To switch: edit config, restart.

**Compatibility is asymmetric and fail-closed.** Every checkpoint written in delta mode carries metadata marker `deerflow_checkpoint_channel_mode: "delta"` (injected via `inject_checkpoint_mode`; absence of marker = full, so pre-feature checkpoints need no migration). Before any state read/write, `ensure_checkpoint_mode_compatible` rejects a full-mode process opening a delta thread with `CheckpointModeMismatchError` (surfaced as HTTP 409 with the cause and thread id by the threads router; `CheckpointModeReconfigurationError` maps to 503) — a full-mode raw read of a delta blob would silently return empty/partial `messages`. The reverse direction is allowed: delta-mode processes read full checkpoints transparently (old full checkpoints seed the delta channel), so full → delta is the smooth migration path; delta → full requires materializing/converting the data first. Detection also honors upstream's `counters_since_delta_snapshot.messages` metadata, and an explicit config marker takes precedence over any ambient context value.

**Never bypass `CheckpointStateAccessor` (`runtime/checkpoint_state.py`) for thread-state access.** It is the single choke point binding graph + checkpointer + mode: it injects the mode marker into configs, runs the compatibility check before every `get`/`update`/`history`, and returns materialized state (delta checkpoints lack `channel_values.messages` — raw `get_tuple` reads see a sentinel). Gateway `services.py` builds and passes the accessor; thread-owned reads (state/history/regeneration) must use `build_thread_checkpoint_state_accessor` so the recorded assistant's middleware schema materializes every channel. `history(limit)` semantics: `0` means zero items (explicit empty), `None` means unlimited — do not pass `limit=0` through to `graph.get_state_history`. Assistant metadata lookup is fail-closed for mutation accessors so a store outage cannot silently select the default schema and discard extension channels. In `full` mode the read path degrades to a raw checkpointer read (`_RawCheckpointReadAccessor`) when the agent factory cannot build the graph (bad model config, MCP outage) — full checkpoints carry complete `channel_values`, so reads don't need the graph; degraded snapshots take `created_at` from the standard checkpoint `ts` field, falling back to metadata only for compatibility. The delta gate still applies on the degraded path; `next`/`tasks` degrade to empty and thread status falls back to the stored status because task presence is not derivable, while delta mode has no fallback (materialization needs the channel table).

**Replay checkpoint lookup prefers lineage and degrades only for an explicitly missing legacy parent link.** Branch and regenerate paths first walk `parent_config`, which prevents a global chronological scan from selecting a sibling created by regeneration. `CheckpointParentMissingError` alone enables the bounded newest-first history fallback in `app/gateway/checkpoint_lineage.py`; cycles, dangling/non-addressable parents, target mismatches, and depth exhaustion raise `CheckpointLineageIntegrityError` and fail closed instead of selecting a sibling. The compatibility scans request 400 raw checkpoints so up to 200 duration-only entries do not consume the effective branch-history budget; the fallback scans oldest-to-newest internally, skips duration-only checkpoints, and accepts only checkpoints with an addressable id as the replay base. A source history with no discoverable pre-user checkpoint preserves the historical single-checkpoint branch behavior instead of rejecting the branch; regeneration remains unavailable for that inherited response. Existing single-checkpoint branches are not mutated by regenerate preparation, and no raw checkpoint tuple is copied across threads because delta state depends on ancestry and pending writes. Regenerate source-run lookup uses the current thread's exact event, then the server-stamped `run_id` on the copied human message, then verified RunManager content matching; it does not read parent-thread events. Storage or checkpoint-mode failures are not treated as a missing base and still fail closed.

**Wholesale message replacement uses a state-only mutation graph + `Overwrite`.** `update_state` values pass through channel reducers (`add_messages` merge in full, append in delta), so replacing `messages` wholesale (run rollback, context compaction) requires `{"messages": Overwrite([...])}`. The write goes through `build_state_mutation_graph(as_node, mode, state_schema)` — when the write carries materialized state, `state_schema` MUST be the thread's effective schema (`graph_state_schema(assistant_graph)`), because the base-ThreadState fallback silently discards written channels contributed by custom `AgentMiddleware.state_schema`. Channels absent from the write are unaffected: forked checkpoints clone the parent's channel blobs, so middleware channels survive rollback/compaction regardless of schema (locked by `test_rollback_preserves_middleware_contributed_channels` and `test_compact_thread_context_preserves_middleware_contributed_channels`) — a compiled graph with one no-op node (entry = finish) whose checkpoint machinery (channels/versions/metadata) is identical to the agent graph's but schedules no pending tasks, so the restored/compacted head stays idle instead of re-triggering the agent. Never hand-write checkpoints via `checkpointer.aput` for this; raw writers elsewhere must preserve checkpoint parentage — severed ancestry breaks delta replay (see `runtime/runs/worker.py` writer parenting and `checkpoint_patches.py`).

**Run rollback flow** (`runtime/runs/worker.py`): `_capture_rollback_point` materializes pre-run state (messages via accessor, raw `pending_writes` via `aget_tuple`) into an immutable `RollbackPoint` before the run starts — capture failure disables rollback (fail-closed), never restores partial state. Cancel-with-rollback then forks from the pre-run checkpoint via the mutation graph and replays the captured pending writes.

**Where things live**:
- `runtime/checkpoint_mode.py` — mode freeze, marker injection, delta detection, compatibility gate, both error types
- `runtime/checkpoint_state.py` — `CheckpointStateAccessor`, `build_state_mutation_graph`, `RollbackPoint`
- `checkpoint_patches.py` (package root) — saver patches: delta-history folding for `InMemorySaver` (delegating to the base walk), stable message IDs across materialization, upstream first-write drop fix
- `agents/thread_state.py` — `ThreadState`/`DeltaThreadState`, `DELTA_MESSAGES_FIELD` (`DeltaChannel` with `snapshot_frequency=1000`), schema adaptation helpers
- `runtime/context_compaction.py` — compaction via accessor + mutation graph (reference consumer)
- Tests: `tests/test_checkpoint_mode.py` (freeze/detect/gate), `tests/test_checkpoint_state.py` (accessor/mutation graph), `tests/test_delta_channel_checkpointers.py` (saver parity), `tests/test_threads_checkpoint_mode.py`, `tests/test_gateway_checkpoint_mode.py` (dual-mode e2e parity), `tests/test_context_compaction.py` (mutation-graph write, no scheduling), `tests/test_run_worker_rollback.py`

**Checkpoint channel benchmark**: `scripts/benchmark/bench_checkpoint_channels.py`
runs paired `full`/`delta` message-only StateGraphs in a fresh child process per
case, using sync `InMemorySaver` or `SqliteSaver` so reducer, serialization, and
saver costs stay separate from Gateway/async scheduling. It reports deterministic
correctness digests, write windows/percentiles, warm and graph-rebuilt cold reads,
logical checkpoint/write bytes, SQLite DB/WAL/SHM footprint, reducer replay time,
and peak RSS as versioned JSONL. The controller alternates mode order and rejects
performance data when paired modes materialize different state. Its default 1 GiB
estimated cumulative full-payload cap skips both modes of an oversized pair when
`full` is selected; intentional `--modes delta` diagnostics bypass this
full-payload cap, so size those runs explicitly. Use `--allow-large-cases` only
on a provisioned machine. Duplicate CSV matrix values are ignored with a warning;
use `--repetitions` for repeated samples. Summarize paired successful repetitions
with `scripts/benchmark/summarize_checkpoint_channels.py` (all ratios are
`delta/full`). `--profile-dir /tmp/checkpoint-profiles` writes one cProfile
artifact per case for attribution. Profiled rows carry `profiled: true`, and the
summarizer automatically excludes them from baseline summaries with a warning.
Storage-size collection relies on saver-specific diagnostic layouts; if those
layouts change, the timing/correctness row remains successful while storage
fields become `null` and `storage_stats_error` records the diagnostic failure.
Example:

```bash
cd backend
PYTHONPATH=. uv run python scripts/benchmark/bench_checkpoint_channels.py \
  --backends sqlite --updates 100,500,999,1000,1001 --payload-bytes 128 \
  --repetitions 7 --output /tmp/checkpoint-bench.jsonl
PYTHONPATH=. uv run python scripts/benchmark/summarize_checkpoint_channels.py \
  /tmp/checkpoint-bench.jsonl
```

The sync storage benchmark is not an end-to-end Gateway benchmark. Complete
`ThreadState`/`DeltaThreadState`, async saver scheduling, history, mutation,
rollback, migration, and branch-heavy cases belong to the production-shaped
follow-up layer. Harness tests live in `tests/test_bench_checkpoint_channels.py`
and `tests/test_summarize_checkpoint_channels.py`; timing thresholds are not CI
gates.

### Terminal Workbench / TUI (`packages/harness/deerflow/tui/`)

A terminal-native UI over the embedded harness, exposed as the `deerflow` console script (`[project.scripts]` in `packages/harness/pyproject.toml`). It is a UI shell over `DeerFlowClient` and does **not** fork agent behavior. `textual` is an optional dependency (`deerflow-harness[tui]`; also in the backend dev group); the console script degrades to headless help when it is absent. Full guide: [docs/TUI.md](docs/TUI.md).

**Module layout** (all layers except `app.py` are pure / Textual-free and unit-tested directly):
- `cli.py` — `plan_launch()` (pure launch-mode decision) + headless `--print` / `--json` + `main()` entry point. TTY → TUI, else headless help. Uses an **absolute** `from deerflow.tui.app import run_tui` so the `app.py` module name doesn't trip `test_harness_boundary.py` (which records relative import module names verbatim).
- `view_state.py` — `ViewState` + `reduce(state, action)`, the testable heart. Rows: user / assistant / tool / system. Title captured from `values` events.
- `runtime.py` — `translate(StreamEvent) -> [Action]` (pure) + `stream_actions()` which brackets a run with `RunStarted`/`RunEnded` and turns model errors into an `AssistantError` row.
- `message_format.py` / `command_registry.py` / `input_history.py` / `render.py` / `theme.py` — pure helpers (tool summaries, slash registry + `resolve()`, ↑/↓ history, Rich renderers).
- `app.py` — Textual `App`. Runs `DeerFlowClient.stream()` (sync) on a worker thread and marshals actions to the UI thread via `call_from_thread`. Slash palette with `/goal` management + model/thread modal pickers; routes idle display-only `/clear` through `ClearRows` without replacing the active thread, and blocks state-resetting local commands like `/new` and `/clear` with the standard "Still working" message during an active run; priority key bindings gated by `check_action` so they never steal keys from overlays or the composer.
- `session.py` / `persistence.py` — builds the client + checkpointer and the `ThreadMetaWriter`.

**Web UI visibility**: the Web UI lists threads from the `threads_meta` SQL table (user-scoped), not the checkpointer. `persistence.py` writes a `threads_meta` row under the default user (`"default"`) into the same DB the Gateway reads — via the harness-only `deerflow.persistence.engine.init_engine_from_config()` — so TUI sessions appear in the Web UI sidebar **without** running the Gateway. Best-effort: a no-op on the `memory` backend. All DB work runs on one long-lived background event loop (a SQLAlchemy async engine is bound to its creating loop).

**Tests**: `tests/test_tui_*.py` — pure layers via plain pytest, the app/palette/overlays via Textual's pilot harness with a fake in-process session, and `test_tui_persistence.py` for the `threads_meta` round-trip.

### Request Trace Context (`packages/harness/deerflow/trace_context.py`)

Request trace correlation is controlled by `logging.enhance.enabled` at **both** entry points, gated through the shared helper `deerflow.config.app_config.is_trace_correlation_enabled` so the Gateway and embedded paths cannot drift:

- **Gateway HTTP**: `app.gateway.trace_middleware.TraceMiddleware` binds one request-level trace id per HTTP request, inheriting inbound `X-Trace-Id` when present or generating a new id otherwise. A **valid** inbound header also marks the request so `runtime/runs/worker.py` prefers that id over `config.metadata.deerflow_trace_id`, keeping logs, response headers, Langfuse, and runtime context aligned when callers send both. The middleware writes the final value to every HTTP response at `http.response.start`, which covers SSE / streaming responses without consuming the body.
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

**Monocle telemetry** is a third provider, structurally unlike LangSmith/Langfuse. It is **not** a LangChain callback: `tracing/monocle.py::setup_monocle_tracing_if_enabled()` calls `monocle_apptrace.setup_monocle_telemetry()` once, which installs a **process-global OTel `TracerProvider`**, patches span serialization, and auto-instruments the openai/langchain/langgraph clients. Because that is a one-time, process-global side effect (not a per-run callback), it is initialized from the **Gateway lifespan** (`app/gateway/app.py`) — never from `build_tracing_callbacks()` — and it is **off by default**. The setup call was deliberately moved out of `agents/__init__.py`, so `import deerflow.agents` must never start tracing (pinned by `tests/test_monocle_tracing.py::test_no_import_time_setup`). The Gateway lifespan is the **sole call site** (pinned by `test_gateway_lifespan_initializes_monocle`), so unlike LangSmith/Langfuse — which attach at the graph roots and cover every path — the embedded `DeerFlowClient` and the TUI are not instrumented; embedded users who want Monocle traces call `setup_monocle_tracing_if_enabled()` themselves before running the agent.

Unlike the Langfuse metadata above, DeerFlow injects **no** per-run fields into Monocle traces — the only attribute it sets is `workflow_name="deer-flow"`; every span attribute (`span.type`, `entity.*`, token usage, span inputs/outputs, `scope.agentic.session`) is produced by Monocle's own metamodel and auto-instrumentation, so there is no DeerFlow trace-attribute layer to maintain here.

Config is env-driven like the others — `MonocleTracingConfig`, built in `get_tracing_config()` and gated by `is_monocle_tracing_enabled()`. `MONOCLE_TRACING` enables it; `MONOCLE_EXPORTERS` selects exporters (default `file` → trace JSON in `.monocle/`; also `console`, `okahu`, `s3`, `blob`, `gcs`, where `okahu` requires `OKAHU_API_KEY`). `setup_monocle_tracing_if_enabled()` stays a thin wrapper on purpose: `monocle_apptrace` already guards duplicate setup (`instrumentor.py::check_duplicate_setup`) and never force-overrides an existing global provider, so the wrapper only gates on config. Coexistence with Langfuse (v4, also OTel-based) is **verified**: whichever library initializes second reuses the existing global `TracerProvider` and attaches its own span processor, so neither side loses spans (pinned by `test_coexists_with_langfuse`). Both processors see all spans, so Monocle's exporters also capture Langfuse's spans when both are enabled. (LangSmith is a plain callback and coexists trivially.) Tests: `tests/test_monocle_tracing.py`.

### Config Schema

**`config.yaml`** key sections:
- `models[]` - LLM configs with `use` class path, `supports_thinking`, `supports_vision`, provider-specific fields
- `logging.enhance` - Optional request trace correlation (`enabled`, `format`) for Gateway `X-Trace-Id`, log `trace_id`, and Langfuse `deerflow_trace_id`
- vLLM reasoning models should use `deerflow.models.vllm_provider:VllmChatModel`; for Qwen-style parsers prefer `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking`, and DeerFlow will also normalize the older `thinking` alias
- `tools[]` - Tool configs with `use` variable path and `group`
- `tool_groups[]` - Logical groupings for tools
- `sandbox.use` - Sandbox provider class path
- `skills.path` / `skills.container_path` - Host and container paths to skills directory
- `skills.deferred_discovery` - When `true`, replaces the full-metadata `<available_skills>` prompt block with a compact `<skill_index>` (names only) and registers the `describe_skill` tool so the agent fetches metadata on demand. Defaults to `false` (legacy full-metadata injection)
- `title` - Auto-title generation (enabled, max_words, max_chars, model_name; null model_name uses fast local fallback, explicit model_name uses the prompt_template LLM path)
- `summarization` - Context summarization (enabled, trigger conditions, keep policy)
- `subagents.enabled` - Master switch for subagent delegation
- `memory` - Memory system (enabled, storage_path, debounce_seconds, shutdown_flush_timeout_seconds, model_name, max_facts, fact_confidence_threshold, injection_enabled, max_injection_tokens, staleness_review_enabled, staleness_age_days, staleness_min_candidates, staleness_max_removals_per_cycle, staleness_protected_categories, staleness_max_lifetime_multiplier, staleness_max_extension_days)

**`extensions_config.json`**:
- `mcpServers` - Map of server name → config (enabled, type, command, args, env, url, headers, oauth, description, `routing`, `tools`, `tool_call_timeout`). `routing.mode="prefer"` emits `<mcp_routing_hints>` prompt guidance; if `tool_search` defers the hinted tool, `McpRoutingMiddleware` can also auto-promote matching deferred schemas before the model call. It does not hard-disable other tools.
- `tool_search.auto_promote_top_k` - Global MCP routing auto-promote breadth. Default `3`, clamped to `1..5`; applies only when `tool_search.enabled=true` and only to deferred MCP tools with `routing.mode="prefer"` and non-empty keywords. For lead agents the deferred catalog is built from the full configured MCP set; auto-promotion never grants authority because an active skill's runtime policy still filters model-visible schemas, `tool_search` results, and execution.
- `skills` - Map of skill name → state (enabled)
- `middlewares` - Zero-argument `AgentMiddleware` class paths for lead and subagent runtime extension. `config.yaml -> extensions` can override these fields after validation; overrides are replace-per-field, not list concatenation.

Gateway API endpoints and `DeerFlowClient` methods can modify MCP servers and skill state at runtime; `middlewares` remains an operator-controlled config-file extension point.

### Embedded Client (`packages/harness/deerflow/client.py`)

`DeerFlowClient` provides direct in-process access to all DeerFlow capabilities without HTTP services. All return types align with the Gateway API response schemas, so consumer code works identically in HTTP and embedded modes.

**Architecture**: Imports the same `deerflow` modules that Gateway API uses. Shares the same config files and data directories. No FastAPI dependency.

**Agent Conversation**:
- `chat(message, thread_id)` — synchronous, accumulates streaming deltas per message-id and returns the final AI text
- `stream(message, thread_id)` — subscribes to LangGraph `stream_mode=["values", "messages", "custom"]` and yields `StreamEvent`:
  - `"values"` — full state snapshot (title, messages, artifacts); AI text already delivered via `messages` mode is **not** re-synthesized here to avoid duplicate deliveries
  - `"messages-tuple"` — per-chunk update: for AI text this is a **delta** (concat per `id` to rebuild the full message); tool calls and tool results are emitted once each
  - `"custom"` — forwarded from `StreamWriter`; DeerFlow-built-in custom events are dual-emitted through `deerflow.utils.custom_events`, so `astream_events(version="v2")` consumers also receive one `on_custom_event` with `name=payload["type"]` and the unchanged payload as `data`
  - `"end"` — stream finished (carries cumulative `usage` counted once per message id)
- **Custom-event invariant** — production DeerFlow emitters must use `emit_custom_event` / `aemit_custom_event`, not call `StreamWriter` alone. Every built-in payload must carry a non-empty string `type`; typeless payloads remain writer-only and are intentionally absent from `astream_events`. The writer runs first and remains authoritative for Gateway, Web UI, and embedded-client compatibility; callback dispatch is best-effort and must not break that path. Async graph hooks must await the async helper rather than invoking synchronous dispatch on a running event loop.
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
- Gateway HTTP upload/list/delete handlers offload filesystem work through `deerflow.utils.file_io.run_file_io`, a dedicated ContextVar-preserving file IO executor. Non-mounted sandbox uploads acquire sandboxes with `SandboxProvider.acquire_async()` and offload `read_bytes()` plus `sandbox.update_file()` together.
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
  The route shares the per-thread serialization gate used by `/goal` writes
  and run admission so compaction cannot race with goal updates or runs that
  read/write checkpoints.

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

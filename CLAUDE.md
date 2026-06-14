# Project Overview

DeerFlow is an open-source "super agent harness" (Python + TypeScript) for orchestrating agents, sub-agents, long-term memory, sandboxes and skills. It provides a Gateway HTTP API and optional LangGraph-backed agent runtime, a frontend (Next.js) UI, and an embedded Python client for in-process usage. Typical uses: running research / automation flows that spawn sub-agents, attach files to threads, and persist memory.

Primary languages/ecosystem: Python (backend, agent runtime), JavaScript/TypeScript + Next.js (frontend). Runtime tooling: Makefile, Docker, uv (python process manager), pnpm for frontend.

# Key Components

- backend/app/channels/feishu.py:FeishuChannel — WebSocket-based IM channel implementation (lark-oapi workaround, uploads/downloads, interactive cards).
- backend/app/channels/manager.py:ChannelManager — Orchestrates inbound messages → LangGraph runs; ingestion of inbound files; streaming assembly.
- backend/app/channels/service.py:ChannelService — Loads channel plugins, resolves service URLs from config/env, owns MessageBus/ChannelStore.
- backend/app/gateway/routers/* — HTTP API endpoints (memory, skills, uploads, runs) used by the frontend and APIs (e.g., backend/app/gateway/routers/memory.py).
- backend/app/gateway/services.py:format_sse / build_run_config / start_run — SSE framing, run config normalization (assistant_id → configurable.agent_name), and run lifecycle glue.
- backend/packages/harness/deerflow/client.py:DeerFlowClient — in-process client that mirrors Gateway semantics; streaming, agent caching and tool/middleware composition.
- backend/packages/harness/deerflow/agents/lead_agent/agent.py:make_lead_agent — lead agent factory, middleware assembly and model resolution.
- backend/packages/harness/deerflow/agents/lead_agent/prompt.py — system prompt generator and enabled-skills cache + background refresh.
- backend/packages/harness/deerflow/agents/memory/updater.py:MemoryUpdater — memory CRUD, LLM-driven memory extraction, deduplication and persistence via storage abstraction.
- backend/packages/harness/deerflow/agents/middlewares/* — collection of AgentMiddleware implementations (uploads, memory, loop_detection, etc.).
- backend/packages/harness/deerflow/sandbox/local/local_sandbox.py:LocalSandbox — local sandbox path mapping (container↔host), read-only mounts and host-path masking.
- backend/packages/harness/deerflow/sandbox/tools.py — sandbox-aware tools (bash, read_file, glob, grep) with virtual-path resolution and truncation.
- frontend/src/* — Next.js frontend (chat pages, prompt input, message rendering, artifacts, suggestions, command palette).
- docker/provisioner/app.py — Kubernetes-based sandbox provisioner (creates Pod + NodePort per sandbox_id).

# Architecture (high-level)

    [Browser UI (Next.js)]
            │
            ▼
    [Gateway API (FastAPI)] ──┬── [LangGraph server (optional)]
            │                 │
            │                 └── runs.wait / run manager
            │
            ├── Routers: /api/memory, /api/skills, /api/uploads, /runs
            └── Services: start_run, format_sse, StreamBridge
            │
            ▼
    [Agent factory / Lead Agent] ──> middlewares, tools, sandbox provider
            │
            ▼
    [Sandboxes (Local / AIO / Kubernetes provisioner)]
            │
            ▼
    [Persistent storage: uploads, memory storage, channel store]

# Core Data Structures

- backend/app/channels/message_bus.py:InboundMessage / OutboundMessage — canonical channel message models (used across channels).
- backend/packages/harness/deerflow/agents/memory/updater.py:fact / memory snapshot — facts {id, content, confidence, source, sourceError, ...} and memory object used by MemoryUpdater.
- backend/packages/harness/deerflow/agents/lead_agent/thread_state.py:ThreadState — per-run state schema used by agents and sandbox tooling.
- backend/packages/harness/deerflow/subagents/executor.py:SubagentResult / SubagentStatus — background subagent lifecycle and statuses consumed by task_tool.
- backend/packages/harness/deerflow/sandbox/local/local_sandbox.py:PathMapping — mapping of container_path -> local_path (+ read_only flag) used in path resolution.

# Control Flow

1. User (UI or IM channel) sends input → Gateway or MessageBus.
   - Channels publish InboundMessage to MessageBus; ChannelManager ingests files and starts runs.
2. Gateway receives /runs request → services.build_run_config normalizes request (context vs configurable) and resolves assistant_id → agent factory.
3. RunManager.create_or_reject + run_agent starts agent execution; StreamBridge streams SSE frames formatted by format_sse.
4. Agent graph (make_lead_agent) constructed: model resolution, middleware chain (uploads/memory/loop detection/etc.), and tools registered.
5. Middleware mutation examples:
   - UploadsMiddleware.before_agent prepends <uploaded_files> text to HumanMessage and provides uploaded_files in state.
   - MemoryMiddleware.after_agent queues filtered conversation for MemoryUpdater (detects corrections/reinforcement).
   - LoopDetectionMiddleware inspects tool_calls in AIMessage and injects warning or hard-stop when loops detected.
6. Subagents: task_tool starts a SubagentExecutor asynchronously and polls status, emitting lifecycle stream events; cancellation triggers cooperative cancel + deferred cleanup.
7. Sandboxes: tools call into sandbox provider (LocalSandbox or AioSandbox) to read/write files, execute commands; LocalSandbox maps container paths to host.

# Test-Driven Development

- Many modules have focused unit tests in backend/tests and frontend tests are built via pnpm. Before adding features, search for related tests (e.g., backend/tests/test_channels.py, test_memory_updater.py) and run them.
- Typical backend test commands: see Bash Commands below. Use mocks for external systems (LangGraph, SDKs) as in the repo tests.

# Bash Commands

- Run full backend tests: (from repo root)
  - cd backend && make test
  - or pytest backend/tests -q
- Run single backend test file:
  - pytest backend/tests/test_memory_updater.py -q
  - pytest backend/tests/test_channels.py -q
- Frontend dev/build:
  - cd frontend && pnpm install
  - cd frontend && pnpm dev
  - cd frontend && pnpm build
- Docker development:
  - make docker-init
  - make docker-start
  - make up / make down (production)
- Local dev quick flow:
  - make config
  - make install
  - make dev
- Utility checks (developer tooling):
  - python3 scripts/check.py  # verifies Node >=22, pnpm, uv, nginx

# Code Style / Conventions (notes)

- Preserve explicit virtual-path prefix semantics: VIRTUAL_PATH_PREFIX (/mnt/...) is canonical for sandbox mapping.
- Use create_chat_model / model factory helpers (do not pass raw model names directly) so alias resolution and options are applied.
- Use get_app_config() helper for configuration, and prefer push_current_app_config/pop_current_app_config for temporary overrides.
- Middleware ordering is semantically important; consult make_lead_agent:_build_middlewares when inserting new middlewares.

# Gotchas (high-priority)

- lark-oapi + asyncio: FeishuChannel MUST create a dedicated thread + event loop and patch the SDK module-level loop (see backend/app/channels/feishu.py:_run_ws). Don't instantiate SDK Client in main thread with running uvloop.
- Virtual path security: Always validate and resolve virtual paths via sandbox/tools.replace_virtual_path and LocalSandbox._resolve_path. Maintain resolve().relative_to checks to avoid path traversal.
- Memory confidence validation: _validate_confidence uses math.isfinite; raise ValueError('confidence') for NaN/Inf/out-of-range — tests depend on this string.
- Background tasks & cancellation: task_tool must call request_cancel_background_task on asyncio.CancelledError and schedule deferred cleanup; do not rely on thread termination without cooperative cancellation.
- Do not inject SystemMessage mid-conversation (Anthropic compatibility): use HumanMessage for warnings injected by LoopDetectionMiddleware.
- Preserve SSE frame format: format_sse ordering (event, data, optional id) and json.dumps ensure_ascii=False, default=str; clients/tests expect exact framing.

# Pattern Examples

- backend/app/gateway/services.py:format_sse — canonical SSE formatter; follow its field ordering and encoding.
- backend/packages/harness/deerflow/agents/lead_agent/agent.py:make_lead_agent — example of middleware assembly and lazy tool import to avoid circular deps.
- backend/packages/harness/deerflow/sandbox/local/local_sandbox.py:_resolve_path — canonical container→host mapping that uses longest-prefix matching.
- backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py:UploadsMiddleware.before_agent — how to safely expose uploaded files to the agent context and preserve additional_kwargs.

# Common Mistakes (symptom → fix)

- Symptom: Feishu WS Client raises RuntimeError about running loop.
  Fix: Ensure FeishuChannel._run_ws thread + loop patching remains; do not create SDK client on main loop (backend/app/channels/feishu.py:start/_run_ws).

- Symptom: Files uploaded appear outside outputs dir or traversal exception.
  Fix: Use ChannelManager._resolve_attachments and Tools.replace_virtual_path which enforce _OUTPUTS_VIRTUAL_PREFIX and resolve().relative_to(outputs_dir).

- Symptom: Memory fact confidence accepts NaN or Inf and later corrupts JSON.
  Fix: Use _validate_confidence (math.isfinite + 0<=x<=1) to validate before persist (backend/packages/.../memory/updater.py).

- Symptom: Subagent background task kept running after request cancel.
  Fix: task_tool must call request_cancel_background_task on CancelledError and schedule cleanup_when_done via asyncio.create_task.

# Invariants (must hold)

- Virtual paths returned to users must start with configured VIRTUAL_PATH_PREFIX and map into thread-scoped uploads/outputs.
- Memory facts must have finite confidence floats in [0,1] or raise ValueError('confidence').
- Middleware ordering constraints documented in _build_middlewares must be preserved (ThreadData before Sandbox, Clarification last, etc.).
- SSE frames must use the exact format from format_sse used by tests/clients.

# Anti-patterns (avoid)

- Directly manipulating host filesystem paths from tools without using sandbox providers' resolve helpers.
- Creating blocking sleeps in async tools (use asyncio.sleep). Task polling and timeouts must be async.
- Importing optional SDKs at module import time without graceful absence handling (many channel modules import SDKs lazily and log if missing).

# CI & Developer Notes

- CI workflows located in .github/workflows include backend-unit-tests.yml and lint-check.yml. Expect at least lint and backend tests in the matrix.
- README.md documents make targets for dev, docker, and production; use `make check`, `make install`, `make dev`, and `make docker-start` as entry points.
- Use python scripts/check.py locally to confirm developer toolchain (Node.js >=22, pnpm, uv, nginx).

# Sandbox & Security Considerations

- LocalSandbox enforces read-only mounts via PathMapping.read_only and raises OSError(errno.EROFS) for blocked writes.
- Host bash execution is disabled by default for LocalSandbox — enable only for fully trusted local setups and gate with is_host_bash_allowed checks.
- Prompt and skill mutation endpoints run security scanner (scan_skill_content) and record history entries; do not silently swallow scanner HTTPExceptions.

# Where to Start When Changing Code

- Channels & Manager: backend/app/channels/manager.py and backend/app/channels/message_bus.py (message flow, ingestion).
- Agent creation & middleware: backend/packages/harness/deerflow/agents/lead_agent/agent.py (model selection) and prompt.py (skills cache).
- Sandboxes & tools: backend/packages/harness/deerflow/sandbox/local/local_sandbox.py and backend/packages/harness/deerflow/sandbox/tools.py.
- Streaming & run lifecycle: backend/app/gateway/services.py and backend/packages/harness/deerflow/client.py (stream format parity).

If you made a change: run the focused tests that exercise that area (examples above) and `cd backend && make test`.

---
Concise CLAUDE.md generated for coding-agent onboarding. If you want, I can add quick reference snippets for common test commands per-target (channels, memory, sandbox, client) or expand the CI matrix details.

# Verification Checklist

- Run the full test matrix locally or in CI
- Confirm failing test fails before fix, passes after
- Run linters and formatters

# Test Integrity

- NEVER modify existing tests to make your implementation pass
- If a test fails after your change, fix the implementation, not the test
- Only modify tests when explicitly asked to, or when the test itself is demonstrably incorrect

# Suggestions for Thorough Investigation

When working on a task, consider looking beyond the immediate file:
- Test files can reveal expected behavior and edge cases
- Config or constants files may define values the code depends on
- Files that are frequently changed together (coupled files) often share context

# Must-Follow Rules

1. Work in short cycles. In each cycle: choose the single highest-leverage next action, execute it, verify with the strongest available check (tests, typecheck, run, lint, or a minimal repro), then write a brief log entry of what changed + what you'll do next.
2. Prefer the smallest change that can be verified. Keep edits localized, avoid broad formatting churn, and structure work so every change is easy to revert.
3. If you're missing information (requirements, environment behavior, API contracts), do not assume. Instead: inspect code, read docs in-repo, run a targeted experiment, add temporary instrumentation, or create a minimal reproduction to learn the truth quickly.


# Index Files

I have provided an index file to help navigate this codebase:
- `.claude/docs/general_index.md`

The file is organized by directory (## headers), with each file listed as:
`- `filename` - short description. Key: `construct1`, `construct2` [CATEGORY]`

You can grep for directory names, filenames, construct names, or categories (TEST, CLI, PUBLIC_API, GENERATED, SOURCE_CODE) to quickly find relevant files without reading the entire index.

**MANDATORY RULE — NO EXCEPTIONS:** After you read, reference, or consider editing a file or folder, you MUST run:
`python .claude/docs/get_context.py <path>`

This works for **both files and folders**:
- For a file: `python .claude/docs/get_context.py <file_path>`
- For a folder: `python .claude/docs/get_context.py <folder_path>`

This is a hard requirement for EVERY file and folder you touch. Without this, you'll miss recent important information and your edit will likely fail verification. Do not skip this step. Do not assume you already know enough. Do not batch it "for later." Do not skip files even if you have obtained context about a parent directory. Run it immediately after any other action on that path.

The command returns critical context you cannot infer on your own:

**For files:**
- Edit checklist with tests to run, constants to check, and related files
- Historical insights (past bugs, fixes, lessons learned)
- Key constructs defined in the file
- Tests that exercise this file
- Related files and semantic overview
- Common pitfalls

**For folders:**
- Folder role and responsibility in the codebase
- Key files and why they matter
- Cross-cutting behaviors across the subtree
- Distilled insights from every file in that folder

**Workflow (follow this exact order every time):**
1. Identify the file or folder you need to work with.
2. Run `python .claude/docs/get_context.py <path>` and read the output.
3. Only then proceed to read, edit, or reason about it.

If you need to work with multiple paths, run the command for each one before touching any of them.

**Violations:** If you read or edit a file or folder without first running get_context.py on it, you are violating a project-level rule. Stop, run the command, and re-evaluate your changes with the new context.



---
*This knowledge base was extracted by [Codeset](https://codeset.ai) and is available via `python .claude/docs/get_context.py <file_or_folder>`*

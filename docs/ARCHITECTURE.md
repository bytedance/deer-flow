# DeerFlow Architecture

This document is the **top-level architecture overview** for DeerFlow. It explains the
"big picture" — how the services, layers, and cross-cutting subsystems fit together — and
points to the module-level guides that own the depth:

- Backend depth → [`backend/AGENTS.md`](backend/AGENTS.md) and [`backend/docs/ARCHITECTURE.md`](backend/docs/ARCHITECTURE.md)
- Frontend depth → [`frontend/AGENTS.md`](frontend/AGENTS.md)

DeerFlow 2.0 is a ground-up rewrite of the original Deep Research framework (see
[`README.md`](README.md)); it shares no code with v1.

---

## 1. What DeerFlow Is

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) is an
open-source **super-agent harness** built on LangGraph. A single "lead agent" orchestrates
**sub-agents**, **persistent memory**, **sandboxed code execution**, and **extensible
skills/tools** — all isolated per conversation thread. The frontend is a Next.js chat UI;
external IM platforms (Feishu, Slack, Telegram, Discord, DingTalk) bridge into the *same*
agent through the Gateway.

---

## 2. Service Topology

A single `make dev` (or Docker stack) runs four cooperating services; Nginx is the only
public entry point.

| Service         | Port   | Role                                                                 |
| --------------- | ------ | ------------------------------------------------------------------- |
| **Nginx**       | `2026` | Unified reverse proxy — open this in the browser                    |
| **Gateway API** | `8001` | FastAPI REST API + embedded LangGraph-compatible agent runtime      |
| **Frontend**    | `3000` | Next.js web interface                                               |
| **Provisioner** | `8002` | Optional — only when sandbox is in provisioner/K8s mode             |

**Nginx routing** (the key entry-point contract):
- `/api/langgraph/*` → Gateway's LangGraph-compatible runtime (rewritten to native `/api/*`)
- `/api/*` (other) → Gateway REST routers
- `/*` (non-API) → Frontend

This lets standard LangGraph SDK clients talk to DeerFlow without a separate LangGraph
server. Both compose files publish nginx as `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`
— **loopback by default**; the Gateway's `8001` is never published. Any new published port
must carry an explicit bind address (`backend/tests/test_compose_default_bind_host.py`
pins this for every service in both compose files).

---

## 3. Backend: Harness / App Split

The backend is two layers with a **strict one-way dependency**:

- **Harness** (`backend/packages/harness/deerflow/`, import prefix `deerflow.*`) — the
  publishable agent framework: orchestration, tools, sandbox, models, MCP, skills, memory,
  config. Everything needed to *build and run* agents.
- **App** (`backend/app/`, import prefix `app.*`) — unpublished application code: the
  FastAPI Gateway and IM channel integrations.

**Rule**: App imports `deerflow`, but `deerflow` never imports `app`. This boundary is
enforced in CI by `backend/tests/test_harness_boundary.py`. A thin third package,
`deerflow-extension-api` (`backend/packages/extension-api/`), defines the host-independent
extension contract that plugins implement.

There is also an **embedded Python client** (`deerflow.client.DeerFlowClient`) used by
scheduled tasks and tests to drive the same run lifecycle programmatically.

### Agent runtime path

All run modes (local `make dev`, Docker, prod) execute the agent through the Gateway via
`RunManager` + `run_agent()` + `StreamBridge` (`packages/harness/deerflow/runtime/`). The
agent is assembled by `make_lead_agent()` and wrapped in a **middleware chain** that runs
before the model call:

1. ThreadDataMiddleware — set up `workspace`/`uploads`/`outputs` paths
2. UploadsMiddleware — inject uploaded file list
3. SandboxMiddleware — acquire sandbox
4. SummarizationMiddleware — context reduction (if enabled)
5. TitleMiddleware — auto-generate conversation title
6. TodoListMiddleware — task tracking (plan mode)
7. ViewImageMiddleware — vision-model image handling
8. ClarificationMiddleware — handle `ask_clarification`

SSE streaming carries both per-chunk messages and bounded `values` snapshots; with
`stream_subgraphs`, delegated subagents publish namespaced SSE events (`values|<ns>`,
LangGraph Platform style) rather than impersonating root frames, so SDK clients don't lose
the parent thread view.

### State, tools, sandbox

- **`ThreadState`** extends LangGraph's `AgentState` with `sandbox`, `artifacts`,
  `thread_data`, `title`, `todos`, `viewed_images`. Each thread gets isolated data dirs
  under `backend/.deer-flow/threads/{thread_id}/`.
- **Tools** come from three sources, merged by `get_available_tools()`: built-ins
  (`present_files`, `ask_clarification`, `view_image`, `review_skill_package`), configured
  tools (`bash`, `read_file`, `write_file`, `str_replace`, `ls`, web search/fetch), and
  MCP tools.
- **Sandbox** is an abstract `SandboxProvider` with `LocalSandboxProvider` (dev, direct
  execution) and `AioSandboxProvider` (Docker, production isolation). Agent code executes
  inside sandbox boundaries with virtual path mapping (`/mnt/user-data/...`).

---

## 4. Frontend: Stateful Chat over LangGraph SDK

Next.js 16 / React 19 / TypeScript / Tailwind v4. Stack: LangGraph SDK (`@langchain/langgraph-sdk`)
for orchestration + streaming, TanStack Query for server state. Requires Node 22+ and pnpm
10.26.2+.

The frontend is a **stateful chat app**: users create **threads** (conversations), send
messages, set thread-scoped `/goal` completion conditions, and receive streamed responses.
The backend may produce **artifacts** (files/code), **todos**, and goal-state updates.

**Source layout** (`frontend/src/`):
- `app/` — App Router routes: `/workspace/chats/[thread_id]` (authenticated chat),
  `/workspace/agents/[agent_name]` (custom agents), `/showcase/[thread_id]` (allowlisted
  public read-only demos), `/api/*` route handlers, `(auth)/{login,setup,auth/callback}`.
- `core/` — the business-logic heart. Domains: `threads/` (creation, streaming, state),
  `api/` (LangGraph client singleton), `agents/`, `auth/`, `artifacts/`, `channels/`,
  `integrations/`, `memory/`, `skills/`, `mcp/`, `models/`, `tasks/`, `todos/`, `tools/`,
  `workspace-changes/`, `config/`, `i18n/` (en-US, zh-CN), and more.
- `components/` — `workspace/` (chat), `landing/`, `docs/`; `ui/` and `ai-elements/` are
  registry-generated (Shadcn / Vercel AI SDK) and must not be hand-edited.
- `hooks/`, `lib/` (`cn()`), `content/` (MDX), `styles/`.

**Streaming data flow**: `core/threads/` subscribes to the LangGraph run stream via the
`core/api/` client singleton, normalizes SSE events (messages, `values`, `task_*`,
artifact deltas) into TanStack-Query-managed thread state that components render. Subtask
progress rides root-namespace `task_*` custom events (the web frontend does not request
subgraph streaming).

By default the frontend connects through nginx: `NEXT_PUBLIC_LANGGRAPH_BASE_URL=/api/langgraph`
and `NEXT_PUBLIC_BACKEND_BASE_URL=` (empty). Leave these unset for the standard `make dev`
/ Docker flow.

---

## 5. Cross-Cutting Subsystems

These span both layers and require reading multiple files to understand:

- **Config system** — lives at repo root: `config.yaml` (models, tools, sandbox,
  summarization, scheduler) and `extensions_config.json` (MCP servers + skills). Both are
  gitignored, generated from the `*.example.*` templates, and editable at runtime via the
  Gateway API. Operator-controlled third-party `plugins:` live only in `config.yaml`
  (never the API-writable `extensions_config.json`) because that list causes code import.
- **Skills** — `skills/public/` (committed) and `skills/custom/` (gitignored); managed
  integration packs are global at `.deer-flow/integrations/skills/{provider}/`. Skills are
  discovered/loaded lazily by the harness; `skills/public/skill-reviewer/` is a read-only
  quality reviewer using the harness `review_skill_package` tool.
- **Sub-agents** — background delegation via `SubagentExecutor` (server-side `execution_id`)
  correlated to provider `tool_call_id` for `ToolMessage`/SSE/lifecycle/persistence. Scheduled
  tasks reuse the *same* Gateway run lifecycle (scheduler decides *when*, not *how*).
- **Scheduled tasks** — workspace page `/workspace/scheduled-tasks` + a background scheduler
  gated by `config.yaml → scheduler.enabled`; non-interactive runs drop `ask_clarification`
  and client-supplied `non_interactive`.
- **Long-running MCP** — a durable `McpTaskService` (leased rows, DB as source of truth)
  keeps remote task IDs/polling out of the agent loop.
- **Version sources** — a release version must match in `backend/pyproject.toml`,
  `frontend/package.json`, and `deploy/helm/deer-flow/Chart.yaml` (`version` + `appVersion`);
  pushing a `v*` tag triggers CI that runs `scripts/verify_versions.sh` and blocks all
  publishing on drift. See [`RELEASING.md`](RELEASING.md).

---

## 6. Security & Isolation Model

- **Thread isolation**: each conversation has separate data dirs; uploads are validated
  against path traversal and staged as `.upload-*.part` before atomic replace.
- **Sandbox isolation**: production should use the Docker `AioSandboxProvider`; local
  sandbox is dev-only direct execution.
- **MCP isolation**: each MCP server runs in its own process with runtime env-var
  resolution; servers toggle independently.
- **Loopback-by-default ingress**: nginx is the only published surface; the Gateway's `8001`
  is container-internal and never published. A bare `"${PORT}:2026"` bind (0.0.0.0) is
  rejected by convention and CI. See the Security Notice in [`README.md`](README.md) before
  any non-loopback deployment.

---

## 7. Where to Go Next

- System topology & component depth → [`backend/docs/ARCHITECTURE.md`](backend/docs/ARCHITECTURE.md)
- Backend commands, TDD, harness/app boundary, config reload → [`backend/AGENTS.md`](backend/AGENTS.md)
- Frontend commands, source layout, streaming data flow → [`frontend/AGENTS.md`](frontend/AGENTS.md)
- Setup & install → [`Install.md`](Install.md), [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Release process → [`RELEASING.md`](RELEASING.md)
- User-facing features & deployment sizing → [`README.md`](README.md)

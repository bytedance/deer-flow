# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, OpenCode, and others) when working with code in this repository. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

It is the **monorepo orientation layer** plus the **project lock-decisions and
delivery gate** (the non-negotiable rules every agent must follow). It maps the
whole repo and points to the module guides that own the depth:

- **[backend/AGENTS.md](backend/AGENTS.md)** — backend depth: harness/app split detail, agent &
  middleware chain, sandbox, MCP, skills, memory, IM channels, persistence/migrations,
  config system, test layout.
- **[frontend/AGENTS.md](frontend/AGENTS.md)** — frontend depth: Next.js App Router layout,
  thread/streaming data flow, code style, commands.
- **[docx/dev-setup.md](docx/dev-setup.md)** — commands and project layout snapshot (changes often).

## What is DeerFlow

DeerFlow is a LangGraph-based AI super-agent system with a full-stack architecture. The
backend runs a "super agent" with sandboxed execution, persistent memory, subagent
delegation, and extensible tools (built-in, MCP, community), all per-thread isolated. The
frontend is a Next.js chat UI. External IM platforms (Feishu, Slack, Telegram, Discord,
DingTalk) bridge into the same agent through the Gateway.

## Service Topology

A single `make dev` / Docker stack runs four cooperating services:

| Service         | Port   | Role                                                                 |
| --------------- | ------ | ------------------------------------------------------------------- |
| **Nginx**       | `2026` | Unified reverse-proxy entry point — open this in the browser        |
| **Gateway API** | `8001` | FastAPI REST API + embedded LangGraph-compatible agent runtime      |
| **Frontend**    | `3000` | Next.js web interface                                               |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx is the single public entry: it serves the frontend and proxies `/api/langgraph/*`
to the Gateway's LangGraph runtime, rewriting it to Gateway's native `/api/*` routes; all
other `/api/*` go straight to the Gateway REST routers.

## Repository Map

```
deer-flow/
├── Makefile                        # Root orchestration: drives the full stack (dev/start/stop, docker, setup)
├── config.example.yaml             # Template → copy to config.yaml (gitignored) at repo root
├── extensions_config.example.json  # Template → copy to extensions_config.json (gitignored): MCP servers + skills
├── backend/                        # Python backend — see backend/AGENTS.md
│   ├── Makefile                    # Per-module backend commands (dev, gateway, test, lint, migrate-rev)
│   ├── packages/harness/           # deerflow-harness package (import: deerflow.*) — agent framework
│   └── app/                        # FastAPI Gateway + IM channels (import: app.*)
├── frontend/                       # Next.js frontend (pnpm) — see frontend/AGENTS.md
├── docker/                         # docker-compose files, nginx config, provisioner
├── skills/                         # Agent skills: public/ (committed), custom/ (gitignored)
├── contracts/                      # Cross-component JSON contracts (e.g. subagent status)
├── scripts/                        # Root orchestration scripts invoked by the Makefile (check, configure, doctor, support_bundle, serve, nginx, docker, deploy, setup_wizard)
├── tests/                          # Root-level tests (currently tests/skills/ — public skill tests)
└── docs/                           # Cross-cutting docs, plans, and design notes
```

Runtime config lives at the **repo root**: copy `config.example.yaml` → `config.yaml`
(main app config) and `extensions_config.example.json` → `extensions_config.json` (MCP
servers + skills). Both real files are gitignored and may be edited at runtime via the
Gateway API.

Scheduled-task note:
- The scheduled-task MVP adds a workspace page at `/workspace/scheduled-tasks` plus a background scheduler service gated by `config.yaml -> scheduler.enabled`.
- Scheduled background runs are intentionally non-interactive: they execute through the normal run lifecycle, but the lead-agent toolset excludes `ask_clarification` when `context.non_interactive=true`. The key is honored only for internally-authenticated callers (the scheduler launch path); client-supplied `context.non_interactive` is dropped.

## Commands: Root vs. Module

Detailed commands and the per-file layout live in [docx/dev-setup.md](docx/dev-setup.md);
this section is the quick map.

**Root `make` targets drive the whole stack** (run from the repo root):

```bash
make check      # Verify Node 22+, pnpm, uv, nginx
make install    # Install backend (uv sync) + frontend (pnpm install) + pre-commit hooks
make setup      # Interactive setup wizard — generates config.yaml + writes API keys to .env
make doctor     # Validate setup; actionable fix hints
make dev        # Start all services with hot-reload (Gateway + Frontend + Nginx)
make dev-pro    # Gateway mode: agent runtime embedded in Gateway (no separate LangGraph server)
make start      # Production mode (local, optimized)
make stop       # Stop all running services
make up / down  # Build/stop the production Docker stack (browser at localhost:2026)
```

**Per-module commands** (run inside that module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # LangGraph server :2024  |  make gateway for :8001
cd backend && make test       # pytest
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Turbopack (port 3000)
cd frontend && pnpm check     # Lint + type check (run before committing)
cd frontend && pnpm test      # Unit tests (Rstest)
cd frontend && pnpm test:e2e  # Playwright Chromium E2E
```

Rule of thumb: **root `make` = the full application**; **`backend/Makefile` and `frontend/`
(`pnpm`) = per-module work.**

## Backend Module Boundary (Harness / App)

CI-enforced by `backend/tests/test_harness_boundary.py` — do not break it.

| Package | Prefix | Contents |
|---|---|---|
| `backend/packages/harness/deerflow/` | `deerflow.*` | Publishable `deerflow-harness`. Agents, sandbox, tools, models, MCP, skills, config. |
| `backend/app/` | `app.*` | Unpublished. FastAPI Gateway and IM channel integrations. |

`app.*` may import `deerflow.*`. **`deerflow.*` MUST NOT import `app.*`** — fails CI.

## Runtime Modes

- **Standard** (`make dev`): LangGraph :2024 + Gateway :8001 + Frontend :3000 + nginx :2026. Nginx routes `/api/langgraph/*` → LangGraph, `/api/*` → Gateway.
- **Gateway** (`make dev-pro`): agent runtime embedded in Gateway via `RunManager` + `run_agent()` + `StreamBridge`. Concurrency via async tasks. Nginx → Gateway only.

## Sandbox Virtual Paths

The agent sees a stable virtual filesystem regardless of sandbox provider:

- `/mnt/user-data/{workspace,uploads,outputs}` → physical `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`
- `/mnt/skills` → `deer-flow/skills/`
- `/mnt/acp-workspace` → per-thread ACP workspace (read-only from lead agent)

`user_id` is resolved via `get_effective_user_id()` (falls back to `"default"` in
no-auth mode). Translation helpers: `replace_virtual_path()` / `replace_virtual_paths_in_command()`
in `packages/harness/deerflow/sandbox/tools.py`.

## Project Lock-Decisions

Hard non-negotiable rules. Don't drift.

- **Local-only trust** — 127.0.0.1 loopback is the default. LAN / public deployment
  requires IP allowlist + auth gateway. See `CONTRIBUTING.md` (security section) and
  `README.md` security notice.
- **chatbi-report is the active report skill** — sqlbot-report is retired. Do not reopen
  ai-report without an executable E2E passing on a real fixture (ai-report was archived
  2026-07-01).
- **Cross-cutting constraints extracted at boundaries first** — precision, security,
  locale, audit, threading. Build the boundary handler + unit test BEFORE feature code.
- **Middleware order is runtime-registered**, not hard-coded in docs. The current list
  is at `backend/packages/harness/deerflow/agents/middlewares/` plus runtime registration
  in `lead_agent/agent.py::build_middlewares` and `tool_error_handling_middleware.py::build_lead_runtime_middlewares`.
  Code is the source of truth.
- **Hot-reload vs. restart-required config** — runtime fields (`models[*].max_tokens`,
  `summarization.*`, `title.*`, `memory.*`, `subagents.*`, `tools[*]`, agent system prompt)
  pick up `config.yaml` edits on the next message. Infrastructure fields (`database`,
  `checkpointer`, `run_events`, `stream_bridge`, `sandbox`, `log_level`, `channels`,
  `channel_connections`) are **restart-required**. The authoritative list lives in
  `packages/harness/deerflow/config/reload_boundary.py::STARTUP_ONLY_FIELDS`; the
  standardized `"startup-only:"` prefix on the corresponding `Field(description=...)` in
  `AppConfig` surfaces the reason in IDE hover. Drift is pinned by
  `tests/test_reload_boundary.py`.
- **Gateway workers** — production defaults to a single Gateway worker
  (`GATEWAY_WORKERS=1`) because the Gateway holds run state (RunManager, stream bridge)
  in process. Raising worker count without a shared cross-worker stream bridge breaks
  run cancellation, SSE reconnects, request de-duplication, and IM channels. Scale a
  single worker up with more CPU/RAM (or move the database and sandbox onto dedicated
  tiers) instead of raising `GATEWAY_WORKERS`.
- **Same-origin CORS by default** — nginx on :2026 is same-origin. Split-origin or
  port-forwarded browser clients must set `GATEWAY_CORS_ORIGINS` (comma-separated exact
  origins); Gateway `CORSMiddleware` and `CSRFMiddleware` both read that variable.

## Change Delivery Gate

Before claiming "完成" / "通过" / "ready to merge":

1. **Evidence first** — verification actually ran. If a key check can't run, say why —
   don't skip silently.
2. **Quality gate cleared** (review / verification pass).
3. **Command output is real**, not invented.
4. **Without evidence** → answer is "未跑通" or "待验证", never "should work".

Process discipline (brainstorm → spec → TDD → verify → review) is in the
`brainstorming`, `test-driven-development`, `systematic-debugging`, and
`requesting-code-review` skills. This file only states the **delivery gate** because
it's a project-specific cap on what "done" means.

## Where to Go Next

- Backend work → **[backend/AGENTS.md](backend/AGENTS.md)**
- Frontend work → **[frontend/AGENTS.md](frontend/AGENTS.md)**
- Commands & layout snapshot → **[docx/dev-setup.md](docx/dev-setup.md)**
- Setup & install → **[Install.md](Install.md)**, **[CONTRIBUTING.md](CONTRIBUTING.md)**
- Project overview & usage → **[README.md](README.md)**
- Security policy → **[SECURITY.md](SECURITY.md)**
- Changes → **[CHANGELOG.md](CHANGELOG.md)**

## Cross-Cutting Conventions

These apply repo-wide; module guides own the module-specific detail.

- **Documentation update policy** — keep docs in sync with code: update `README.md` for
  user-facing changes and the relevant `AGENTS.md` for development/architecture changes in
  the same change set.
- **Test-driven development** — features and bug fixes ship with tests. Backend tests live
  in `backend/tests/` (TDD is mandatory there; see [backend/AGENTS.md](backend/AGENTS.md));
  frontend tests live in `frontend/tests/`.
- **Format before pushing** — run `make format` (backend) / `pnpm check` (frontend). Backend
  CI enforces `ruff format --check`, so formatting must be clean before a push.
- **AI assistance disclosure** — every PR must complete the "AI assistance" section of
  `.github/pull_request_template.md` (tool(s) used, how used, human review confirmation).
- **Support bundle for issues** — `make support-bundle` produces a redacted
  `*-issue-summary.md` (paste into the issue), a `*-issue-draft.md` (for AI-assisted
  filing, fill REQUIRED placeholders), and an optional evidence zip under
  `.deer-flow/support-bundles/`. Attach the zip only if a maintainer asks or the summary
  alone is not enough. The bundle intentionally excludes `.env`, raw conversation
  messages, and workspace file contents.

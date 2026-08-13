# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with code in this repository. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

It is the **monorepo orientation layer**: it maps the whole repo and points to the
module guides that own the depth. For anything inside a module, read that module's
guide rather than expecting full detail here:

- **[backend/AGENTS.md](backend/AGENTS.md)** — backend depth: harness/app split, agent &
  middleware chain, sandbox, MCP, skills, memory, IM channels, persistence/migrations,
  config system, test layout.
- **[frontend/AGENTS.md](frontend/AGENTS.md)** — frontend depth: Next.js App Router layout,
  thread/streaming data flow, code style, commands.

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
other `/api/*` go straight to the Gateway REST routers. See
[backend/AGENTS.md](backend/AGENTS.md) for the runtime and router detail.
It compresses HTML and configured textual assets, while deliberately leaving SSE,
fonts, images, audio, and video uncompressed at the proxy layer.

Both compose files publish that entry as `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`
— **loopback by default**, matching the README's documented deployment model. A bare
`"${PORT}:2026"` binds `0.0.0.0`, which does not.
The root `PORT` value is Docker ingress configuration only; local orchestration pins
Next.js to `3000` so loading `.env` cannot make `make dev` wait on the wrong port.
Nginx itself listens `default_server` on IPv4+IPv6 and the
Gateway binds `0.0.0.0:8001` inside the container on purpose — both are container-
internal; the published nginx port is the entire external surface, and the Gateway's
`8001` is deliberately not published. Any new published port needs an explicit bind
address; `backend/tests/test_compose_default_bind_host.py` pins this for every service
in both compose files.

## Repository Map

```
deer-flow/
├── Makefile                        # Root orchestration: drives the full stack (dev/start/stop, docker, setup)
├── config.example.yaml             # Template → copy to config.yaml (gitignored) at repo root
├── extensions_config.example.json  # Template → copy to extensions_config.json (gitignored): MCP servers + skills
├── backend/                        # Python backend — see backend/AGENTS.md
│   ├── Makefile                    # Per-module backend commands (dev, gateway, test, lint, migrate-rev)
│   ├── extensions/sources/         # Deployable snapshots of locally installed Python extensions
│   ├── packages/extension-api/     # deerflow-extension-api package (import: deerflow_extension_api.*) — public extension contract
│   ├── packages/harness/           # deerflow-harness package (import: deerflow.*) — agent framework
│   └── app/                        # FastAPI Gateway + IM channels (import: app.*)
├── frontend/                       # Next.js frontend (pnpm) — see frontend/AGENTS.md
├── docker/                         # docker-compose files, nginx config, provisioner
├── skills/                         # Agent skills: public/ (committed), custom/ (gitignored)
│                                    # Managed integration skill packs are global at .deer-flow/integrations/skills/{provider}/
│                                    # Integration credentials and enabled state remain per-user
├── contracts/                      # Cross-component JSON contracts (e.g. subagent status, skill review)
├── examples/deerflow-extension-example/ # Standalone package demonstrating all extension contribution kinds
├── scripts/                        # Root orchestration scripts invoked by the Makefile (check, configure, doctor, support_bundle, serve, nginx, docker, deploy, setup_wizard)
├── tests/                          # Root-level tests (currently tests/skills/ — public skill tests)
└── docs/                           # Cross-cutting docs, plans, and design notes
```

Third-party extensions are loaded from a top-level `plugins:` list in `config.yaml`
(operator-controlled on purpose — that list causes code to be imported, so it is deliberately
kept out of the API-writable `extensions_config.json`). Packaged extensions can contribute
middleware, task lifecycle, system-model observers, Gateway services, and FastAPI HTTP
routers; the [reference extension](examples/deerflow-extension-example/) demonstrates all
five. Manage them with `deerflow extensions install/list/enable/disable/remove` or the root
`make extension-*` wrappers. Every mutation requires a Gateway restart, and both build
hooks and extension code execute with Gateway privileges, so only trusted operator sources
belong in this path. The manager transaction, accepted source forms, lock discipline, and
contribution contract live in
[the extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md).

Runtime config lives at the **repo root**: copy `config.example.yaml` → `config.yaml`
(main app config) and `extensions_config.example.json` → `extensions_config.json` (MCP
servers + skills). Both real files are gitignored and may be edited at runtime via the
Gateway API. Config schema and resolution order are documented in
[backend/AGENTS.md](backend/AGENTS.md).

Skill quality review note:
- `skills/public/skill-reviewer/` is the built-in read-only skill quality reviewer.
  It uses the harness-layer `review_skill_package` tool and contracts in
  `contracts/skill_review/`. Model-visible review data is compact and
  tag-neutralized; full raw payloads stay in tool artifacts. See
  [backend/AGENTS.md](backend/AGENTS.md) for the non-activation, SkillScan, and
  `skill-creator` ownership boundaries.

Scheduled-task note:
- The scheduled-task MVP adds a workspace page at `/workspace/scheduled-tasks` plus a background scheduler service gated by `config.yaml -> scheduler.enabled`.
- Scheduled background runs are intentionally non-interactive: they execute through the normal run lifecycle, but the lead-agent toolset excludes `ask_clarification` when `context.non_interactive=true`. The key is honored only for internally-authenticated callers (the scheduler launch path); client-supplied `context.non_interactive` is dropped.

## Commands: Root vs. Module

**Root `make` targets drive the whole stack** (run from the repo root):

```bash
make setup       # Interactive setup wizard (recommended for new users)
make doctor      # Check configuration and system requirements
make support-bundle  # Generate redacted troubleshooting summary, AI issue draft, and optional zip
make config      # Generate local config files from the examples
make check       # Check that required tools are installed
make install     # Install all dependencies (frontend + backend + pre-commit hooks)
make extension-install SOURCE=...  # Install and enable a trusted Python extension
make extension-list                # List configured Python extensions
make extension-enable NAME=...     # Enable an installed extension (restart required)
make extension-disable NAME=...    # Disable without uninstalling (restart required)
make extension-remove NAME=...     # Remove package and config entry (restart required)
make dev         # Start all services with hot-reload (Gateway + Frontend + Nginx)
make start       # Start all services in production mode (local, optimized)
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make docker-start / docker-stop / docker-logs   # Docker development environment
```

Production startup uses the image's pre-built Python environment with `uv run
--no-sync`, gives the Gateway a real `/health` probe, and makes `make up` wait
for that probe before printing its success banner. A readiness failure must
surface Compose status and recent Gateway logs instead of claiming the stack is
running.

Docker log and restart commands resolve `DEER_FLOW_ROOT` from the current
checkout before invoking Compose, matching the start and stop commands.

Run `make help` for the full list.

**Per-module commands drive a single module** (run inside that module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # Gateway API with reload (port 8001)
cd backend && make test       # Backend test suite
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Dev server with Turbopack (port 3000)
cd frontend && pnpm check     # Lint + type check (run before committing)
cd frontend && pnpm test      # Unit tests
```

Rule of thumb: **root `make` = the full application**; **`backend/Makefile` and `frontend/`
(`pnpm`) = per-module work.**

Host-side pnpm consumers, including the root/frontend Makefiles and local diagnostic scripts, must run through `scripts/pnpm.py`. Diagnostic scripts resolve the runner and frontend directory to absolute paths before changing the child process working directory, so they remain independent of the caller's current directory. The runner preserves direct `pnpm`/`pnpm.cmd` priority, falls back to `corepack pnpm`, and is invoked from `frontend/` so Corepack honors the package-manager version pinned by that project.

## Where to Go Next

- Backend work → **[backend/AGENTS.md](backend/AGENTS.md)**
- Frontend work → **[frontend/AGENTS.md](frontend/AGENTS.md)**
- Setup & install → **[Install.md](Install.md)**, **[CONTRIBUTING.md](CONTRIBUTING.md)**
- Project overview & usage → **[README.md](README.md)** (translations: `README_zh.md`,
  `README_ja.md`, `README_fr.md`, `README_ru.md`)
- Security policy → **[SECURITY.md](SECURITY.md)**
- Changes → **[CHANGELOG.md](CHANGELOG.md)**
- Cutting a release → **[RELEASING.md](RELEASING.md)**

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

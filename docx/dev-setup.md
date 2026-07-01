# dev-setup.md — DeerFlow commands & layout

> Read alongside `CLAUDE.md`. This file holds commands and code-map snapshots that change often; CLAUDE.md stays static.

## Commands

Run from **project root** unless otherwise noted. Backend commands: `cd backend`. Frontend commands: `cd frontend`.

### Full application

| Command | Purpose |
|---|---|
| `make check` | Verify Node.js 22+, pnpm, uv, nginx |
| `make install` | Install backend (uv sync) + frontend (pnpm install) deps |
| `make setup` | Interactive setup — generates `config.yaml` + writes API keys to `.env` |
| `make doctor` | Validate setup; actionable fix hints |
| `make config` | `config.example.yaml` → `config.yaml` (no-op if exists) |
| `make dev` | All services: LangGraph :2024, Gateway :8001, Frontend :3000, nginx :2026 |
| `make dev-pro` | Gateway mode (agent runtime embedded in Gateway, no separate LangGraph server) |
| `make stop` | Stop all running services |
| `make clean` | Stop + remove `.deer-flow` data and logs |

### Backend (cd backend/)

| Command | Purpose |
|---|---|
| `make dev` | LangGraph server only :2024 |
| `make gateway` | Gateway API only :8001 |
| `make lint` | ruff |
| `make format` | ruff format |
| `make test` | pytest |

### Frontend (cd frontend/)

| Command | Purpose |
|---|---|
| `pnpm dev` | Turbopack dev server :3000 |
| `pnpm build` | Production build |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | TypeScript check |
| `pnpm test` | Vitest unit |
| `pnpm test:e2e` | Playwright/Chromium E2E |

## Project layout

```
deer-flow/
├── Makefile                  # dev, stop, docker-*, up/down
├── config.example.yaml       # primary config template
├── extensions_config.json    # MCP servers + skills state
├── backend/
│   ├── packages/harness/deerflow/   # deerflow-harness (publishable, prefix `deerflow.*`)
│   │   ├── agents/           # lead agent, middlewares, memory, thread_state
│   │   ├── sandbox/          # bash, ls, read/write/str_replace
│   │   ├── subagents/        # registry + executor
│   │   ├── tools/builtins/   # present_files, ask_clarification, view_image
│   │   ├── mcp/  models/  skills/  config/
│   │   ├── community/        # Tavily, Jina, Firecrawl, AioSandbox, ACP
│   │   ├── reflection/       # dynamic module/class loading
│   │   └── client.py
│   ├── app/gateway/          # FastAPI routers (models, mcp, skills, memory, uploads, threads, artifacts)
│   ├── app/channels/         # IM: Feishu, Slack, Telegram, WeChat, WeCom
│   └── tests/
├── frontend/                 # Next.js 16 + React 19 + TS
│   ├── src/app/  src/components/  src/core/
│   └── tests/
└── skills/
    ├── public/               # built-in skills (committed)
    └── custom/               # custom skills (gitignored)
```

Verify with `tree -L 4 backend/ frontend/ skills/` on a fresh checkout.

## First-time setup

1. `make check` — prereqs (Node 22+, pnpm, uv, nginx)
2. `make install` — backend (uv sync) + frontend (pnpm install)
3. `make setup` or `cp config.example.yaml config.yaml` — configure
4. `make dev` — open http://localhost:2026

For backend-only iterations: `cd backend && make lint && make test`
For frontend-only: `cd frontend && pnpm lint && pnpm typecheck && BETTER_AUTH_SECRET=... pnpm build`

## Config conventions

- `config.yaml` lives at **project root** (not `backend/`). Values starting with `$` resolve as environment variables.
- `extensions_config.json` (also project root) holds MCP servers + skill states.
- `config_version` in `config.example.yaml` enables auto-upgrade via `make config-upgrade`.

## IM Channels

Feishu uses `client.runs.stream(["messages-tuple", "values"])` with a single card patched in place. Slack/Telegram use `client.runs.wait()` for final response. Channels run inside the `gateway` container in Docker Compose — use container service names for `channels.langgraph_url` / `channels.gateway_url`.

## Security

Designed for **local trusted environments** (127.0.0.1 loopback). LAN / public cloud requires IP allowlisting + authentication gateway. See `CONTRIBUTING.md` for details.

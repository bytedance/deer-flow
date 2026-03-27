# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeerFlow is a full-stack "super agent harness" built on LangGraph + FastAPI (backend) and Next.js (frontend), unified behind nginx at `http://localhost:2026`.

- **Backend**: Python 3.12, LangGraph server (port 2024) + FastAPI gateway (port 8001)
- **Frontend**: Next.js 16 + React 19 + TypeScript (port 3000)
- **Nginx**: Reverse proxy on port 2026 (unified entry point for dev and production)

For deep backend architecture details, see `backend/CLAUDE.md`.

## Requirements

- Node.js `>=22`, pnpm (10.x), Python `>=3.12`, `uv`, `nginx`

## Commands

**From repo root** (full stack):
```bash
make config         # First-time only: generate config.yaml from config.example.yaml (non-idempotent)
make config-upgrade # Merge new fields from config.example.yaml into existing config.yaml
make check          # Verify required tools are installed
make install        # Install all dependencies (backend uv sync + frontend pnpm install)
make dev            # Start all services (LangGraph + Gateway + Frontend + nginx), logs in logs/
make stop           # Stop all services
make clean          # stop + remove .deer-flow/, .langgraph_api/, logs/
```

**Docker development** (recommended for consistency):
```bash
make docker-init    # Build images + install deps (first time)
make docker-start   # Start services (auto-detects provisioner mode from config.yaml)
make docker-stop    # Stop
make docker-logs    # View logs
```

**Docker production**:
```bash
make up   # Build and start production containers
make down # Stop and remove containers
```

**Backend only** (from `backend/`):
```bash
make dev            # LangGraph server only (port 2024)
make gateway        # Gateway API only (port 8001)
make test           # Run all backend tests (277 tests, ~77s)
make lint           # ruff check
make format         # ruff format

# Single test file
PYTHONPATH=. uv run pytest tests/test_<feature>.py -v
```

**Frontend only** (from `frontend/`):
```bash
pnpm lint
pnpm typecheck
BETTER_AUTH_SECRET=local-dev-secret pnpm build
```

## Architecture

```
agent_server/
├── Makefile                      # Root orchestration
├── config.yaml                   # Main app config (gitignored, copy from config.example.yaml)
├── extensions_config.json        # MCP servers and skills (gitignored)
├── backend/                      # Python backend
│   ├── packages/harness/deerflow/ # deerflow-harness package (agent, tools, sandbox, MCP, memory)
│   ├── app/                      # FastAPI gateway + IM channel integrations
│   ├── tests/                    # Test suite
│   └── langgraph.json            # LangGraph entrypoint (deerflow.agents:make_lead_agent)
├── frontend/                     # Next.js frontend
│   └── src/
│       ├── app/                  # Next.js routes
│       ├── components/           # UI components
│       └── core/                 # App logic (threads, tools, API, models)
├── skills/
│   ├── public/                   # Built-in skills (committed)
│   └── custom/                   # Custom skills (gitignored)
└── docker/                       # Docker Compose configs and nginx configs
```

**Dependency direction**: `app.*` may import `deerflow.*`; `deerflow.*` must never import `app.*`. Enforced by `backend/tests/test_harness_boundary.py` in CI.

**Nginx routing**:
- `/api/langgraph/*` → LangGraph (2024)
- `/api/*` → Gateway (8001)
- `/` → Frontend (3000)

## Configuration

- Copy `config.example.yaml` → `config.yaml` in project root (`make config` for first-time setup)
- Copy `extensions_config.example.json` → `extensions_config.json` for MCP/skills config
- API keys go in `.env` at project root (e.g., `OPENAI_API_KEY`, `TAVILY_API_KEY`)
- Config values starting with `$` are resolved as env vars (e.g., `api_key: $OPENAI_API_KEY`)
- `config.yaml` is hot-reloaded on mtime change — no restart needed for model/config edits
- Run `make config-upgrade` when `config_version` in `config.example.yaml` bumps

## Gotchas

- `make config` **aborts** if `config.yaml` already exists — use `make config-upgrade` for updates
- Frontend `pnpm build` requires `BETTER_AUTH_SECRET` env var; without it the build fails
- Do not use `pnpm check` — it is broken; use `pnpm lint && pnpm typecheck` instead
- Proxy env vars can silently break `pnpm install`; unset them if frontend install fails
- `make dev` emits shutdown noise when interrupted — this is expected; run `make stop` to clean up

## Pre-PR Checklist

```bash
cd backend && make lint && make test      # Always
cd frontend && pnpm lint && pnpm typecheck  # When touching frontend
BETTER_AUTH_SECRET=x pnpm build           # When changing env/auth/routing
```

CI runs `.github/workflows/backend-unit-tests.yml` on every PR: `uv sync --group dev` → `make lint` → `make test` in `backend/`.

## Plan Rules
- When you are asked to work on a requirement with a numbering format like # 2026-03-07-01, please read the corresponding section from `docs/plans/my_plan.md` and do not involve content from other sections.

## Some Preference Notes
- We prefer Log.info over System.out.println

## Language Notes
- Please use Simplified Chinese and English to communicate, write, and output.
- Japanese and Korea are forbidden to use.

## GitHub Instructions
- When committing, if the fix addresses a previously submitted issue, add a comment to the issue explaining the fix details.
- When committing the modifications accoring to the specific section in my_plan.md, includes the description in that section in the commit message.

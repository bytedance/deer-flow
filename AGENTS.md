# DeerFlow — Agent Instructions

## Monorepo at a Glance

```
deer-flow-latest/
├── backend/          # Python/uv — LangGraph-based agent harness + Gateway API
├── frontend/         # Next.js 16 — React 19, Tailwind CSS 4, pnpm
├── config.yaml       # Runtime config (loaded if present, falls back to config.example.yaml)
├── config.example.yaml
├── Makefile          # Root commands: setup, dev, start, stop, clean, config-upgrade
└── .pre-commit-config.yaml
```

**Runtime**: Gateway API (FastAPI, port 8001) → Nginx reverse proxy → Frontend (Next.js, port 3000).
Backend is a LangGraph-based "super agent" with subagents, memory, skills, and sandbox execution.

## Quick Commands

### Setup
```bash
# Backend
cd backend && uv sync

# Frontend
cd frontend && pnpm install

# Both (from root)
make setup
```

### Development
```bash
# Backend gateway (port 8001)
cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001

# Frontend dev server
cd frontend && pnpm dev

# Both (from root)
make dev
```

### Tests & Linting
```bash
# Backend
cd backend && uv run pytest
cd backend && uvx ruff check .   # lint
cd backend && uvx ruff format .  # format

# Frontend
cd frontend && pnpm test         # Vitest (unit)
cd frontend && pnpm test:e2e     # Playwright (Chromium)
cd frontend && pnpm format       # Prettier format check
cd frontend && pnpm lint:fix     # ESLint fix
cd frontend && pnpm typecheck    # TypeScript check
```

## Backend (`backend/`)

- **Language**: Python ≥3.12, managed with [uv](https://github.com/astral-sh/uv)
- **Workspace**: `uv workspace` with `packages/harness` member
- **Runtime**: `PYTHONPATH=. uv run uvicorn app.gateway.app:app`
- **Key deps**: fastapi, httpx, sse-starlette, uvicorn, langchain, langgraph-sdk, markdown-to-mrkdwn
- **Channel integrations**: Lark (`lark-oapi`), Slack (`slack-sdk`), Telegram (`python-telegram-bot`), WeCom (`wecom-aibot-python-sdk`), DingTalk (`dingtalk-stream`)
- **Auth**: bcrypt, pyjwt, email-validator
- **Test markers**: `@pytest.mark.integration`, `@pytest.mark.asyncio`

See `backend/AGENTS.md` → `backend/CLAUDE.md` for architecture (LangGraph runtime, Gateway, subagents, memory, sandbox).

## Frontend (`frontend/`)

- **Framework**: Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4
- **Package manager**: pnpm
- **UI**: shadcn/ui, MagicUI, React Bits
- **State**: TanStack Query
- **Agent SDK**: `@langchain/langgraph-sdk`, `@langchain/core`
- **Testing**: Vitest (unit, mirrors `src/`), Playwright (E2E, mocked backend)
- **File structure**: `src/app/` (routes), `src/core/` (business logic), `src/components/` (UI), `src/hooks/`, `src/lib/`, `src/styles/`

See `frontend/AGENTS.md` for architecture and interaction ownership rules.

## CI/CD (`.github/workflows/`)

| Workflow | Purpose |
|---|---|
| `lint-check.yml` | Ruff (backend) + ESLint/TypeScript (frontend) |
| `backend-unit-tests.yml` | Backend pytest suite |
| `frontend-unit-tests.yml` | Frontend Vitest suite |
| `e2e-tests.yml` | Playwright E2E against mocked backend |

## Config

- `config.yaml` — active config (git-ignored via `.gitignore`)
- `config.example.yaml` — reference schema (committed)
- Config supports env var interpolation and version management
- Run `make config-upgrade` to migrate between config schema versions

## Tips for Subagents

- Use `backend/AGENTS.md` and `frontend/AGENTS.md` as entry points for deeper guidance
- Backend architecture details are in `backend/CLAUDE.md` (LangGraph runtime, Gateway API, subagents, memory, sandbox)
- Frontend has detailed architecture docs in `frontend/AGENTS.md`
- Always run linters/tests after changes: `make dev` + backend `uvx ruff` + frontend `pnpm check` + `pnpm test`

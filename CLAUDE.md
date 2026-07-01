# CLAUDE.md — DeerFlow

DeerFlow is a LangGraph-based AI super agent harness: Python 3.12 backend (LangGraph + FastAPI), Next.js 16 frontend (React 19 + TypeScript), pnpm, nginx reverse proxy. Local dev at http://localhost:2026.

## Index

1. [Architecture](#1-architecture)
2. [Backend split (harness / app)](#2-backend-split-harness--app)
3. [Runtime modes](#3-runtime-modes)
4. [Sandbox virtual paths](#4-sandbox-virtual-paths)
5. [Project lock-decisions](#5-project-lock-decisions)
6. [Change Delivery Gate](#6-change-delivery-gate)

> **Out of scope here — read by pointer, not duplicated:**
> - Commands & project layout → [`docx/dev-setup.md`](docx/dev-setup.md)
> - General Claude Code behavior → superpowers skills (`brainstorming`, `TDD`, `systematic-debugging`, `verification-before-completion`, `dispatching-parallel-agents`, `writing-plans`, `executing-plans`, `requesting-code-review`)
> - Project-specific memory → `.claude/projects/.../memory/MEMORY.md`

## 1. Architecture

```
        Nginx (:2026)
         │      │
/api/langgraph/*  │      │ /api/*
         ▼      ▼
  LangGraph (:2024)  Gateway API (:8001)
  Lead Agent          FastAPI REST:
  Middlewares (18)    models, mcp, skills,
  Tools               memory, uploads,
  Subagents           threads, artifacts
         ▲
         │ SSE
         │
      Frontend (:3000)
```

Lead agent has 18 middlewares in strict order. The current list is at `backend/packages/harness/deerflow/agents/middlewares/` plus runtime registration. **Code is the source of truth — CLAUDE.md does not duplicate the list.**

## 2. Backend split (harness / app)

Strict import boundary, CI-enforced by `tests/test_harness_boundary.py`:

| Package | Prefix | Contents |
|---|---|---|
| `backend/packages/harness/deerflow/` | `deerflow.*` | Publishable `deerflow-harness`. Agents, sandbox, tools, models, MCP, skills, config. |
| `backend/app/` | `app.*` | Unpublished. FastAPI Gateway and IM channel integrations. |

`app.*` may import `deerflow.*`. **`deerflow.*` MUST NOT import `app.*`.**

## 3. Runtime modes

- **Standard** (`make dev`): LangGraph :2024 + Gateway :8001 + Frontend :3000 + nginx :2026. Nginx routes `/api/langgraph/*` → LangGraph, `/api/*` → Gateway.
- **Gateway** (`make dev-pro`, experimental): agent runtime embedded in Gateway via `RunManager` + `run_agent()` + `StreamBridge`. Concurrency via async tasks. Nginx → Gateway only.

## 4. Sandbox virtual paths

- `/mnt/user-data/{workspace,uploads,outputs}` → physical `backend/.deer-flow/threads/{thread_id}/user-data/...`
- `/mnt/skills` → `deer-flow/skills/`

Translation helpers: `replace_virtual_path()` / `replace_virtual_paths_in_command()` in sandbox tools. (ai-report-specific `/mnt/ai-report-data/` paths were archived 2026-07-01.)

## 5. Project lock-decisions

Hard non-negotiable rules. Don't drift.

- **ai-report archived** (2026-07-01). Do not reopen unless an executable E2E passes on a real fixture. See memory `ai-report-archived-lesson`.
- **chatbi-report is the active report skill**. sqlbot-report is retired. See memory `chatbi-report-replaces-sqlbot-report`.
- **Cross-cutting constraints extracted at boundaries first** (precision, security, locale, audit, threading). Build the boundary handler + unit test BEFORE feature code. See memory `cross-cutting-constraint-boundary-discipline`.
- **Middleware order is runtime-registered**. CLAUDE.md does not duplicate the list.
- **Local-only trust**: 127.0.0.1 loopback default. LAN / public deployment requires IP allowlist + auth gateway. See `CONTRIBUTING.md`.

## 6. Change Delivery Gate

Before claiming "完成" / "通过" / "ready to merge":

1. **Evidence first**. Verification actually ran. If a key check can't run, say why — don't skip silently.
2. **Quality gate cleared** (review / verification pass).
3. **Command output is real**, not invented.
4. **Without evidence** → answer is "未跑通" or "待验证", never "should work".

Process discipline (brainstorm → spec → TDD → verify → review) is in superpowers skills. CLAUDE.md only states the **delivery gate** because it's a project-specific cap on what "done" means.

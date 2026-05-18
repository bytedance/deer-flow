# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeerFlow Frontend is a Next.js 16 web interface for an AI agent system. It communicates with a LangGraph-based backend to provide thread-based AI conversations with streaming responses, artifacts, and a skills/tools system.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2

## Commands

| Command          | Purpose                                           |
| ---------------- | ------------------------------------------------- |
| `pnpm dev`       | Dev server with Turbopack (http://localhost:3000) |
| `pnpm build`     | Production build                                  |
| `pnpm check`     | Lint + type check (run before committing)         |
| `pnpm lint`      | ESLint only                                       |
| `pnpm lint:fix`  | ESLint with auto-fix                              |
| `pnpm test`      | Run unit tests with Vitest                        |
| `pnpm test:e2e`  | Run E2E tests with Playwright (Chromium)          |
| `pnpm typecheck` | TypeScript type check (`tsc --noEmit`)            |
| `pnpm start`     | Start production server                           |

Unit tests live under `tests/unit/` and mirror the `src/` layout (e.g., `tests/unit/core/api/stream-mode.test.ts` tests `src/core/api/stream-mode.ts`). Powered by Vitest; import source modules via the `@/` path alias.

E2E tests live under `tests/e2e/` and use Playwright with Chromium. They mock all backend APIs via `page.route()` network interception and test real page interactions (navigation, chat input, streaming responses). Config: `playwright.config.ts`.

## Architecture

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code) and **todos**.

### Source Layout (`src/`)

- **`app/`** — Next.js App Router. Routes: `/` (landing), `/workspace/chats/[thread_id]` (chat), `/workspace/agents/[agent_name]/chats/[thread_id]` (agent chat), `/workspace/report-templates` + `/workspace/report-templates/[template_id]` (template management), `/workspace/report-runs` + `/workspace/report-runs/[run_id]` (report history).
- **`components/`** — React components split into:
  - `ui/` — Shadcn UI primitives (auto-generated, ESLint-ignored)
  - `ai-elements/` — Vercel AI SDK elements (auto-generated, ESLint-ignored)
  - `workspace/` — Chat page components (messages, artifacts, settings)
  - `landing/` — Landing page sections
- **`core/`** — Business logic, the heart of the app:
  - `threads/` — Thread creation, streaming, state management (hooks + types)
  - `api/` — LangGraph client singleton
  - `artifacts/` — Artifact loading and caching
  - `i18n/` — Internationalization (en-US, zh-CN)
  - `settings/` — User preferences in localStorage
  - `memory/` — Persistent user memory system
  - `skills/` — Skills installation and management
  - `messages/` — Message processing and transformation
  - `genui/` — Dynamic UI block store, history recovery, and render_ui component helpers
  - `mcp/` — Model Context Protocol integration
  - `models/` — TypeScript types and data models
  - `report-templates/` — Report Template Platform: TanStack Query hooks (`useReportTemplates`, `useReportTemplate`, `useReportTemplateVersion`, `usePublishReportTemplate`, `useForkReportTemplate`, `useReportRuns`, `useReportRunPayload` …), REST client (`api.ts`), and shared types (`types.ts`). See [docs/plans/2026-05-14-ai-report-custom-template-design.md](../docs/plans/2026-05-14-ai-report-custom-template-design.md) for the backend contract.
- **`hooks/`** — Shared React hooks
- **`lib/`** — Utilities (`cn()` from clsx + tailwind-merge)
- **`server/`** — Server-side code (better-auth, not yet active)
- **`styles/`** — Global CSS with Tailwind v4 `@import` syntax and CSS variables for theming

### Data Flow

1. User input → thread hooks (`core/threads/hooks.ts`) → LangGraph SDK streaming
2. Stream events update thread state (messages, artifacts, todos)
3. TanStack Query manages server state; localStorage stores user settings
4. Components subscribe to thread state and render updates

### Key Patterns

- **Server Components by default**, `"use client"` only for interactive components
- **Thread hooks** (`useThreadStream`, `useSubmitThread`, `useThreads`) are the primary API interface
- **LangGraph client** is a singleton obtained via `getAPIClient()` in `core/api/`
- **Environment validation** uses `@t3-oss/env-nextjs` with Zod schemas (`src/env.js`). Skip with `SKIP_ENV_VALIDATION=1`

## Code Style

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

## Environment

Backend API URLs are optional; an nginx proxy is used by default:

```
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:2024
```

Requires Node.js 22+ and pnpm 10.26.2+.

## Report Template Platform

Frontend surface for the AI Report Custom Template platform (backend design: [docs/plans/2026-05-14-ai-report-custom-template-design.md](../docs/plans/2026-05-14-ai-report-custom-template-design.md)).

**Routes** (App Router, all under `/workspace`):

| Path                              | Purpose                                                                                          |
| --------------------------------- | ------------------------------------------------------------------------------------------------ |
| `report-templates/`               | List view, filterable by `visibility` (private / tenant / builtin)                               |
| `report-templates/[template_id]/` | Detail: metadata, version list, YAML viewer, fork / publish / archive actions                    |
| `report-runs/`                    | Report history embedded in the workspace sidebar — runs across the user's threads                |
| `report-runs/[run_id]/`           | Run detail: parameters, sections (GenUI re-render), artifact download links                      |

Sidebar entry points live in [src/components/workspace/workspace-nav-chat-list.tsx](src/components/workspace/workspace-nav-chat-list.tsx) — the design's "report history embedded in chat history" decision is implemented as additional sidebar items (not a separate global nav).

**Components** (under [src/components/workspace/report-templates/](src/components/workspace/report-templates/)):

- `report-templates-page.tsx` — list page (filter, search, create-from-fork)
- `report-template-detail-page.tsx` — metadata + version selector + YAML viewer + actions
- `report-runs-page.tsx` — history list with status badges
- `report-run-detail-page.tsx` — re-renders `report_payload.json` via GenUI primitives + artifact links

**State + API**: [src/core/report-templates/](src/core/report-templates/) wraps the 11 REST endpoints. All hooks are TanStack Query mutations / queries keyed by `template_id` / `report_run_id`; cache invalidation on publish / archive / fork follows the standard pattern.

**Form rendering during a run**: report runs happen inside an existing thread/run. The backend pushes GenUI `form` blocks (one per `form_step`) via the standard SSE stream — the frontend reuses the existing [FormBlock.tsx](src/components/genui/FormBlock.tsx) and `render_ui` interaction infrastructure. There is **no separate form runtime** on the frontend.

**Artifacts**: report exports (`report.md`, optional `report.pdf`) are downloaded through the existing `/api/threads/{thread_id}/artifacts/...` route. Markdown is always available; PDF may be absent when the backend's `weasyprint` is unavailable — the UI should hide the PDF button gracefully when `artifact_paths.pdf` is null.

## Design System

The daily report feature follows the visual and interaction design spec at
[docs/plans/2026-05-16-daily-report-visual-and-interaction-design.md](../docs/plans/2026-05-16-daily-report-visual-and-interaction-design.md).
All font choices, colors, spacing, component states, and interaction flows for the daily report
are defined there. Do not deviate without explicit user approval.

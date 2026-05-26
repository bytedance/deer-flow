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

### Template Marketplace & Visual Editor

The platform includes a visual template editor, marketplace for discovering/installing templates, and blueprint system for quick template creation.

**Additional Routes** (App Router, all under `/workspace`):

| Path                                           | Purpose                                                                                   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `report-templates/editor/[id]/`                | Visual template editor with drag-and-drop form steps, data steps, sections                |
| `report-templates/new/`                        | Blueprint catalog — choose pre-configured templates to create from                        |
| `template-marketplace/`                        | Marketplace listing — search, filter, browse available templates                          |
| `template-marketplace/[id]/`                   | Marketplace detail — view description, reviews, install template                          |

**Marketplace Components** (under [src/components/workspace/marketplace/](src/components/workspace/marketplace/)):

- `marketplace-page.tsx` — grid layout with search, category filter, sort controls
- `marketplace-detail-page.tsx` — detail view with tabs (description, reviews), install panel

**Editor Components** (under [src/components/workspace/report-templates/editor/](src/components/workspace/report-templates/editor/)):

- `template-editor-page.tsx` — main editor layout (palette, canvas, property panel, YAML toggle)
- `editor-palette.tsx` — drag-and-drop source for form fields, sections, data pipeline components
- `form-steps-panel.tsx` — sortable form step list with @dnd-kit, automatic `next` chain update
- `sections-panel.tsx` — sortable sections with inline editing
- `data-steps-panel.tsx` — data steps and transforms editors
- `editor-property-panel.tsx` — template metadata editing
- `yaml-editor.tsx` — textarea-based YAML editor with line numbers
- `validation-panel.tsx` — auto-validates on DSL change with 1s debounce
- `editor-actions-dialog.tsx` — publish to marketplace and export dialogs

**Blueprint Components** (under [src/components/workspace/blueprints/](src/components/workspace/blueprints/)):

- `blueprint-catalog-page.tsx` — grid of blueprint cards with category icons, create dialog

**State + API**:

- [src/core/marketplace/](src/core/marketplace/) — marketplace listings, reviews, install operations (TanStack Query hooks)
- [src/core/blueprints/](src/core/blueprints/) — blueprint catalog and template creation from blueprints
- [src/core/report-templates/use-template-dsl.ts](src/core/report-templates/use-template-dsl.ts) — DSL state management hook with YAML bidirectional sync, uses js-yaml for serialization

**Key Patterns**:

- **DSL compatibility**: Editor output must be 100% compatible with DSL v1 schema. The `useTemplateDSL` hook maintains in-memory DSL object as single source of truth.
- **Drag-and-drop**: Implemented with @dnd-kit/core + @dnd-kit/sortable. Form step reorder automatically updates the `next` chain.
- **YAML bidirectional editing**: js-yaml handles serialization (DSL→YAML) and deserialization (YAML→DSL).
- **Real-time validation**: Debounced 1s calls to `POST /api/report-templates/{id}/validate`.
- **Marketplace operations**: TanStack Query mutations with proper cache invalidation.
- **Package format**: `.template` ZIP archive containing template.yaml, metadata.json, blueprint.json, README.md.
- **Marketplace source tracking**: Templates installed from marketplace include `marketplace_source` field with listing_id, display_name, source_version. UI shows badge with link to marketplace listing and "Update available" indicator when upstream has newer version.

**Backend API Endpoints**:

- `GET /api/template-blueprints/` — list available blueprints
- `GET /api/template-blueprints/{id}` — get blueprint definition
- `POST /api/template-blueprints/{id}/create-template` — create template from blueprint
- `GET /api/template-marketplace/` — paginated listing with search/filter/sort
- `GET /api/template-marketplace/{id}` — detail with reviews
- `POST /api/template-marketplace/{id}/reviews` — submit rating and review
- `POST /api/template-marketplace/{id}/install` — install template to private/tenant space
- `POST /api/report-templates/{id}/publish-to-marketplace` — create marketplace listing
- `GET /api/report-templates/{id}/export` — download .template package
- `POST /api/report-templates/import` — upload and import .template package

## Design System

The daily report feature follows the visual and interaction design spec at
[docs/plans/2026-05-16-daily-report-visual-and-interaction-design.md](../docs/plans/2026-05-16-daily-report-visual-and-interaction-design.md).
All font choices, colors, spacing, component states, and interaction flows for the daily report
are defined there. Do not deviate without explicit user approval.

## Document Upload Error Codes (Sprint C.1.3)

Document conversion failures (PDF/DOCX/PPTX/XLSX → Markdown) come back from the gateway as a `422` with body `{code, message, filename}`. The frontend keys off the stable `code` enum so toast text is localised on this side — the server's `message` is English-only, intended for logs.

**Source of truth**: [src/core/uploads/conversion-errors.ts](src/core/uploads/conversion-errors.ts).

- `ConversionError` — typed error subclass thrown by `uploadFiles` ([core/uploads/api.ts](src/core/uploads/api.ts)) and `uploadDocument` ([core/knowledge-base/api.ts](src/core/knowledge-base/api.ts)).
- `conversionErrorToastText(code, locale, filename?)` — code → bilingual toast string.

**Codes**: `EMPTY_RESULT`, `ENCRYPTED_PDF`, `UNSUPPORTED_FORMAT`, `MARKITDOWN_UNAVAILABLE`, `INTERNAL_ERROR`. Adding a new code requires touching both [conversion-errors.ts](src/core/uploads/conversion-errors.ts) and the matching backend enum in `packages/harness/deerflow/utils/file_conversion.py:ConversionErrorCode`. Tests in [tests/unit/core/uploads/conversion-errors.test.ts](tests/unit/core/uploads/conversion-errors.test.ts) fail loudly when the table drifts.

**Calling pattern** (any component triggering an upload):

```ts
import { ConversionError, conversionErrorToastText } from "@/core/uploads";

try {
  await uploadDocument(kbId, file);
} catch (err) {
  if (err instanceof ConversionError) {
    toast.error(conversionErrorToastText(err.code, locale, err.filename));
    return;
  }
  toast.error((err as Error).message);
}
```

Non-conversion 4xx/5xx still throw a plain `Error` with the server's `detail` string — surface it as-is.

## Knowledge Base Selector Cleanup Invariants (Sprint C.2.1)

[knowledge-base-selector.tsx](src/components/workspace/knowledge-base-selector.tsx) drops `selected_ids` that no longer correspond to any visible KB. The cleanup effect:

- Re-runs whenever the **set of visible KB IDs** changes (computed via the pure `knowledgeBaseIdSignature` helper, exported under `__test_only`). A fresh array reference with identical IDs is a no-op — important because TanStack Query returns a new reference on every poll.
- Skips the `onSelectionChange` call when `cleanSelection(...)` returns the input by reference. This prevents the live-loop the previous `hasCleaned` ref was working around.
- Forces `enabled=false` when every selected ID disappears, so the next chat turn doesn't try to retrieve from an empty set and silently produce zero results.

Parents passing `onSelectionChange` should still wrap it in `useCallback`, but the selector keeps a ref to the latest callback so an unstable identity won't refire cleanup.

## Device Selector Filter Invariant

Both [DeviceSelectorBlock.tsx](src/components/genui/DeviceSelectorBlock.tsx) and [DeviceSelectorMultiBlock.tsx](src/components/genui/DeviceSelectorMultiBlock.tsx) share a single source of truth for filtering the org-tree response: [device-selector-utils.ts](src/components/genui/device-selector-utils.ts) exports `collectDevices(node, filterDeviceType?)`.

Invariants — locked by [tests/unit/components/genui/device-selector-utils.test.ts](tests/unit/components/genui/device-selector-utils.test.ts):

- **Devices vs org levels**: `type < 10` is a device; `type >= 10` is an org level. Only devices are returned.
- **Strict equality filter**: when `filterDeviceType` is set, a child is included **only if `child.type === filterDeviceType`** — never approximate, never via parent's type. This is the frontend's defense against ins-bus-rpc returning a mixed tree when the caller asked for one type.
- **No recursion into devices**: the walker descends into org children only. Measurement points / sub-components hanging off a device must not be hoisted into the device list (the previous code did this and would surface point nodes alongside parent devices).
- **Stable ordering**: results sorted by `displayOrder` ascending.

This came from a bug where selecting "静设备 (6)" in the daily report rendered 旋转机组 (1) entries in the device list — the agent's SOUL.md example hard-coded `typeId: 4` (pump) and LLMs sometimes copied it verbatim instead of applying the mapping table. Fix: (1) [device-selector-utils.ts](src/components/genui/device-selector-utils.ts) provides a single `collectDevices` shared by both selector components; (2) SOUL.md now uses a valid JSON example (typeId=1) with a prominent per-type mapping list right after the code block, plus a "do NOT copy the number" warning.

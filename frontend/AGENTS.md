# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with the DeerFlow frontend. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

## Project Overview

DeerFlow Frontend is a Next.js 16 web interface for an AI agent system. It communicates with a LangGraph-based backend to provide thread-based AI conversations with streaming responses, artifacts, and a skills/tools system.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2. Requires Node.js 22+ and pnpm 10.26.2+.

### Core dependencies

- **LangGraph SDK** (`@langchain/langgraph-sdk` ^1.5.3) — Agent orchestration and streaming
- **LangChain Core** (`@langchain/core` ^1.1.15) — Fundamental AI building blocks
- **TanStack Query** (`@tanstack/react-query` ^5.90.17) — Server state management
- **UI**: Shadcn UI, MagicUI, React Bits, and Vercel AI SDK elements (generated from registries — see Code Style)

## Commands

| Command          | Purpose                                       |
| ---------------- | --------------------------------------------- |
| `pnpm dev`       | Start the development server with Webpack     |
| `pnpm build`     | Production build                              |
| `pnpm check`     | Lint + type check (run before committing)     |
| `pnpm lint`      | ESLint only                                   |
| `pnpm lint:fix`  | ESLint with auto-fix                          |
| `pnpm format`    | Prettier check (`pnpm format:write` to apply) |
| `pnpm test`      | Run unit tests with Rstest                    |
| `pnpm test:e2e`  | Run E2E tests with Playwright (Chromium)      |
| `pnpm typecheck` | TypeScript type check (`tsc --noEmit`)        |
| `pnpm start`     | Start production server                       |

Unit tests live under `tests/unit/` and mirror the `src/` layout (e.g., `tests/unit/core/api/stream-mode.test.ts` tests `src/core/api/stream-mode.ts`). Powered by Rstest; import source modules via the `@/` path alias.

Webpack is the default development bundler. Use `DEER_FLOW_DEV_BUNDLER=turbo` with `pnpm dev` to opt in to Turbopack when diagnosing a local Next.js bundler issue.

Rstest runs them as two projects (`rstest.config.ts`). `*.test.ts` / `*.test.tsx` run in a plain **node** environment — that is nearly the whole suite, and it is the default for anything that is pure logic. `*.dom.test.ts` / `*.dom.test.tsx` run in **happy-dom**, for tests that need a document: hooks driven through `renderHook` from `@testing-library/react`, and components. Keep the split — a DOM environment costs roughly 3x the runtime of the node suite, so tests that do not render should not opt into it. A hook whose behavior only exists under real React (effect ordering, cleanup on unmount, re-render on store change) belongs in a `.dom.test.*` file rather than a node test that mocks `react` itself.

E2E tests live under `tests/e2e/` and use Playwright with Chromium. They mock all backend APIs via `page.route()` network interception and test real page interactions (navigation, chat input, streaming responses). Config: `playwright.config.ts`.

## Architecture

Account settings include `AccountNicknameSettings`, keyed by authenticated user ID.
`core/auth/profile.ts` reads/patches the session-only `/api/v1/auth/profile` endpoint.
The `account-profile` query cache and drafts are owner-scoped; failed saves retain
the draft, and an empty nickname clears the preference. Tests: `account-nickname.dom`.

`/workspace/enterprise` (Enterprise connections) contains only WeCom group bindings
and Alibaba enterprise mail. Group messages and schedules are arranged in chat;
the page has no standalone message composer or delivery-history section.
`core/enterprise` owns API types and localized copy. Query keys include user ID
and the editor remounts on account changes. Webhook drafts stay in memory and
clear after save/cancel; responses never contain secrets.
`mail-panel.tsx` independently checks `enterprise_mail` access, binds encrypted
AliMail credentials and displays read-only keyword previews with UIDVALIDITY
pagination. Secrets stay in component memory; mail bodies render as plain text.
AI organization creates a normal owned chat/run, passing only account ID and
filters; the tool fetches messages with fresh authorization. Preserve a link to
the created chat on ambiguous launch failure rather than auto-retrying. Schedules
use the existing Scheduled tasks page. Tests: enterprise/mail unit and browser E2E.

`mail-outbox.tsx` adds a separate compose permission check, plain-text draft preview
and explicit recipient/content confirmation inside the mail section. AI links
use `?mail_draft=<id>`; all query keys remain user-scoped. Sending submits only the
immutable draft ID and confirmation. Never automatically retry a POST; after a
lost response disable sending until a read-only status refresh. `sending` records
may be polled, but never resubmitted. Tests: mail-outbox.dom and enterprise-mail E2E.

`/workspace/knowledge-base` sits immediately below Scheduled tasks in the sidebar.
`core/knowledge-base` owns its authenticated API client, user-scoped query keys,
document polling and feature-local English/Chinese copy. The Gateway supplies
`can_upload`/`can_create`; UI controls are not an authorization boundary. Upload
files sequentially and lock dataset selection during mutations. Display upload
and parse-start outcomes independently so a failed parse never causes an automatic
duplicate upload. Parse retries operate on the existing document ID. Document
lists use explicit pagination and poll every 3 seconds while parsing (15 seconds
otherwise), stopping on errors or background tabs. UI and API tests live in
`tests/unit/{components/workspace,core/knowledge-base}`.

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, set thread-scoped `/goal` completion conditions, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code), **todos**, and goal state updates.

### Source Layout (`src/`)

- **`app/`** — Next.js App Router. Routes include `/` (landing), `/showcase/[thread_id]` (allowlisted public read-only demos), `/workspace/chats/[thread_id]` (authenticated chat), `/workspace/agents/[agent_name]` and `/workspace/agents/new` (custom agents), `/artifacts/view` (chrome-free window that renders one markdown artifact with the panel's own renderer), `/blog/…`, the `(auth)/{login,setup,auth/callback}` flow, `/[lang]/docs/…`, and `/api/…` route handlers (e.g. `/api/memory`).
- **`components/`** — React components:
  - `ui/` — Shadcn UI primitives (auto-generated, ESLint-ignored)
  - `ai-elements/` — Vercel AI SDK elements (auto-generated, ESLint-ignored)
  - `workspace/` — Chat page components (messages, artifacts, settings)
  - `landing/` — Landing page sections
  - `docs/` — Docs / MDX rendering components
- **`core/`** — Business logic, the heart of the app. Domains include `threads/` (creation, streaming, state), `api/` (LangGraph client singleton), `agents/` (custom agents), `subagents/` (runtime worker catalog and administrator mutations), `auth/` (authentication), `artifacts/`, `channels/` (IM connections), `integrations/` (managed third-party integration status/install clients such as Lark CLI), `i18n/` (en-US, zh-CN), `settings/`, `memory/`, `skills/`, `messages/`, `mcp/`, `models/`, `input-polish/` (pre-send draft rewrite API), `voice-input/` (browser speech-recognition helpers), `suggestions/`, `tasks/`, `todos/`, `tools/`, `workspace-changes/` (run-scoped changed-file summaries and diff fetching), `config/`, `notification/`, `blog/`, plus rendering helpers (`rehype/`, `streamdown/`) and `utils/`.
- **`hooks/`** — Shared React hooks
- **`lib/`** — Utilities (`cn()` from clsx + tailwind-merge)
- **`content/`** — MDX content (blog posts, docs) rendered by the app
- **`styles/`** — Global CSS with Tailwind v4 `@import` syntax and CSS variables for theming
- **`typings/`** — Ambient TypeScript declarations
- Root files: `env.js` (env validation), `mdx-components.ts` (MDX component map)

More specific `AGENTS.md` files under `src/` contain the frontend sections split from this file.

## Code Style

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

## Environment

### DDFW-Agent deployment branding

The root `/` route redirects server-side to `/login`; it no longer renders the
marketing landing page. The existing auth layout sends authenticated users to
`/workspace`, while anonymous users see the combined login/registration page.
Keep entry redirects temporary and preserve the existing setup/auth checks.
`tests/e2e/landing.spec.ts` covers the root redirect and authenticated continuation.

The Tools settings page also mounts `UserToolSecurityPanel`. Its session-only
`/api/user-security` APIs expose only credential status, never saved values.
Personal credential drafts live only in component memory and clear on success;
do not persist them in localStorage, query keys or analytics. Administrators
select a registered user's email before changing exact resource grants. The
backend catalog excludes bundled tools/Skills and sandbox execution, which are
available by default. Display added tool/MCP/skill resources only; optional
labels are presentation, exact targets are request identities. Personal overrides
use the target-user catalog returned by `/grants`, including owned custom Skills. Keep
the selected account separate from the editable email field so a draft edit
cannot redirect a permission mutation. The backend remains the permission
boundary. `user-tool-security.dom.test.tsx` covers these interactions.

The admin-only `UserGroupSecurityPanel` owns group CRUD, memberships and exact
group grants. Group queries include the signed-in user ID; membership/grant
mutations invalidate group details, group lists, user grant details and personal
tool status. Key the editor by selected group ID and lock selection during writes.
Personal exceptions use inherit/allow/deny, with a separate effective permission
label and inherited memberships. The backend applies deny precedence; do not
derive effective access from the select value alone. Group membership never
changes the personal credential form or sandbox identity.

The application UI uses the DDFW-Agent name in authentication, navigation, landing,
welcome, and notification copy in both locales. `public/images/ddfw.svg` is the
wordmark mask; `public/favicon.svg` and the matching ICO are the browser icons.
Keep expanded and collapsed sidebar branding consistent. Internal API paths,
storage keys, package names, and upstream license/acknowledgment sources retain
their original identifiers.

The workspace Settings and more menu exposes Settings only. About is excluded
from the settings section type, navigation, lazy content, and `?settings=`
deep-link allowlist; the workspace header has no upstream repository shortcut.
Custom-agent availability still comes from `/api/features` and the deployment's
`config.yaml -> agents_api.enabled`, not from a frontend hardcoded override.
`tests/unit/components/workspace/enterprise-shell.dom.test.tsx` covers this UI
contract, including the mobile-compatible sidebar states and old About links.

Backend API URLs are optional; an nginx proxy is used by default:

```
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:8001/api
```

Leave these unset for the standard `make dev` / Docker flow, where nginx serves the public `/api/langgraph/*` prefix and rewrites it to Gateway's native `/api/*` routes.

To reach a dev server on anything other than localhost — a LAN address, or a proxied hostname — list the host in `DEER_FLOW_DEV_ALLOWED_ORIGINS` (comma-separated; a full URL is reduced to its host). It feeds Next's `allowedDevOrigins`, which gates `/_next/*`, fonts, and HMR. Without it those requests get a 403 and the page renders server-side but never hydrates, so nothing on it — including the login form — responds. Development only; production builds ignore it.

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Core Concepts](https://js.langchain.com/docs/concepts)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [Next.js App Router](https://nextjs.org/docs/app)

## Contributing

When adding features:

1. Follow the established `src/` structure
2. Add TypeScript types and proper error handling
3. Write unit tests under `tests/unit/` (`pnpm test`) and E2E tests under `tests/e2e/` (`pnpm test:e2e`)
4. Run `pnpm check` before committing
5. Update this `AGENTS.md` when architecture, commands, or conventions change

Route asset budgets are enforced with `pnpm perf:check`. The command measures
`/login` from a normal production build, then builds in static-demo mode for the
fixture-backed workspace routes. It starts the production server on temporary local
ports, measures the unique JavaScript and CSS files referenced by representative
routes, writes the detailed result to `.next/performance-results.json`, and compares
totals with `performance-budgets.json`. Fix route ownership or split points when a
budget fails; do not raise a ceiling without documenting and reviewing the measured
regression.

Chat archive is a thread metadata flag (`deerflow_archived === true`), independent
of run status. Sidebar and Chats explicitly request the Gateway's optional
`archived` filter through `searchThreadsByArchive`; the SDK drops this extension,
so use the authenticated REST fetcher. Static demos retain SDK fixture queries.
`core/threads/archive.ts` waits for the write, cancels stale reads, merges only the
owned flag into metadata snapshots, then restarts metadata reads and resets list
pagination. Keep both default and Custom Agent header restore controls in sync.
Pin/archive responses must not merge unrelated metadata flags: out-of-order
organization requests can otherwise roll back each other's confirmed state.
Run-created optimistic snapshots have no archive flag: refresh archive-filtered
lists from the server instead of inserting those snapshots into either view.

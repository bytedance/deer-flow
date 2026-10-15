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

`pnpm-workspace.yaml` overrides vulnerable `@xmldom/xmldom` 0.9.x releases to
0.9.12 for GHSA-965w-775f-mr7g. Nextra pulls it in through MathJax and
`speech-rule-engine@4.1.2`, which pins 0.9.8. Keep the override until the
upstream dependency chain resolves a patched version without it; regenerate
`pnpm-lock.yaml` and verify the docs build when changing this constraint.

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

On Windows `pnpm dev` binds `127.0.0.1` by default because Hyper-V/winnat excluded port ranges can reject Next's default `0.0.0.0` bind with `EACCES` (#2870). Pass `pnpm dev -- --hostname 0.0.0.0` to listen on a LAN interface instead.

Rstest runs them as two projects (`rstest.config.ts`). `*.test.ts` / `*.test.tsx` run in a plain **node** environment — that is nearly the whole suite, and it is the default for anything that is pure logic. `*.dom.test.ts` / `*.dom.test.tsx` run in **happy-dom**, for tests that need a document: hooks driven through `renderHook` from `@testing-library/react`, and components. Keep the split — a DOM environment costs roughly 3x the runtime of the node suite, so tests that do not render should not opt into it. A hook whose behavior only exists under real React (effect ordering, cleanup on unmount, re-render on store change) belongs in a `.dom.test.*` file rather than a node test that mocks `react` itself.

E2E tests live under `tests/e2e/` and use Playwright with Chromium. They mock all backend APIs via `page.route()` network interception and test real page interactions (navigation, chat input, streaming responses). Config: `playwright.config.ts`. The real-backend auth contract in `tests/e2e-real-backend/auth-disabled-contract.spec.ts` and `backend/tests/test_auth_me_permissions.py` pin the complete route-permission list; update both when adding registered permissions (including `projects:read/write/delete`).

The dedicated `run-history.ts` hook replaces the unpaged runs hook. Show counts
only after a successful history read, never during initial loading or errors.
Scheduled run history uses task/page query keys and the existing live offset API.
Fetch 51 rows to display 50 plus a next-page sentinel; never append pages. Only
page zero polls or refreshes on focus/reconnect. Task switches reset to page zero,
and consumed AbortSignals cancel obsolete reads. Live offsets are not snapshots;
explicit mutations or navigation may observe newly inserted runs.
Run status `unmet` identifies a finished occurrence whose scheduled goal was not satisfied; keep it distinct from execution failure.
`core/scheduled-tasks/goal-outcome.ts` maps goal verdicts and host reason codes for run history; show known codes as localized labels; unknown codes, raw run errors and the evaluator's reason stay behind the run row's Details. Check-failure codes are "unchecked", not a miss. `contracts/scheduled_goal_notes_contract.json` pins the host strings it and `run-error.ts` match.
Scheduled-task views read state through the pure `core/scheduled-tasks` helpers (`status.ts`, `actions.ts`, `format.ts`, `describeTaskSchedule`, `errors.ts`) so list, detail and chat card agree. "Is a run active?" is `status === "running"` or `active_run_status` (a recurring task stays `enabled` while it runs). Default views show no IDs, ISO times, cron strings or enum names; errors localize by `detail.code` (`contracts/scheduled_task_errors_contract.json`) with raw text only behind Details. `tests/e2e/utils/readable.ts` and `tests/unit/helpers/readable.ts` assert this.
The tasks page (`app/workspace/scheduled-tasks/page.tsx`) only composes `components/workspace/scheduled-tasks/*`: list with status tabs, detail (Runs / Stops when / goal / Does / notes / History), outcome notice, create/edit/duplicate dialog (PATCH sends only changed fields, `null` clears) and the renew dialog that a `limits_exhausted` Resume opens. `?task_id=` selects a task; `?thread_id=` scopes the list to one chat.
In chat, a `schedule_task` result becomes an `assistant:scheduled-task` group (`core/scheduled-tasks/tool-result.ts`, last card per task per turn; not a turn boundary) rendered by `ScheduledTaskCard`, which polls the task only while on screen. A human message with `additional_kwargs.deerflow_scheduled_origin` stays a `human` group with `scheduledOrigin`: `ScheduledRunPrompt` renders the origin's user-language parts, never the launched text, and it is not editable.
Server-created threads: `core/threads/origin.ts` reads `metadata.deerflow_origin` (`contracts/thread_origin_contract.json`), then `channel_source`, then a legacy `scheduled_task_id`; provider names come from `threads.origin.providers`. `core/threads/activity.ts` polls `/api/thread-activity` (mount `useThreadActivity` once; unmounting resets its cursor; first poll only seeds; invalidate lists only on server-origin threads, truncation or a higher `read_version`) and `useMarkThreadRead` posts reads. `core/scheduled-tasks/events.ts` loads a chat's lifecycle events, not gated on its task list; `placeTaskEvents` puts each at the end of its `after_run_id` turn. The UI language is saved as the `locale` preference once per session and on each switch, only when the Gateway's preferences include `locale`.
Thread rows (sidebar, `/workspace/chats`) show `ThreadOriginIcon` and, if `unread === true` and not the open thread, `ThreadUnreadDot` with `threads.unreadLabel` as row label. `WorkspaceSidebar` mounts `useThreadActivity`. Chat pages call `useMarkOpenThreadRead` once metadata loads (marks read on load, on an unread flip, on tab visible, and via its callback from `onFinish`).
Chat pages pass `useThreadScheduledTaskEvents` data to `MessageList` (`scheduledTaskEvents`; the custom-agent page also passes its agent for the run link), which renders `ScheduledTaskEventLine` through `VirtualMessageList.renderAfterGroup` at the `placeTaskEvents` position, inside the group's measured row. Lines are history: never gated on the task list. Channel provider cards (Settings and the sidebar list) render `ChannelScheduledUpdates` from `proactive_notifications`, and nothing when the field is absent.

## Architecture

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, set thread-scoped `/goal` completion conditions, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code), **todos**, and goal state updates.

### Source Layout (`src/`)

- **`app/`** — Next.js App Router. Routes include `/` (landing), `/showcase/[thread_id]` (allowlisted public read-only demos), `/workspace/chats/[thread_id]` (authenticated chat), `/workspace/agents/[agent_name]` and `/workspace/agents/new` (custom agents), `/artifacts/view` (chrome-free window that renders Markdown or CSV/TSV artifacts with the panel's own renderer), `/blog/…`, the `(auth)/{login,setup,auth/callback}` flow, `/[lang]/docs/…`, and `/api/…` route handlers (e.g. `/api/memory`).
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

`core/utils/markdown.ts` reads web-fetch titles from the first nonblank line.
Match zero to three literal spaces before `# ` without trimming indentation;
mixed space/tab code blocks must fall back to the URL. Strip optional closing
hashes with a backwards scan so long fetched titles cannot cause quadratic regex
backtracking. Closing hashes require a preceding space/tab (or an empty title)
and only ASCII spaces/tabs afterward, apart from the terminal CR in CRLF input.
Non-ASCII trailing whitespace must not turn literal hashes into closing syntax.
Keep this local to title extraction rather than changing the shared streamdown
fence parser.

Custom Agent `display_name` is an optional Unicode UI label, edited in
`AgentSettingsDialog`. Use it with a fallback to `name` for gallery/chat text;
keep `name` for React identity, URLs, requests, and runtime `agent_name`.
The 100-code-point budget uses `[...value.trim()].length`, matching Pydantic;
do not use HTML `maxLength`, which counts UTF-16 code units instead.

Custom Agent portability uses the versioned `deerflow.custom-agent` JSON
document through `core/agents/api.ts`. Keep file parsing client-side only for
previewing the proposed local name; the Gateway is authoritative for schema,
name, model, and conflict validation. Export downloads must never synthesize
runtime state from browser caches.

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

Scheduled-task list search filters the current authorized query result by title or
prompt, composing with status/type filters and thread scope. Selection must derive
from the filtered list so hidden tasks cannot remain actionable. Keep literal
matching in `core/scheduled-tasks/search.ts`; clearing search retains other filters.

Single-run schedule edits retain the mounted task's original `run_at` while its wall time and timezone match. The parent echoes edits through `initial`; retain a stable snapshot and reset the parent draft during render before remounting with a task key when switching tasks. Use the resolved timezone consistently for the snapshot and displayed wall time. Component and scheduled-task E2E tests cover DST folds and timestamp precision.

## Environment

Scheduled-task interval forms preserve the initial `every_seconds` on mount,
timezone changes, and untouched blur. The backend's configurable interval minimum
can be lower than the UI's default 60-second floor. Apply that UI floor only after
an explicit amount/unit edit so editing metadata or duplicating a task cannot
silently change its cadence. Component regressions live in
`tests/unit/components/workspace/scheduled-task-schedule-input.dom.test.tsx`.

Backend API URLs are optional; an nginx proxy is used by default:

```
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:8001/api
```

Leave these unset for the standard `make dev` / Docker flow, where nginx serves the public `/api/langgraph/*` prefix and rewrites it to Gateway's native `/api/*` routes.

`make build-static` creates a standalone read-only demo and copies `.next/static`
and `public` into the output. In static mode, `core/api/static-response.ts`
resolves Gateway REST reads with the bundled capability catalog and safe
installation projections from existing same-origin `/mock/api` fixtures; writes
and unknown API routes fail locally.
The homepage client counter calls `/github-stars`, outside the Gateway proxy.
That dynamic route reads the server-only `GITHUB_OAUTH_TOKEN` at runtime, caches
GitHub data for one hour, and returns 204 when the count is unavailable. Start
the standalone server from `frontend/` with `node --env-file=.env
.next/standalone/server.js` to load the current credentials.

To reach a dev server on anything other than localhost — a LAN address, or a proxied hostname — list the host in `DEER_FLOW_DEV_ALLOWED_ORIGINS` (comma-separated; a full URL is reduced to its host). It feeds Next's `allowedDevOrigins`, which gates `/_next/*`, fonts, and HMR. Without it those requests get a 403 and the page renders server-side but never hydrates, so nothing on it — including the login form — responds. Development only; production builds ignore it.

One-time schedule input uses `validZonedLocalToUtcIso` to reject wall times that
do not round-trip in the selected timezone. Invalid input emits an empty spec and
localized inline feedback; both create and edit must block submission. Keep this
UI validation separate from the API payload. Preserve the original instant when
wall time and timezone match the mounted snapshot; validate changed inputs, and
restore the exact original timestamp when those edits are reverted.

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

### Delimited artifact preview

CSV/TSV previews share `artifact-table-preview.tsx` between the panel and standalone viewer. Papa Parse runs only inside `delimited-preview.worker.ts`; `use-delimited-preview.ts` bounds input before transfer, cancels stale work, and enforces a five-second timeout. The parser detects the first record separator outside quoted fields and passes it explicitly to Papa Parse, so embedded newlines in an incomplete quoted field cannot corrupt newline detection. It retains at most 202 logical records and 50 columns, discarding an incomplete final record from truncated input. UI pagination displays at most 200 data rows in pages of 50. Keep the table mounted but inactive when switching to source so header/pagination state survives; changing file identity resets it. Pending `write_file` content stays in source mode until success.

For a truncated sample whose first separator is LF or CRLF, strip a terminal CR
before parsing so a split CRLF separator cannot make a quoted final field
invalidate the whole preview, including LF-first files with later CRLF records.
The terminal record remains incomplete and is discarded; complete CR-only files
and malformed quotes retain their existing behavior.

Custom skill export is admin-only and disabled in static demos. The lazy
`skill-export-dialog.tsx` must abort requests and ignore stale callbacks on close
or user/skill changes. `core/skills/export.ts` owns the revision-bound Blob download;
HTTP 409 requires explicit preview refresh. Keep file lists paginated and diagnostics
localized. Browser handoff does not prove the file was saved to disk.

Sidebar rows request deletion through `ThreadDeleteDialogProvider`, hosted in
`WorkspaceSidebar` outside the virtualized flat/project lists. Keep the selected
thread snapshot and retry UI alive when a partial deletion removes its row.
Focus Cancel on open and after a failed deletion has re-enabled the actions;
block dismissal while deletion is pending. Show the error message when available,
with a localized fallback, and log the rejection for debugging. The shared
delete helper accepts remote 404 (not 403) before retrying local cleanup, and
`onDeleted` runs only after both deletion steps succeed.

## Capability Center

`/workspace/capabilities` owns Plugins and Skills navigation. Plugins composes the
MCP manager and a lazily loaded Lark configuration dialog; installation, OAuth,
mutation permissions, and cache ownership remain in the existing hooks. Skill display names/summaries are presentation
metadata; runtime names and full descriptions remain unchanged. Public, custom,
integration, and legacy sources must stay distinct. Community currently offers
archive import, not a remote marketplace. Screenshot E2E fixtures are demo data.
`backend/packages/harness/deerflow/capabilities/builtin.json` owns localized
catalog manifests. Refresh the generated demo snapshot with `pnpm catalog:sync`
after changing the catalog; unit tests enforce equality with the source. Demo
business projections derive provider IDs from the catalog adapter metadata. The
sync script uses decoded filesystem paths for formatter configuration lookup.
`plugin-catalog.ts` only resolves localized text and explicit
installation metadata; never infer provider identity from server display names.
`plugin-directory.tsx` groups rows and applies search/category/installed filters.
`core/capabilities` consumes catalog and safe status projections; MCP secrets and
raw settings remain in the administrator-only editor. `plugin-adapters.tsx`
registers integration-specific settings flows once, independent of catalog size.
The `business` form uses manifest credential fields without asking for an MCP URL;
its backend adapter generates bundled DingTalk/WeCom notification or HubSpot CRM
connections. These also appear in MCP discovery, so deduplicate projections by
installation ID. Keep their labels as configuration, not package installation.
Keep installation, enabled state, configured credentials, and verified authorization
distinct. Agent `mcp_plugins` uses stable installation IDs; null means all, [] means
none. The settings dialog submits only selections changed from its opening
snapshot, preserving concurrent updates on unrelated saves and treating restored
selections as unchanged. It is runtime selection, not a replacement authorization policy. See
`docs/capability-center.md` for the complete contract and extension example.
`PluginIcon` is shared by recommendations, configured entries, and the editor;
brand assets and their provenance live in `public/images/plugins/`. Brand icons
require explicit catalog metadata; a custom server name never selects a brand.
Ambiguous installation IDs remain visible but cannot be selected for an Agent. The icon picker
accepts local PNG/JPEG/WebP up to 2 MiB, checks the signature, decodes and contains
the image in a 128px PNG, and stages changes until the existing targeted MCP save.
`presentation.icon` is a bounded PNG data URL carried by the API's existing extra
metadata support; it must never enter transport parameters. Preserve sibling
presentation fields and masked credentials; cancel/reset/unmount must fence stale
image-decoding results. Uploaded remote URLs and SVG are never rendered. Existing
shared-MCP administrator checks remain authoritative; this adds no personal scope.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

### Shared model settings

Settings → Models (`?settings=models`) offers administrator-only catalog management
through `/api/managed-models`. YAML entries are read-only. `core/models/management.ts`
whitelists editable fields so source metadata and `has_api_key` never get posted.
Draft credentials stay in editor state, never query cache or browser storage; blank
keeps the saved key, explicit removal sends an empty key. Saving invalidates both the
admin catalog and `MODELS_QUERY_KEY`. Editor unmount aborts probes and fences late
callbacks. Static demos and non-admin users must not query the management API.

### Model reasoning capabilities

`/api/models` projects a per-model `reasoning` contract (issue #5073) beside the
deprecated `supports_thinking` / `supports_reasoning_effort` booleans.
`core/models/reasoning.ts` is the only place that interprets it: it falls back to
the booleans for older Gateways, clamps the chat mode (`getResolvedMode` never
yields `flash` for a required-thinking model), lists the effort options the
composer and the sidecar render, and maps mode presets and remembered values
through the contract's aliases/default (`resolveReasoningEffort`). Effort values
are open strings (`ReasoningEffortValue`), so provider-specific tokens such as
`max` flow through local settings and account preferences unchanged; the custom
agent dialog offers only the intersection with the per-agent `low/medium/high`
schema and hides "off" for required-thinking models. Do not read the booleans in
components directly. On a legacy model, `resolveReasoningEffort` keeps only its
advertised generic values; this drops a remembered provider-specific token after
a model switch without changing the backend's direct legacy-request behavior.

## Full-stack plugin UI

`core/extensions/` loads authenticated deployment-installed ES modules from `/api/plugins`.
Inline modules use authenticated fetch plus a released Blob URL. Manifest assets use
native credentialed module scripts, preserving relative imports and resource URLs.
Both honor the backend base and prefixes; transport and cache semantics are documented in
`docs/full-stack-plugins.md`. Host copy belongs in the typed locale dictionaries.
Conversation action factories, shapes and availability callbacks are guarded per plugin;
only validated value snapshots reach the toolbar/sidebar render paths.
`PluginNavigation` and the dynamic workspace extension route consume page declarations;
Capability Center defaults to the repository examples in `core/extensions/catalog.ts`,
merged by explicit namespace with runtime descriptors. Catalog-only entries are discovery
metadata, never module-loader inputs or proof of installation. Backend-only examples may
have no plugin descriptor; keep their runtime status unasserted. Details link to package
installation instructions. Keep the catalog aligned with `examples/deerflow-extension-*`.
Agent teams uses `community.agent-teams`; merge its installed descriptor into the
localized catalog entry without asserting runtime status for a catalog-only row.
Conversation action slots augment normal/custom-agent toolbars and sidebar menus without replacing native export or notification.
Plugin views use mount/dispose and abort signals; Shadow DOM is CSS isolation, not a sandbox.
Descriptors are user-keyed page snapshots, refreshed manually. Backend calls bind the plugin's
namespace, action allowlist and expected viewer identity. See `docs/full-stack-plugins.md`.

Plugin page `openConversation(threadId)` resolves authenticated thread metadata
with `pathOfThread`; do not let plugins hardcode default-agent routes. The page's
abort signal fences late navigation after unmount/account changes. Synchronous
conversation-action callbacks reject Promise returns while consuming rejections.

### Composer references

`components/workspace/mentions/` owns cursor-local `@` detection, the picker,
and atomic references. Render labels as DOM text, never HTML; canonical tokens
preserve draft positions. Submission expands tokens to `@label` and sends up to
16 unique skill IDs in `additional_kwargs.skill_references`; the backend checks
each against the user registry and agent allowlist. The web slash picker lists
only `/goal` and `/compact`; skill selection uses `@`. Legacy typed slash text
continues through normal message submission for backend and channel compatibility.
Project files require confirmed `additional_kwargs.files`. Conversation context
is reconciled from tokens against the current capability and limit. Only successful
discovery may flatten references; pending/errors preserve IDs and block reference
sends, with retry on failure. Polish restores whole labels longest-first in one
pass. Confirmed thread creation seeds metadata before migration; references stay
locked during attachment. Deleting an object removes its context; undo restores
references already attached to the draft. Labels grant no read authority. IME,
caret, thread changes and attachment fences apply to editor and picker. The `@`
and attachment buttons share the picker.

The API fetch wrapper must forward native Request inputs intact, including body,
method, explicit workspace header and AbortSignal. Derive CSRF from the effective
RequestInit/Request method; caller RequestInit headers override inherited ones,
and clone before adding CSRF. Never reduce a Request to just its URL. Workspace
Request tests normalize Headers at the happy-dom fetch-double boundary because
its Request constructor does not consume the worker Headers instance like native
fetch; keep actual selector/body/signal assertions. Shanghai frontend #6 verifies
this foundation and full check, not automatic workspace/client/cache switching.
All frontend tests/typecheck here run in Shanghai, not local Docker/Node runtime.


The SDK factory accepts an explicit `WorkspaceRequestScope` as its second
argument: actor ID, canonical workspace UUID and AbortSignal for one page
lifetime. It snapshots metadata and memoizes only by that lifetime object;
never mutate an existing scope to switch workspaces. Main, run-creation and
recovery transports all bind the same selector and combined signal. Creation
keeps zero retries; recovery GETs retain the native retry budget. Workspace
streams use `onDisconnect: "continue"` so detaching a page does not implicitly
cancel its background Run. Stream and join/recovery options must carry the
combined lifetime signal into the SDK's own reconnect loop, not just fetch.
SDK 1.6 classifies fetch cancellation by message prefix: normalize aborted
fetch failures to an Error named AbortError with an AbortError-prefixed message
so it never waits through network retry backoff. Keep native unscoped/demo
behavior unchanged. SDK reconnect markers are actor/workspace/thread-keyed;
the React hook's own resumable storage and provider/cache integration remain
unwired and must not be described as full tab isolation.


QueryClientProvider owns a lazily created QueryClient per mounted page tree.
It reads optional AuthProvider display identity and keys the query subtree by
actor ID plus an explicit `cacheKey`; account changes/logout immediately render
a fresh cache, including when the workspace key stays the same. Public artifact
and showcase trees can omit authentication context and still get independent
caches. The future workspace provider must pass a stable key for one validated
workspace lifetime and renew it on workspace/credential/policy lifetime changes;
a mutable browser-global current-workspace value is not a cache identity.
Genuine unmount clears query/mutation caches and cancels queries. Cleanup uses
a captured generation object and a microtask to distinguish real unmount from
React StrictMode's immediate effect replay; do not clear the still-live cache
during that replay. Cache removal does not cancel server-side Runs, physical
work or arbitrary mutation callbacks; their request/publication lifetimes remain
separate required fences. This foundation does not wire the workspace selector.


Browser workspace REST callers use `createWorkspaceRESTClient(scope)` from the
shared fetcher. The factory copies the actor/workspace/signal and configured API
root once; its fetch keeps native Request body/method, CSRF and live-401 behavior
while binding the selector and cancellation through the shared transport.
Prefer its `json()` for materialized JSON: it checks the captured combined signal
after decoding and before returning data or a parsed GatewayApiError, so late
results/errors cannot survive a cancelled lifetime. Native domain decoders use consume(response, reader), which accepts only
a Response returned by this exact client and checks its combined signal before
and after the whole success/error decoder, including caught parse failures.
The Response itself remains native. Raw fetch consumers that skip consume()
still own their post-decode/publication fences. Returning a value does not fence
a caller that starts another await before applying it. Native unscoped fetch and
static demos retain their original behavior; explicit workspace clients reject
demo mode. RequestInit signal:null clears an inherited Request signal, never the
workspace lifetime. Shared scoped fetch dispatches the resolved/validated absolute
URL (or original native Request), not a raw relative string that the browser
would resolve against a different page/base URL. No actor header is invented.
The workspace selector/context and consumer wiring remain required work.


`core/workspaces/context.tsx` provides the opt-in WorkspaceProvider and
WorkspaceReadyBoundary. Provider enablement must come from server runtime
capability; disabled nested wrappers preserve an existing parent context.
Each native actor owns one WorkspaceSession; its read-only metadata adapter
validates the active list, unique own personal workspace and current actor,
selector and membership/policy versions before publishing any new names/roles
or constructing REST/SDK clients. Selection aborts the previous lifetime first;
a stale completion cannot overwrite a later selection. Snapshot data and
client scope are immutable; the per-entry cacheKey includes the versions and
a local epoch. Refcounted microtask release keeps StrictMode's immediate effect
replay alive but permanently closes a genuinely unmounted store.
Controls may read useWorkspaceContext while pending; all resource consumers
belong under WorkspaceReadyBoundary. useWorkspaceLifetime returns null only
without enabled context and refuses pending/denied context, rather than falling
back to native unscoped clients. Ready content owns the matching query cache.
This component is not yet mounted in the app shell: runtime capability/bootstrap,
consumer clients, selector UI and stored thread/artifact/reconnect metadata still
need integration. No automatic membership/session watcher is installed here;
selection and explicit refresh revalidate. Cross-tab credentials/native principal
consistency and physical Run behavior remain M4/M6/M11 requirements.


Native upload hooks capture useWorkspaceLifetime and pass its REST client into
upload/list/limits/delete APIs. Scoped list/limits queries consume their query
AbortSignal; mutation cache effects skip expired lifetimes. The on-submit helper
checks again after awaiting upload. Optional request options preserve native
unscoped callers. Ordinary chat's separate direct uploadFiles path also captures
the confirmed REST client. Replay and other resource actions still need integration;
upload-hook checks alone do not prove complete chat isolation.


Native ordinary chat consumers now capture useWorkspaceLifetime: useThreadStream
uses its SDK for streaming/agent metadata and its REST client for direct upload;
per-thread history, metadata, Runs and token-usage reads use the same lifetime.
Check again after conversion/upload/submit awaits before publication. Expired
stream callbacks must not send UI notifications or update task/cache state.
The SDK-supported reconnectOnMount storage factory uses core/workspaces/run-storage:
map only lg:stream keys to actor/workspace/thread keys, refuse operations after
scope abort, and leave native unscoped keys untouched. Recovery helpers use this
same adapter. A stored marker is only a hint; server-side Run/resource ownership
must be revalidated. Switching workspace must not cancel background Runs.
Sidebar search/CRUD hooks have captured lifetime bindings, verified with
Shanghai frontend #35; see the 2026-10-15 resume checkpoint. Replay/compact, UI caller
publication, remaining resources/stores and shell activation are still pending.
Do not infer complete client isolation from network-double tests.


Scoped thread actions use optional ThreadRequestOptions for REST domain
decoding and captures the SDK for search/Run detail/rename. Recheck expiry after
async cache cancellation before publishing mutation effects. Sidecar lookup
cancellation must not fall through to best-effort parent deletion. Scoped delete
uses the canonical Gateway REST endpoint once per normally enumerated thread;
retain SDK-plus-local-cleanup only for native unscoped compatibility. The 50 hook/network tests and full frontend check pass in #35. Actual
backend/browser acceptance remains pending; tenant activation stays closed.


Regenerate/edit replay now captures the confirmed REST client and fences the
whole native prepare success/error decoder plus entry/prepare/submit boundaries.
Expired replay callbacks return false quietly; existing replay masks and native
ordering remain intact. Shanghai frontend #39 verifies 20 hook/network tests and
full pnpm check. Compact/project creation, page callbacks and remaining resource/
storage/shell integration still precede activation and actual browser acceptance.


createThread accepts optional third ThreadRequestOptions; compactThreadContext
accepts options.rest. Both preserve native no-options requests/errors and fence
full decoding through the fixed REST client (#43, 17 tests/full check). ChatPage project creation/branch is integrated in #47; ancillary InputBox
paths and the remaining resource/storage/shell integration still precede activation.
The actual delete dialog separately fences retained open/delete callbacks,
reset/router, post-await publication, error feedback and focus by its lifetime.


InputBox goal GET/PUT/DELETE and compact commands capture useWorkspaceLifetime
(#45: 21 tests/full check). Preserve command AbortController/epoch checks and
prepare→save→run ordering alongside scope fences. Goal decoders include native
error reads; clear accepts an empty success body. Guard before publication and
follow-up submit, not only fetch. Ancillary reference/input-polish/voice paths
and draft/attachment stores still require integration before activation.


ChatPage precreation captures the confirmed REST client (#47: three page/
Context mains/full check), preserves native no-options behavior and refuses
stale preparation/cache writes. Keep the native conversation epoch alongside
scope guards. Branch callbacks guard entry, after await and errors; reference
attachment routing checks expiry. Leaf UI/stream/branch operations are doubled
in the page fixture; this is not actual browser/backend authorization proof.


Sidecar scoped main/create/delete publication is verified in Shanghai #54
(three real panel/context/SDK/REST mains + ten native regressions/full check).
Provider restore uses the fixed SDK and checks the decoded result. Optional
ThreadRequestOptions binds create; namespace pending creates by REST client
(WeakMap), not a global parent ID. Keep legacy no-options coalescing and native
errors. Panel/trigger await continuations check expiry; first-send queue rejects
typed AbortError on scope close and removes listeners after settling. Native
unknown send failures retain their localized fallback. Actual same-space parent
change/unmount/quiet-stream fault audit, other clients/stores and browser/backend
acceptance still precede activation; do not infer them from these network doubles.


Activity/read hooks bind the confirmed REST lifetime (#57: two scoped mains
and 20 native regressions/full check). Polling combines Query/workspace abort
signals and fences cursor/read clock updates and invalid-cursor recovery.
Read callbacks/timers refuse expired scope; late decoded success/errors cannot
update clocks or invalidate lists. Preserve native no-options clients, 15s
polling, 1s debounce, optimistic unread patches and monotonic read versions.
Real hooks/Context/REST with HTTP doubles are not browser/backend acceptance.


Project APIs accept optional ProjectRequestOptions (#61: two scoped mains,
38 native regressions/full check). Keep native no-options argument lists and
request/error/Range/PDF/binary behavior; the shared helper owns the whole
decoder with fixed REST. All project hooks capture that lifetime, combine
Query/scope cancellation, and guard onSettled invalidations. Actual page
callbacks, upload loops, preview effects and direct URLs still require scope
binding/publication guards. HTML preview base stripping of search means a
top-level workspace query cannot scope relative resources by itself.

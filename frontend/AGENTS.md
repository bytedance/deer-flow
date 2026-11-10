# AGENTS.md

Frontend guidance; `CLAUDE.md` imports `@AGENTS.md`.

Feature rules live next to the code. Read the guide before you change that area:

- [src/AGENTS.md](src/AGENTS.md) — data flow, threads, streaming
- [src/components/workspace/AGENTS.md](src/components/workspace/AGENTS.md) — model
  picker, artifact previews, Capability Center, plugin UI, composer references
- [src/components/workspace/browser-view/AGENTS.md](src/components/workspace/browser-view/AGENTS.md) — browser view
- [src/core/models/AGENTS.md](src/core/models/AGENTS.md) — model catalog, shared model
  settings, reasoning capabilities, provider presets
- [src/core/auth/AGENTS.md](src/core/auth/AGENTS.md) — authentication, admin user management
- [src/core/memory/AGENTS.md](src/core/memory/AGENTS.md),
  [src/core/background-tasks/AGENTS.md](src/core/background-tasks/AGENTS.md),
  [tests/e2e/AGENTS.md](tests/e2e/AGENTS.md)

## Project Overview

Next.js 16 frontend for LangGraph conversations, streaming, artifacts, skills and tools.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2. Requires Node.js 22+ and pnpm 10.26.2+.

Dependencies: `@langchain/langgraph-sdk` ^1.5.3, `@langchain/core` ^1.1.15,
`@tanstack/react-query` ^5.90.17. Registry UI: Shadcn, MagicUI, React Bits,
Vercel AI SDK (see Code Style).

`pnpm-workspace.yaml` pins vulnerable `@xmldom/xmldom` 0.9.x to patched
0.9.12 (GHSA-965w-775f-mr7g) and Nextra 4.6.1's Zod dependencies to 4.3.6
until upstream fixes missing-`children` validation. App schemas use Zod 4.6.6.
Remove each override after its upstream fix; refresh the lockfile and test
docs builds after changes.

## Commands

Run from `frontend/`; host pnpm calls use `../scripts/pnpm.py`.

- `pnpm dev`: development; `pnpm build` / `pnpm start`: production build/server.
- Before committing: `pnpm check` (ESLint + TypeScript). Separately: `pnpm lint` / `pnpm typecheck`; ESLint fixes: `pnpm lint:fix`.
- `pnpm format` / `pnpm format:write`: Prettier check/write.
- `pnpm test`: Rstest unit tests; `pnpm test:e2e`: Playwright Chromium E2E tests.

Unit tests under `tests/unit/` mirror `src/`; import source via `@/`.

Webpack is the default; use `DEER_FLOW_DEV_BUNDLER=turbo pnpm dev` to diagnose with Turbopack.

Windows dev binds `127.0.0.1` to avoid Hyper-V/winnat `EACCES` (#2870).
For LAN access: `pnpm dev -- --hostname 0.0.0.0`.

`rstest.config.ts`: **node** for `*.test.*` logic; **happy-dom** for `*.dom.test.*`
components/hooks via `@testing-library/react` render/renderHook. Keep the split
(DOM costs ~3x). Test effect ordering, unmount cleanup and store re-renders with real React/DOM.

Content/state suites may use `tests/unit/helpers/flip-display.tsx` to mock
decorative `FlipDisplay`; preserve children, classes and keyed remounts.
Happy DOM 21 animation cancellation rejects `finished`; keep rejection reporting
enabled. Test real Motion in Playwright.

Playwright Chromium E2E: `tests/e2e/`, configured by `playwright.config.ts`.
Mock backend APIs with `page.route()`; exercise real navigation, chat input and streaming.
When registering permissions (including `projects:read/write/delete`), update both
`tests/e2e-real-backend/auth-disabled-contract.spec.ts` and
`backend/tests/test_auth_me_permissions.py`, which pin the complete route-permission list.

CI runs four E2E shards; only shard 1 runs auth recovery. Suite reports stay separate.

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
`notification_group_connection_id` adds one Feishu group without changing personal
notifications. The selector requires `features.scheduled_tasks.group_notifications`
(absent = false); otherwise a saved target is preserved but explicitly clearable.
While the capability query is pending, show loading without a clear control.
Reuse `useChannelConnections`: offer connected Feishu `group` bindings with matching
nonempty metadata chat/workspace IDs. Show workspace names; disable unnamed groups
and never display raw IDs. Loading/errors preserve selections. PATCH omits unchanged
groups, clears with `null`, and leaves schedules untouched; Duplicate copies the group.
`BindFeishuGroup` uses the connect API for a persistent, copyable `/connect` command
and explicitly refreshes the shared query. The general connection poll stops early
when a private binding already exists, so cannot wait for a new group.
In chat, a `schedule_task` result becomes an `assistant:scheduled-task` group (`core/scheduled-tasks/tool-result.ts`, last card per task per turn; not a turn boundary) rendered by `ScheduledTaskCard`, which polls the task only while on screen. A human message with `additional_kwargs.deerflow_scheduled_origin` stays a `human` group with `scheduledOrigin`: `ScheduledRunPrompt` renders the origin's user-language parts, never the launched text, and it is not editable.
Server-created threads: `core/threads/origin.ts` reads `metadata.deerflow_origin` (`contracts/thread_origin_contract.json`), then `channel_source`, then a legacy `scheduled_task_id`; provider names come from `threads.origin.providers`. `core/threads/activity.ts` polls `/api/thread-activity` (mount `useThreadActivity` once; unmounting resets its cursor; first poll only seeds; invalidate lists only on server-origin threads, truncation or a higher `read_version`) and `useMarkThreadRead` posts reads. `core/scheduled-tasks/events.ts` loads a chat's lifecycle events, not gated on its task list; `placeTaskEvents` puts each at the end of its `after_run_id` turn. The UI language is saved as the `locale` preference once per session and on each switch, only when the Gateway's preferences include `locale`.
Thread rows (sidebar, `/workspace/chats`) show `ThreadOriginIcon` and, if `unread === true` and not the open thread, `ThreadUnreadDot` with `threads.unreadLabel` as row label. `WorkspaceSidebar` mounts `useThreadActivity`. Chat pages call `useMarkOpenThreadRead` once metadata loads (marks read on load, on an unread flip, on tab visible, and via its callback from `onFinish`).
Chat pages pass `useThreadScheduledTaskEvents` data to `MessageList` (`scheduledTaskEvents`; the custom-agent page also passes its agent for the run link), which renders `ScheduledTaskEventLine` through `VirtualMessageList.renderAfterGroup` at the `placeTaskEvents` position, inside the group's measured row. Lines are history: never gated on the task list. Channel provider cards (Settings and the sidebar list) render `ChannelScheduledUpdates` from `proactive_notifications`, and nothing when the field is absent.
Keep IM notification preferences viewer-fenced and separate from browser alerts; only confirmed server writes change switches.

## Architecture

Token usage: `app/workspace/usage` composes `components/workspace/usage` and
`core/usage` over the existing owner-scoped console APIs. Keep owner, period,
timezone, status and page in query keys; consume AbortSignals and never show
another owner's or period's placeholder totals. Gate on `runs:read` and static
mode. Display tokens without changing optional backend pricing fields.
See [design and reporting semantics](docs/token-usage-dashboard.md).
Run links reuse `pathOfThread`; `lead_agent` and absent assistant IDs select
normal chats, while custom assistant aliases follow Gateway normalization.

Model controls: `core/models/use-model-control` + HumanInputCard.

Knowledge evidence is parsed in `core/citations/sources.ts` from version-1
ToolMessage artifacts. Message rows receive sources from preceding loaded tool
messages. `#knowledge-source-ID` links resolve to `KnowledgeCitation` and an
expandable source panel with actual excerpts. Missing URLs/pages remain absent.
Web citations and old history remain compatible. Never infer evidence from
assistant labels or numbered legacy text.
Shared records use the `RetrievalSource` type (native RAGFlow retains
`KnowledgeSource`). Accept raw and `#user-content-knowledge-source-ID`
fragments without disabling sanitizer clobber protection. Validate immutable
tool messages through `createKnowledgeSourceReader` to reuse per-object parses.
Cross-component field bounds live in `contracts/knowledge_sources.v1.json`.
Completed `SubtaskCard` reports read shared evidence only from the matching
`task` ToolMessage after its invocation in the current subagent group, selected
by `findSubtaskResultMessage`. Prompts/earlier steps do not borrow final evidence.
Remount report Markdown when validated source IDs change: Streamdown caches
unchanged text blocks independently of renderer components.

```
Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_agent)
                                              ├── Sub-Agents
                                              └── Tools & Skills
```

Users create **threads** (conversations), send messages, set thread-scoped `/goal` completion conditions, and receive streamed responses, agent **artifacts** (files/code), **todos** and goal state updates.

### Source Layout (`src/`)

Read [auth ownership and recovery](src/core/auth/AGENTS.md) before changing
`AuthProvider` or `QueryClientProvider`. Auth forms trim emails, not passwords.

See [project structure](README.md#project-structure) for the directory map and
[src/AGENTS.md](src/AGENTS.md) for component and domain ownership.

## Code Style

`core/utils/markdown.ts` reads web-fetch titles from the first nonblank line.
Match zero to three literal spaces before a single `#` followed by an ASCII
space or tab, without trimming indentation; mixed space/tab code blocks must
fall back to the URL. Strip optional closing
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

Custom Agent tool access is edited from the configured names returned by
`GET /api/agent-tool-groups`. Preserve the `null` / `[]` / explicit-list
contract (inherit all / disable all / allowlist), retain missing selected names
as removable entries, and submit `tool_groups` only when the user changes it.
Mark missing names unavailable only after a successful catalog load; loading
and errors preserve neutral labels and removable selections.
When a changed allowlist excludes `knowledge`, send `knowledge_scope: null` in
the same update so a saved retrieval default cannot break run admission. Gate
knowledge selection on both draft and persisted tool access: catalog reads
authorize against the saved agent, so new access must be saved first. Restored
tool selections remain unchanged and must not clear a knowledge default.

Custom Agent portability uses the versioned `deerflow.custom-agent` JSON
document through `core/agents/api.ts`. Keep file parsing client-side only for
previewing the proposed local name; the Gateway is authoritative for schema,
name, model, and conflict validation. Export downloads must never synthesize
runtime state from browser caches.

New-Agent saves need the latest `setup_agent` success and API read-back.
Failed/exhausted saves restore Save. Fence superseded or unmounted callbacks.
DOM regression: `new-agent-save.dom.test.tsx`.

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

Sidebar customization: `components/workspace/workspace-sidebar-frame.tsx`.
Rail/drawer mount one tree; `useWorkspaceSidebarExpanded` preserves desktop
`SidebarProvider.open`. Keep polling/delete-dialog provider outside that tree.
Reuse stock `Sidebar`; close before link navigation and on pathname changes,
preserving page focus. Dismissal restores the opener or remounted rail trigger.
`WorkspaceSidebarTrigger` owns surface icons/ARIA; keep generated UI unchanged.
Test frame DOM behavior and `tests/e2e/sidebar.spec.ts`.
Agents headers/actions wrap with the rail; sidebar E2E tests cover bounds.

Scheduled-task list search filters the current authorized query result by title or
prompt, composing with status/type filters and thread scope. Selection must derive
from the filtered list so hidden tasks cannot remain actionable. Keep literal
matching in `core/scheduled-tasks/search.ts`; clearing search retains other filters.

Single-run schedule edits retain the mounted task's original `run_at` while its wall time and timezone match. The parent echoes edits through `initial`; retain a stable snapshot and reset the parent draft during render before remounting with a task key when switching tasks. Use the resolved timezone consistently for the snapshot and displayed wall time. Component and scheduled-task E2E tests cover DST folds and timestamp precision.

The scheduled-task schedule input initializes Custom cron from the current
preset and its current fields on every transition into the custom editor.
Do not substitute a daily schedule or restore stale `parts.raw` after preset
edits. Component tests cover emitted specs; browser tests pin unchanged
schedules through the task form's PATCH payload on desktop and mobile.

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

`make build-static` emits a standalone read-only demo, copying `.next/static`
and `public`. In static mode, `core/api/static-response.ts` serves Gateway reads
from bundled capabilities and safe installation projections in same-origin
`/mock/api` fixtures; writes and unknown routes fail locally.
The homepage counter uses `/github-stars`, outside Gateway. It reads server-only
`GITHUB_OAUTH_TOKEN` at runtime, caches GitHub data for one hour, and returns 204
when unavailable. From `frontend/`, run `node --env-file=.env
.next/standalone/server.js` to load credentials.

For non-localhost dev access, set `DEER_FLOW_DEV_ALLOWED_ORIGINS` to comma-separated
hosts (URLs reduce to hosts). Next's `allowedDevOrigins` gates `/_next/*`, fonts
and HMR; otherwise 403s prevent hydration and interactions, including login.
Production ignores this setting.

One-time schedule input uses `validZonedLocalToUtcIso` to reject wall times that
do not round-trip in the selected timezone. Invalid input emits an empty spec and
localized inline feedback; both create and edit must block submission. Keep this
UI validation separate from the API payload. Preserve the original instant when
wall time and timezone match the mounted snapshot; validate changed inputs, and
restore the exact original timestamp when those edits are reverted.

Wall-time conversion matches the scheduler's `ZoneInfo(fold=0)` policy: choose
the first occurrence of a repeated time and the pre-transition offset for a
skipped time. Stored one-time schedules use that instant for display; the form's
round-trip validation must still reject newly entered skipped times.

## Resources

- [DESIGN.md](DESIGN.md) — tokens, type, components, a11y rules; read before UI work
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Core Concepts](https://js.langchain.com/docs/concepts)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [Next.js App Router](https://nextjs.org/docs/app)

## Contributing

Follow `src/` ownership, add types/error handling and unit/E2E coverage, run
`pnpm check`, and update this guide for architecture, command, or convention changes.

Docs search: `pnpm build` runs `scripts/build-search-index.mjs`: route-based
language, then replace `public/_pagefind/` (generated). `DocsHtmlLang` syncs
runtime language. Only `Header.search` renders search (`Layout search={null}`).
`MobileNav` uses Headless UI `Portal.Group` inside Radix's scroll boundary;
selections close at the same hash too. Pin behavior with DOM and
`tests/e2e/docs-search-mobile.spec.ts` tests; index tests use temporary files.

`pnpm perf:check` measures `/login` in a production build and fixture-backed
workspace routes in a static-demo build. It starts servers on temporary local
ports, measures unique JavaScript/CSS for representative routes, writes
`.next/performance-results.json`, and checks `performance-budgets.json`.
Fix route ownership or split points when over budget; document and review
measured regressions before raising ceilings.

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

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

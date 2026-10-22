# AGENTS.md

DeerFlow frontend guidance source of truth; `CLAUDE.md` imports `@AGENTS.md`.

## Project Overview

DeerFlow's Next.js 16 frontend provides thread-based AI conversations with streaming responses, artifacts, skills, and tools through a LangGraph backend.

**Stack**: Next.js 16, React 19, TypeScript 5.8, Tailwind CSS 4, pnpm 10.26.2. Requires Node.js 22+ and pnpm 10.26.2+.

Core dependencies: `@langchain/langgraph-sdk` ^1.5.3 for orchestration/streaming,
`@langchain/core` ^1.1.15, and `@tanstack/react-query` ^5.90.17 for server state.
Registry UI: Shadcn, MagicUI, React Bits, Vercel AI SDK (see Code Style).

`pnpm-workspace.yaml` overrides vulnerable `@xmldom/xmldom` 0.9.x releases to
0.9.12 for GHSA-965w-775f-mr7g. Nextra pulls it in through MathJax and
`speech-rule-engine@4.1.2`, which pins 0.9.8. Keep the override until the
upstream dependency chain resolves a patched version without it; regenerate
`pnpm-lock.yaml` and verify the docs build when changing this constraint.

## Commands

[Upload context](../docs/upload-context.md).

Run from `frontend/`; host pnpm calls use `../scripts/pnpm.py`.

- `pnpm dev`: Webpack development server; `pnpm build` / `pnpm start`: production build/server.
- `pnpm check`: ESLint + TypeScript (required before committing); `pnpm lint` / `pnpm typecheck`: individual checks; `pnpm lint:fix`: ESLint fixes.
- `pnpm format` / `pnpm format:write`: Prettier check/write.
- `pnpm test`: Rstest unit tests; `pnpm test:e2e`: Playwright Chromium E2E tests.

Rstest unit tests under `tests/unit/` mirror `src/` (e.g., `tests/unit/core/api/stream-mode.test.ts` tests `src/core/api/stream-mode.ts`). Import source modules via `@/`.

Webpack is the default development bundler. Use `DEER_FLOW_DEV_BUNDLER=turbo` with `pnpm dev` to opt in to Turbopack when diagnosing a local Next.js bundler issue.

On Windows `pnpm dev` binds `127.0.0.1` by default because Hyper-V/winnat excluded port ranges can reject Next's default `0.0.0.0` bind with `EACCES` (#2870). Pass `pnpm dev -- --hostname 0.0.0.0` to listen on a LAN interface instead.

`rstest.config.ts` separates **node** (`*.test.ts` / `*.test.tsx`) for pure logic
from **happy-dom** (`*.dom.test.ts` / `*.dom.test.tsx`) for components and hooks
rendered with `@testing-library/react`'s `renderHook`. Keep the split: DOM tests
cost roughly 3x more runtime. Hooks that depend on React effect ordering, unmount
cleanup, or re-renders on store changes belong in `.dom.test.*`; do not mock React
in node tests to cover those behaviors.

E2E tests live under `tests/e2e/` and use Playwright with Chromium. They mock all backend APIs via `page.route()` network interception and test real page interactions (navigation, chat input, streaming responses). Config: `playwright.config.ts`. The real-backend auth contract in `tests/e2e-real-backend/auth-disabled-contract.spec.ts` and `backend/tests/test_auth_me_permissions.py` pin the complete route-permission list; update both when adding registered permissions (including `projects:read/write/delete`).

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

`AuthProvider` publishes the query owner (user ID, confirmed logout, or unknown
auth). `QueryClientProvider` owns a mount-local client and remounts its consumers
when that owner changes, clearing the old cache and cancelling old queries.
Confirmed logout unmounts query consumers immediately; public and unknown-auth
routes still render with an independent client. Keep auth outside the query
provider. Superseded auth refreshes cannot restore an earlier owner.

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

Wall-time conversion matches the scheduler's `ZoneInfo(fold=0)` policy: choose
the first occurrence of a repeated time and the pre-transition offset for a
skipped time. Stored one-time schedules use that instant for display; the form's
round-trip validation must still reject newly entered skipped times.

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Core Concepts](https://js.langchain.com/docs/concepts)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [Next.js App Router](https://nextjs.org/docs/app)

## Contributing

Follow `src/` ownership, add types/error handling and unit/E2E coverage, run
`pnpm check`, and update this guide for architecture, command, or convention changes.

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

`skill-diagnostics.tsx` mounts only for administrators outside static demos. Its
user-keyed diagnostics query is separate from `useSkills()` and every picker.
Reload posts `/api/skills/reload` before invalidating both normal skills and
diagnostics; failures retain the warning and show localized retry feedback.
Never interpret raw parser exception wording in the UI.
Keep the scope note visible even when diagnostics are empty. It must describe
the YAML-syntax-only check and its exclusions (missing frontmatter, metadata
validation, unreadable and non-UTF-8 files); it is not a package-validity check.

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

### Admin user management

Settings → Users (admin-only nav entry; `?settings=users`) suspends and restores
accounts through `core/auth/admin-users.ts` → `/api/v1/admin/users`. The page
reuses `userSchema` for rows — both endpoints parse against it, so a
malformed payload fails the load instead of rendering a phantom row
(`disabled` optional — absent means not disabled) — and PATCHes only
`{disabled}`; role stays a read-only column. Like model management, the page
also gates on `isStaticWebsiteOnly()` (the demo user is nominally an admin,
but there is no Gateway to query), and the settings dialog falls back to the
first nav section when a deep link or stale store activates a section the
current user's nav does not offer. The Gateway's rejection detail
(last-active-admin 409) renders verbatim. A session
that turns out to be disabled maps `account_disabled` (see `AUTH_ERROR_CODES`)
to a login redirect with a stated reason (login surface only — sign-up keeps
the backend message so a suspended account cannot be probed) on all three
surfaces: SSR
`AuthResult` tag (consumed exhaustively by the workspace/artifacts/auth
layouts), the shared fetcher's 401 interception, and `AuthProvider.refreshUser`.
Direct auth-page visits with a live suspended-session cookie get the SSR
verdict via `AuthDisabledContext`, so the login form states the known reason
without waiting for a deliberately generic login failure.

Other sign-in bounces keep path, query and fragment via `currentReturnPath()`. The
workspace layout cannot read the URL, so `unauthenticated` renders
`WorkspaceLoginRedirect` (never `children`), not `redirect()`.

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
schema and blocks new "off" for required-thinking models. Do not read the booleans in
components directly. Legacy `resolveReasoningEffort` keeps only advertised generic
values, dropping provider tokens after a switch; backend requests stay unchanged.
Agent settings omit untouched reasoning, show invalid saved values for clearing,
and require a known model to save a model switch.

## Full-stack plugin UI

Follow [invariants](../docs/full-stack-plugins.md#frontend-implementation-invariants) for
plugin loaders/pages/actions: viewer-bound auth, native actions, i18n and
mount/dispose/abort fencing. Shadow DOM is not a sandbox. Bundled extensions need
typed en/zh `core/extensions/catalog.ts` entries with their namespace.
Catalog entries are not proof of installation or activation.

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
caret, thread changes and attachment fences apply to editor and picker. Commit
mention text before restoring focus synchronously; a delayed callback must not
overwrite subsequent typing or caret movement. The `@`
and attachment buttons share the picker.

### Web model provider presets

Settings → Models obtains provider form metadata from the admin-only backend `/api/managed-models/providers`; do not copy endpoints, protocols or adapter maps into the UI. New models need only provider, API key and arbitrary model ID, with server-generated stable names. Custom endpoint fields and legacy edits stay supported. Provider/endpoint changes clear test results and saved-key reuse; omitted keys retain only the same connection. Capability overrides belong in Advanced settings. Successful saves/toggles invalidate both managed-model queries and MODELS_QUERY_KEY so existing chat/Agent selectors refresh. Keep locale text and administrator/static-mode restrictions aligned.

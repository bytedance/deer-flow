# Workspace entry-point inventory

Status: static inventory with partial runtime evidence. Controls below remain requirements unless explicitly verified. Public tenant signup stays disabled.

Private project CRUD now has actual JWT/RBAC/CSRF and native SQL evidence for SQLite/PostgreSQL (Jenkins #19); project thread listing now intersects live project ACL with private scoped thread ownership (#28). Private project documents now have real upload/list/download/trash and before-send revocation evidence (#21). Explicit project/document sharing has actual native-auth and file evidence (#23); thread files/NAS, client caches and other resource entrypoints remain pending. See `docs/tenant-workspaces-progress.json` for exact source hashes and limits.

All content access requires native permissions intersected with active workspace membership and resource ACL. Workspace selectors are locators, never authority. Background work restores scope from its persisted resource or explicitly bound connection.

| Gateway router | Required boundary | Work package |
| --- | --- | --- |
| `backend/app/gateway/routers/admin_users.py` | Platform control plane; no implicit tenant-content bypass | M2/M8 |
| `backend/app/gateway/routers/agents.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/artifacts.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/assistants_compat.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/auth.py` | Explicit public endpoint allowlist; authenticated provisioning | M2/M6 |
| `backend/app/gateway/routers/browser.py` | HTTP and WSS thread scope, Origin and revocation checks | M3/M4 |
| `backend/app/gateway/routers/capabilities.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/channel_connections.py` | Explicit workspace connection; reject unbound automation; scoped credentials | M4/M5/M6 |
| `backend/app/gateway/routers/channels.py` | Explicit workspace connection; reject unbound automation; scoped credentials | M4/M5/M6 |
| `backend/app/gateway/routers/console.py` | Platform control plane; no implicit tenant-content bypass | M2/M8 |
| `backend/app/gateway/routers/features.py` | Explicit public endpoint allowlist; authenticated provisioning | M2/M6 |
| `backend/app/gateway/routers/feedback.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/github_webhooks.py` | Explicit workspace connection; reject unbound automation; scoped credentials | M4/M5/M6 |
| `backend/app/gateway/routers/input_polish.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/integrations.py` | Explicit workspace connection; reject unbound automation; scoped credentials | M4/M5/M6 |
| `backend/app/gateway/routers/knowledge.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/managed_models.py` | Platform control plane; no implicit tenant-content bypass | M2/M8 |
| `backend/app/gateway/routers/mcp.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/mcp_tasks.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/memory.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/models.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/personal_mcp.py` | Explicit workspace connection; reject unbound automation; scoped credentials | M4/M5/M6 |
| `backend/app/gateway/routers/plugins.py` | Platform control plane; no implicit tenant-content bypass | M2/M8 |
| `backend/app/gateway/routers/project_documents.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/project_thread_files.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/projects.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/runs.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/scheduled_tasks.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/skills.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/subagent_batches.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/subagents.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/suggestions.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/thread_activity.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/thread_runs.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/threads.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/trash.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/uploads.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |
| `backend/app/gateway/routers/user_preferences.py` | Resolve trusted scope; filter before pagination/count; validate resource and parent scope; foreign IDs return 404 | M3/M5/M8 |

## Other entry points

| Entry | Required boundary | Work package |
| --- | --- | --- |
| services.py run admission and restore | Scrub external identity in context/configurable; inject trusted scope; restore from thread mapping | M0/M2/M3 |
| SSE reconnect, downloads, WSS | Reauthenticate and check resource scope; URL selector carries no credential; stop delivery after revocation | M3/M4 |
| PAT | Legacy tokens restricted to personal space; new tokens bind one space and intersect native scopes | M2/M6 |
| app/channels/* and GitHub webhooks | Persist actual user and explicit workspace connection; unbound entry fails closed | M4/M5 |
| Native Scheduler | Persist task/occurrence scope; recheck creator membership; no automatic replay after revocation | M4/M8 |
| MCP submit, poll/cancel and notifications | Immutable task scope; authorization at publication/delivery; cleanup cannot grant business authority | M4 |
| ECS B/C claim/adopt/signing/publication | Versioned workspace protocol and ledger/resource/path agreement; unknown physical work remains reserved | M4/M10 |
| Paths, NAS, upload/export, sandboxes | Scoped paths and least-authorized mounts; copy/hash legacy migration without deleting source | M3/M10 |
| Memory, knowledge, prompt assembly | Partition by workspace and visibility; no implicit private-memory injection in team space | M5/M9 |
| Skills, MCP, plugins, models | Tenant connections separate from operator-only host code/configuration | M5 |
| Frontend requests, subscriptions and cache | Bind selectors and cache keys; cancel old requests; switching tabs cannot mutate run scope | M3/M7 |
| Bootstrap, migration and purge | Limited maintenance authority; two-database receipts and verified recovery before admission | M1/M8/M10 |

## Evidence

This inventory is not isolation evidence. Each work package must record implementation location, source revision and Shanghai Jenkins results. M11 audits every entry again. Unknown extension routes require explicit classification and authorization before tenant access; installed code is not automatically covered.

Thread repository checkpoint: Jenkins #26 verifies SQL filtering before pagination, live membership and private ownership with shared project parents. Thread metadata HTTP now binds trusted scope before owner checks; #28 verifies creation/search/PATCH/move and own-only project listing. SQL success does not prove HTTP/SSE/WSS/checkpoint or filesystem coverage.

Thread file checkpoint #31: actual scoped upload, shelf attachment and promotion byte-level main on both databases, plus legacy transfer regression. Short file publication uses live thread SQL fencing; scoped shelf copy and provenance use matching parent/source checks. Artifact ASGI/query, deletion/withdrawal races, full lifecycle and physical NAS/remote mounts remain required.

Thread artifact GET checkpoint #33: real returned URLs, file/ZIP bytes, selector conflicts and before-send policy revocation on SQLite/PostgreSQL; native Range/download regressions retained. PUT, deletion/withdrawal, continuous streaming, token-reset and lifecycle/client/physical mount acceptance remain required.

Upload DELETE checkpoint #35: SQL policy withdrawal between native admission and unlink preserves original bytes on both databases; authorized deletion and companion/symlink regressions pass. Final scope and short drained unlink share workspace/actor/thread locking. Mid-unlink cancellation and physical mount acceptance remain unproven.

Thread read checkpoint #38: native compiled graph with real persistent SQLite checkpoint reopen plus SQLite/PostgreSQL metadata; detail/state/history/goal retain distinct personal/team content and refuse foreign scope. Actual SQL incarnation change during materialization refuses the prepared response. Read-clock and write/lifecycle/background paths, Postgres checkpoint/recovery, delta and browser acceptance remain required.

Read-marker checkpoint #40/#41: actual scoped SQL/HTTP read marking, private Run/thread parent filtering, independent workspace viewer clocks, idempotent repeated reads, and persisted withdrawal without marker changes on both dialects. Current native migration 0038 retains native clocks/keys. Native Run/activity feeds, controlled commit cancellation and scoped thread cleanup remain required.


Frontend Context checkpoint (frontend #25): explicit metadata GETs are a
browser-session control-plane entry before a content scope exists. Fixed
endpoints and expected actor/selector/version checks precede list publication
and REST/SDK creation. Resource mounts are gated by the confirmed lifetime;
current app-shell/consumer wiring and real browser acceptance remain M3/M7.
Inventory also includes the native artifact panel's sessionStorage bootstrap,
thread UI stores and React SDK reconnect markers. Each needs actor/workspace/
incarnation-safe namespacing or reset; query cache remount is not proof for
those stores. Native session/principal changes after promotion still require
M6/M11 proof, including same-workspace actors. No activation gate is removed.


Frontend ordinary-chat checkpoint (frontend #32): native per-thread history,
metadata, Runs/token usage and ordinary send/direct-upload use captured clients.
Conversion/upload/send and stream-callback publication are lifetime-fenced.
React SDK reconnect and durable-list recovery use the same actor/workspace/thread
storage adapter; stale lifetime operations are inert. This tests actual source
hooks with a doubled external React SDK adapter, not real browser reconnect.
Thread search/CRUD/replay/compact, remaining resources/stores and shell activation
are still open entries. Scoped markers never replace server ownership checks.


Frontend thread actions (#35): sidebar SDK/archived REST search and Run detail,
branch/pin/archive/move/rename/delete hooks capture confirmed clients, fence
materialized values and async cache publication, and refuse stale lookups or
callbacks. Scoped canonical deletion avoids a second SDK+REST delete. Native
compatibility regressions pass. Page callers, replay/compact/create, sidecar's
global parent-keyed in-flight map and other resources/stores still require
integration; actual browser/backend/physical acceptance is not supplied here.


Replay frontend (#39): regenerate/edit prepare and submission use the fixed
confirmed lifetime; decoded late responses and retained callbacks cannot dispatch
or publish after switching. Native replay ordering regressions retained. Compact,
project creation, page callbacks and other resource/storage paths remain open.


Create/compact frontend API (#43) accepts captured REST and fences native
response decoding; actual ChatPage/InputBox callers remain unintegrated.


Actual InputBox goal/compact (#45) now captures fixed REST and fences decoding
and follow-up run publication while retaining native command epochs. Its other
async input paths/stores and actual ChatPage/sidecar/resources remain pending.


Actual ChatPage (#47) binds project precreation and fences cache/send preparation,
branch toast/router and reference-attachment URL callbacks. Native and P/T
creation remain; new-space normal branch still routes. Sidecar and remaining
resources/stores/shell/browser integration precede activation.


Scoped sidecar (#54): fixed SDK restoration, REST creation/decoding and
per-client pending-create coalescing; guarded panel/trigger publication with
first-send queue abort settlement. P/T normal send/delete and pending create/
delete races verified through real core hooks with HTTP/SDK React adapter
doubles. Parent navigation/unmount/quiet-stream, other resources/stores and
actual shell/browser/backend acceptance remain open.


Scoped activity/read frontend (#57): fixed REST hooks with owned decoding,
combined poll cancellation and pre-publication clock/cursor guards; retained
callbacks and late JSON cannot act after workspace expiry. Two added P/T
scenarios and 20 native regressions/full frontend checks passed in Shanghai.
Actual shell/browser/backend/principal acceptance and other resources remain.


Project/shelf clients (#61): 16 API functions accept fixed REST/signal options,
15 hooks bind captured lifetimes and refuse stale cache settlement. P/T
normal project/shelf/thread-file flow plus delayed decoding/retained mutation
passes with 38 native regressions/full check in Shanghai. Actual UI callers
and direct download/iframe/relative HTML URLs remain pending; these HTTP
fixtures are not end-to-end or physical isolation acceptance.


Shelf/InputBox handoff (#65): actor/workspace/thread sessionStorage partition
and expired handle fences, real shelf staging and captured onSent retirement;
scoped preview effect and direct document URL selector. P/T/P persistence and
legacy isolation, late attach/send and same-space project multi-file navigation
passed with 105 native regressions/full check. Other page/store/artifact and
actual browser/backend/Run/physical boundaries remain pending.


Composer text/reference drafts/native project UI (#69): disjoint scoped draft
keys with expired/foreign handle fences and active snapshot persistence;
InputBox storage and new-thread transfer bound. P/T/P text/reference/old
onSent proof plus positive native project/settings/sidebar/create-then-move/
delete navigation pass, with those page implementations unchanged. HTTP/
catalog/router/submit and leaf fixtures do not prove real browser/backend/
principal, every callback fault, or remaining artifact/store boundaries.


Artifact panel REST/state checkpoint (#73): native preview/range/hash, revision
save, manifest and ZIP Blob clients bind the captured workspace and decoder
lifetime. Native detail/list/hooks plus scoped panel storage/setters fence
late same-space callbacks and byte/JSON/Blob completion after scope expiry.
50 tests/full frontend check; HTTP/preview/editor fixtures do not prove live
Run/backend/browser/ZIP extraction. Direct/standalone/HTML/media/Markdown
links and operator skill installation are still open; activation closed.


Standalone artifact/top-level locators (#78 frontend, #91 backend): read-only
startup capability, server cookie bootstrap and actor/target-bound initial
selection precede content. Native viewer/raw URLs and login next retain the
canonical locator; disabled/malformed/denied scopes cannot fall back. Native
legacy/public/development compatibility and original renderer retained. 75
frontend behaviors/full check plus 23 feature-projection tests; HTTP/auth/
cookie/router fixtures are not real Next/browser/backend permission proof.
Markdown/message/media, browser/change-panel and nested HTML relatives remain
open, as do shell/two-tab/principal/physical gates; activation closed.


Message/report resource URLs and feedback/change REST (#85 frontend): confirmed
locators bind file references, images/uploads/static screenshots and file-change
links; original Streamdown renderer/controls remain. Shared whole-decoder fixed
REST and per-view pending/publication fences preserve native compatibility.
54 behaviors/full check with HTTP/router doubles; not live WSS/Next/backend
authorization proof. Native HTML Chromium diagnostic proves query/path aliases
and parent Blob URLs insufficient in the opaque sandbox; child-made Blob bytes
load fixture image/CSS/JSON. CitationSourcesPanel raw source links/copy remain a separate unbound consumer.
Actual product HTML protocol/resources, main shell,
two-tab/principal/physical and other M3/M4-M11 gates remain, activation closed.


Source-list links/copied references (#89 frontend): the two native callers
(message and artifact preview) pass their owning view key; source URL alone
is insufficient when two reports cite the same file. Confirmed file locators,
whole native copied-reference formatting and source/view/workspace publication
fences cover success/error feedback and timers. 59 tests/full check, extending
three existing integration cases without adding cases. HTTP/router/clipboard
wires remain doubles; not OS cancellation or real backend/browser/principal/
physical proof. Nested HTML and other M3/M4-M11 gates remain; activation closed.


HTML parent byte-read adapter (#95 frontend): source/lifetime/client snapshot,
same-thread native file routing, structural-normalization refusal and whole
ArrayBuffer cancellation use existing REST authority. 28 tests/full check with
HTTP doubles, not actual browser/proxy/backend or physical proof. The native
iframe renderer does not yet invoke it. Document-bound channel integration,
child-owned Blob/CSS/script/module/data delivery and actual browser/fault
acceptance remain required before M3; runtime activation stays closed.

# Tenant frontend validation — Shanghai

Status: Request forwarding foundation verified; full tenant/frontend acceptance
is unfinished. User-approved UI direction remains native DeerFlow styling.

## Current isolated runner

- Jenkins job: `deerflow-tenant-frontend`, agent label `shanghai-builder`.
- Private workspace: `/data/jenkins-agent/deerflow/tenant-frontend`, including
  its `@tmp`, `cache` and `node_modules` directories, owner 999:987, mode 0700.
- Reused image: `deerflow-native:final-ci-tools-52ce`, content ID
  `sha256:4f269f6b0e50f9579e099e91a23df868ff1b1a49c03cc9b138beac02dafb3f01`.
- Node 22.23.3, pnpm 10.26.2, Rstest 0.10.6, committed lock digest
  `2c8528230db42751714e6378f711c63a4a05834bf11eebb81435d59410268f65`.
- Source is a private SHA-256-checked tar of tracked/non-ignored approved source,
  never production env/config/credentials. See progress JSON for each archive.
- Every container uses uid 999/gid 987, CPU 1, memory 2GiB with no swap. Tests
  and checks have `--network none`; only dependency setup uses the registry.
  No Docker socket, production DB/NAS or operator credential is mounted.

## Reconstruct the dependency/test layout

Do not mount dependencies inside the unprivileged extraction directory: Docker
creates root-owned parent directories there. Mount the private cache at `/cache`
and dependencies at `/deps/node_modules`, extract source as uid 999 into
`/tmp/tenant-source`, then link `frontend/node_modules` to `/deps/node_modules`.
All paths below refer to that isolated container, not the local workstation.

Install the exact tool only if the private cached executable is absent:

```sh
npm install --global --prefix /cache/pnpm-tool --cache /cache/npm-cache \
  --registry https://registry.npmjs.org pnpm@10.26.2 \
  --ignore-scripts --no-audit --no-fund
export PATH="/cache/pnpm-tool/bin:$PATH"
python3 /tmp/tenant-source/scripts/pnpm.py install --frozen-lockfile \
  --ignore-scripts --store-dir /cache/pnpm-store --registry https://registry.npmjs.org
```

The root runner always resolves `frontend/` itself. Verify the exact lock digest
and pnpm version before use; never update the lock to make CI installation pass.
Dependency setup and network-disabled tests are separate containers. Cache is
intentionally retained; all per-build containers carry the exact ownership label
`org.deerflow.tenant.owned=deerflow-tenant-frontend-{BUILD_NUMBER}` and are removed
by a bounded trap that first checks that label. Do not remove other containers,
images, directories or project jobs. Jenkins credential use remains host-local
and is not part of the test environment.

## Verified Request slice commands

Run from the extracted source root, with the cached tool on PATH:

```sh
python3 scripts/pnpm.py exec rstest run \
  tests/unit/core/workspaces/request.dom.test.ts \
  tests/unit/core/api/fetcher.dom.test.ts \
  tests/unit/core/api/static-mode.test.ts
python3 scripts/pnpm.py exec prettier --check \
  src/core/api/fetcher.ts tests/unit/core/workspaces/request.dom.test.ts
python3 scripts/pnpm.py check
```

#2 RED lost the explicit selector and Request cancellation. #6 SUCCESS has 16
passing checks (two new), formatting, full ESLint and TypeScript. Runtime/test
files match its input archive. #1-#6 inventories and runtime/format probes were
independently empty. Full build time was 338.094s; behavior checks took 3.74s.
Setup/fixture/format failures remain in progress JSON and are not hidden as
successful builds. Do not rerun broader unrelated tests merely to raise a count.

The test double normalizes standard Headers entries before happy-dom Request
reconstruction; outgoing request attributes/body/signal remain asserted. This
is a DOM/fetch-double proof, not real browser/backend or two-tab acceptance.
Next slices must verify immutable request scopes, SDK streams/recovery, per-space
query/cache lifecycle and native-style selection. M7/M11 still require actual
backend browser flows; M4/M5/M11 still require signed producers, physical sandbox
and NAS/fault proof. Keep tenant activation closed until those gates pass.


## Explicit SDK workspace scope

`getAPIClient(false, scope)` takes `{ actorUserId, workspaceId, signal }` for one
immutable client lifetime. The factory copies metadata, rejects subsequent
metadata mutation on reuse and keeps old instances bound to the original
selector. This selector is request metadata, never a substitute for server
authentication, membership or policy validation. API origin/prefix and redirects
are fenced before credentials and selector dispatch. Every SDK transport,
including zero-retry creation and normally retried recovery GET, uses the bound
fetch. A dead lifetime refuses new dispatch, late HTTP results and old stream
frames. SDK stream/join options carry the combined signal so cancelled streams
do not enter the internal reconnect backoff. Aborted fetch errors are normalized
for SDK 1.6's message-prefix cancellation classification.

Workspace streams force `onDisconnect: "continue"`; explicit user cancellation
still uses the native cancel API. SDK gap-recovery markers include actor,
workspace and thread. Legacy callers retain their native singleton and storage
behavior. These explicit APIs are not yet automatically selected by the React
workspace tree. Shared REST capture, per-lifetime QueryClient, logout/account
reset, React SDK resumable storage, selector UI, actual server capability and
real authenticated two-tab testing are remaining work. Tenant activation stays
closed; this slice does not prove remote Run/NAS isolation.

The late-HTTP check currently rejects a Response returned after cancellation.
A Response accepted before cancellation may still be parsing; post-parse state
publication fences belong to the pending REST/provider integration. Do not
interpret the transport check as proof that all hook/cache updates are fenced.


## Page query-cache ownership

QueryClientProvider no longer uses a module-global singleton. Each mounted
instance owns a lazily initialized native QueryClient. It keys the descendant
tree by the optional native AuthProvider actor ID and an explicit cacheKey for
a workspace lifetime; account change/logout therefore reset actual existing
authenticated page trees. Changing cacheKey creates a fresh cache before the
new subtree renders. The selector/provider must still supply and renew that
lifetime key; the property is not workspace authentication or automatic
selection. Public page layouts without AuthProvider remain supported.

A real React/TanStack main covers independent page trees, explicit workspace-key change,
query cancellation and late completion, actor switch/logout, and StrictMode
with genuine-unmount cache cleanup. The cleanup microtask compares a captured
generation object to avoid destroying a cache during StrictMode replay.
Existing feature discovery, offline banner and static-mode checks are the
related regression slice. This does not prove arbitrary mutation callback
cancellation, physical Run STOP, standalone-viewer session synchronization,
REST/SDK lifetime wiring or real authenticated two-tab backend behavior.

```sh
python3 scripts/pnpm.py exec rstest run tests/unit/core/workspaces/cache.dom.test.tsx
python3 scripts/pnpm.py exec rstest run tests/unit/core/features/hooks.dom.test.tsx \
  tests/unit/components/workspace/gateway-offline-banner.dom.test.tsx \
  tests/unit/core/api/static-mode.test.ts
python3 scripts/pnpm.py exec prettier --check src/components/query-client-provider.tsx \
  src/core/auth/AuthProvider.tsx tests/unit/core/workspaces/cache.dom.test.tsx
python3 scripts/pnpm.py exec eslint src/components/query-client-provider.tsx \
  src/core/auth/AuthProvider.tsx tests/unit/core/workspaces/cache.dom.test.tsx --max-warnings 0
python3 scripts/pnpm.py check
```


## Bound REST materialization

`createWorkspaceRESTClient(scope)` captures actor/workspace/lifetime and API root.
Its `fetch()` reuses native credential/CSRF/error handling and scoped transport;
its `json()` additionally retains the exact combined signal through actual JSON
decoding and checks it again before returning data or a GatewayApiError. A late
401 is rejected by the scoped transport before the native login redirect path.
Caller cancellation is combined with the workspace lifetime; explicit signal:null
only removes the original Request's signal. JSON is typed but not schema-validated
by this transport: workspace list/context adapters must validate their responses.

The shared transport now sends the absolute URL it resolved and validated, while
forwarding original native Request bodies/methods. Checking a relative URL and
then sending the raw relative string can select a different browser page/base
path. The existing main reproduces that at a nested chat URL. Foreign origins,
non-API paths and conflicting workspace headers are refused before dispatch.
The scope is request metadata, never membership authorization.

The three node-environment mains use real Request/Response/ReadableStream JSON
decoding with only the outer network replaced. They cover pinned metadata, CSRF,
Request body/signal/null override, dispatch bounds, late HTTP/401 and JSON
completion after workspace or caller cancellation. Native Request/CSRF, static
mode and scoped SDK checks are the related regressions. This is an explicit
REST primitive, not automatic Context/selector integration or real two-tab
server acceptance. Raw Response/Blob readers and caller code performing further
awaits still require their own publication checks.

```sh
python3 scripts/pnpm.py exec rstest run tests/unit/core/workspaces/rest.test.ts
python3 scripts/pnpm.py exec rstest run tests/unit/core/workspaces/request.dom.test.ts \
  tests/unit/core/api/fetcher.dom.test.ts tests/unit/core/api/static-mode.test.ts \
  tests/unit/core/workspaces/sdk.test.ts
python3 scripts/pnpm.py exec prettier --check src/core/api/fetcher.ts \
  src/core/workspaces/request-scope.ts tests/unit/core/workspaces/rest.test.ts
python3 scripts/pnpm.py exec eslint src/core/api/fetcher.ts \
  src/core/workspaces/request-scope.ts tests/unit/core/workspaces/rest.test.ts --max-warnings 0
python3 scripts/pnpm.py check
```

The captured actor ID remains client metadata; fetch credentials come from the
native browser session. A shared HttpOnly cookie can change in another tab while
this tab still holds an old displayed actor. Context bootstrap must compare the
server current-context actor, and M6/M11 must prove cross-tab credential/session
reset and per-request expected-principal consistency before activation. Cache
partitioning and selector capture alone do not prove that property. Include a
case where both actors belong to the same workspace, so a workspace-only guard
cannot mask the identity mismatch. Do not grant authority to a supplied actor
header or infer authentication from the client snapshot.


## Confirmed Context and selection lifecycle

The opt-in WorkspaceProvider reads optional native AuthProvider identity. An
enabled actor gets a separate WorkspaceSession; enabled/no actor is closed,
while disabled/public wrappers preserve existing context or native behavior.
WorkspaceReadyBoundary mounts resources only for confirmed scope and owns that
entry's query cache. Pending/error content never falls back to an unscoped
client. useWorkspaceLifetime refuses resource use outside that ready state.

The fixed GET-only metadata adapter uses native session credentials, no redirect
and no-store. It checks cancellation around response/body completion, validates
canonical workspace IDs/roles/versions, unique own personal membership, and the
current actor/selector/version tuple against the freshly read list. It does not
publish newly fetched names/roles before identity confirmation. Name length
uses Unicode code points to match the native backend. Server metadata is a
projection, never browser-issued authorization. HTTP errors become closed state;
there is no old metadata login redirect and no automatic fallback to another
workspace. Explicit select() can request personal recovery; refresh preserves
the last requested selector.

Every selection immediately aborts the old scope, clears active content and
claims a local epoch. Only its own still-live completion can publish a new
immutable context, fixed REST/SDK pair and fresh cacheKey. StrictMode leases
share initial setup; genuine unmount closes the store permanently. Control
operations are metadata GETs and never create/cancel background Runs.

Three real React/StrictMode mains cover two independent mounted trees, personal
default, one-tree selection, fixed REST/SDK dispatch, fast A→B selection with a
late A response, invalid actor/selector/membership/policy metadata, blocked
resource mount, account/null transitions and a cookie actor change between
list/current reads. These are DOM/network-double tests, not real-browser or
server-authentication acceptance. Nine cache/REST/SDK checks are the related
regressions.

The Context is not yet mounted in WorkspaceContent or a capability bootstrap.
All real resource hooks must consume its fixed clients; query lifetime alone
does not isolate the native artifact panel's sessionStorage bootstrap cache,
thread-local UI stores, React SDK reconnect markers or callbacks after further
awaits. Inventory and namespace/reset those stores during consumer integration.
Selection/manual refresh revalidate; no automatic membership/session watcher
exists in this slice. Cross-tab credential/principal proof after promotion,
actual two-tab backend testing, M4-M11 and activation gates remain required.

```sh
python3 scripts/pnpm.py exec rstest run tests/unit/core/workspaces/context.dom.test.tsx
python3 scripts/pnpm.py exec rstest run tests/unit/core/workspaces/cache.dom.test.tsx \
  tests/unit/core/workspaces/rest.test.ts tests/unit/core/workspaces/sdk.test.ts
python3 scripts/pnpm.py exec prettier --check src/core/workspaces/api.ts \
  src/core/workspaces/session.ts src/core/workspaces/context.tsx \
  tests/unit/core/workspaces/context.dom.test.tsx
python3 scripts/pnpm.py exec eslint src/core/workspaces/api.ts \
  src/core/workspaces/session.ts src/core/workspaces/context.tsx \
  tests/unit/core/workspaces/context.dom.test.tsx --max-warnings 0
python3 scripts/pnpm.py check
```


M3 actual upload consumer checkpoint: frontend #26 RED reproduced the existing
hooks' missing selector and accepted late JSON upload. #27 SUCCESS passes two
real React/StrictMode upload mains plus 19 upload/REST/Context regressions,
modified-file formatting, zero-warning target lint and full pnpm check.
Runtime/test files match the archived source; exact #26-#27 and formatter owned
resources independently empty.

Native upload/list/limits/delete hooks now capture the confirmed lifetime REST
client. Scoped read queries consume TanStack cancellation; the REST client owns
native Response objects in a private WeakMap and consume() checks the captured
combined signal around whole domain decoders, preserving multipart/native
structured errors. Switching aborts a delayed decoded upload and retained old
mutation callback; a new workspace starts an empty observer/cache. Submit helper
also checks lifetime before/after its await. Native unscoped callers retain their
signatures and behavior.

This is actual hook integration, still DOM/network doubles. useThreadStream's
separate direct uploadFiles path and actual SDK/thread reads/submission are next;
app-shell bootstrap/selector, storage/reconnect reset and actual browser/backend
acceptance remain. No real business upload is claimed from this test. M3 and
M4-M11 remain open, activation closed, no deployment/push/local runtime/model.

Shanghai-only commands for this slice:
```sh
python3 scripts/pnpm.py exec rstest run tests/unit/core/uploads/workspace.dom.test.tsx
python3 scripts/pnpm.py exec rstest run tests/unit/core/uploads/api.test.ts tests/unit/core/workspaces/rest.test.ts tests/unit/core/workspaces/context.dom.test.tsx
python3 scripts/pnpm.py check
```


M3 native chat consumer checkpoint: frontend #28 RED reproduced actual missing
thread selectors, stale decoded upload continuing to submit, and shared SDK
reconnect storage. #29 passed two mains but exposed a test-only return-shape
mistake (chat.thread.messages); #30 passed all three mains and 35 regressions,
then exposed two existing isolated options tests' incomplete React substitute.
Their explicit native/no-workspace fixture now supplies null; no production
workaround. #31 passed all 40 tests but target lint refused two test fixture String()
conversions; explicit type narrowing fixed those. #32 SUCCESS passes three mains plus all 37 native/SDK regressions,
five-file formatting, zero-warning target lint and full pnpm check. Runtime/test
bytes match the archive; exact #28-#32 and formatter/SDK-probe resources empty.

Ordinary useThreadStream now captures the confirmed SDK for streaming and agent
metadata. Native per-thread history, metadata, Runs and token-usage reads bind
the matching client; materialized responses are fenced after decode. File
conversion and direct chat upload are checked before/after await, at onSent and
before submit/cache effects. Old stream callbacks cannot notify/update new
content. The native SDK's documented reconnectOnMount storage factory is used
instead of modifying global storage or replacing its runtime. The adapter maps
SDK keys to the existing actor/workspace/thread namespace, refuses stale
lifetime reads/writes/removal and preserves native unscoped markers. Explicit
server admission must still verify current resource/Run identity; markers grant
no authority. Ordinary selection never requests Run cancellation.

New mains use real React/StrictMode, Context, native domain hooks, REST/SDK
clients and the SDK stream parser with network doubles. The external React SDK
useStream adapter is doubled, so actual automatic rejoin/stop/render lifecycle
and browser/backend authorization are not proven. Search/archive/branch/move/
delete/rename and replay/compact still need client/publication binding, along
with project-thread creation, artifacts, remaining resources and storage.
App-shell/bootstrap/native selector and real two-tab acceptance remain next.
M3 and M4-M11 stay open; tenant activation closed, no deployment/push/local
application runtime/model calls. Continue reusing native DeerFlow styling.


2026-10-15 用户暂停：保存本地 WIP，详见 `docs/tenant-workspaces-resume-2026-10-15.md`。前端 #33 三条 RED；#34 的 50 项行为测试、格式和 ESLint 通过，但完整 pnpm check 在 workspace-actions.dom.test.tsx:275 的 nullable metadata 访问报 TS2533，构建 FAILURE。未补跑、未宣称完成。#33/#34 专属容器和网络、actions-format 探针资源均为空。下次先修复该测试类型并完成上海完整检查，然后继续其余客户端/页面调用方/存储/空间入口；全部父验收仍未完成，activation 关闭。用户恢复前不要继续构建、部署或推送。


2026-10-15 resumed at explicit user request. M3 thread-action checkpoint:
frontend #33 RED reproduced missing Run selector, old sidecar lookup continuing
to delete, and archive publication after a delayed cache cancellation. #34 passed
50 tests but full check failed on nullable test metadata (TS2533). #35 SUCCESS
reruns the same three mains and 47 native/chat regressions, four-file formatting,
zero-warning target lint and full pnpm check. Optional metadata access still
requires the archive flag to be true; no type assertion bypass. Runtime/test
bytes match its archive; exact #33-#35 and formatter resources independently empty.

Actual SDK/REST sidebar search, Run detail and branch/pin/archive/move/rename/
delete hooks capture the confirmed clients. Post-decode and post-cache-await
checks stop stale mutation publication and callbacks; lookup cancellation cannot
fall through to best-effort deletion. Scoped deletes use the native canonical
Gateway endpoint, avoiding the previous SDK-plus-fresh-REST double request for
each normally enumerated thread. Native unscoped compatibility and its cleanup
retry regressions remain. These are real hooks with network doubles, not actual
browser/backend or physical STOP proof.

Continue with replay prepare, compact and project-thread creation, then UI
callers' await/toast/router fences (ChatPage branch, delete dialog and sidecar).
The native sidecar API's global inFlightCreates map currently keys only parent
thread ID; scope this by confirmed client/lifetime before activation. Other
resource clients, artifact/thread UI storage, actual shell/selector and backend
browser two-tab acceptance still remain. M3 and all M4-M11 gates remain open;
activation stays closed, no deployment/push/local application runtime/model calls.
The earlier user-pause section is historical; the user has explicitly resumed.


M3 replay checkpoint (2026-10-15): frontend #36 RED found missing prepare
selectors; its retained-callback fixture also held a later request and timed out.
#37 fixes that fixture delay and independently reproduces null selectors and
retained callback dispatch. #38 SUCCESS (20 tests), then formatted final source
#39 SUCCESS (same 20 tests, two-file formatting, zero-warning target ESLint and
full pnpm check). Regenerate/edit prepare uses captured REST with full native
success/error decoding fenced; replay checks entry, prepare return and submit
boundaries. Expired callbacks return the native false result quietly, without
starting Runs or publishing cache/toast effects. Exact source hashes and archive
receipt are in tenant-workspaces-progress.json; #36-#39 and formatter inventories
are empty. These are real hooks with network doubles, not browser/backend proof.
Next: compact/project creation and actual page callbacks, sidecar coalescing,
remaining clients/stores/shell integration. M3 and M4-M11 remain incomplete;
activation stays closed. No remote push, deployment or local runtime testing.


M3 create/compact API checkpoint (2026-10-15): frontend #40 RED reproduced
missing selectors and accepted late-decoded create results. #41 passed 13 tests
but failed TS2322 because test afterEach returned RstestUtilities. Explicit
void cleanup fixes the type without weakening assertions. #42 RED independently
reproduced a real delete dialog callback navigating after a confirmed Context
switch. #43 SUCCESS: two
scoped mains + six native API + five chat hooks + four dialog tests (17 total), formatting,
zero-warning target lint and full pnpm check. Optional fixed REST clients and
whole native response decoding now cover createThread and compactThreadContext;
no-options payload/CSRF/conflict compatibility remains. Exact source/archive
receipts are in tenant-workspaces-progress.json; owned #40-#43 and formatter
resources are empty. Actual ChatPage project creation and InputBox compact
callers still need wiring and post-await UI checks. The actual deletion dialog
now captures its lifetime before dispatch and checks before reset/router,
post-await close and failure toast/log/focus; native failure feedback is kept.
Its external deletion operation is doubled, while #35 covers real deletion hooks.
Network doubles do not
supply real browser/backend/physical acceptance. All parent gates remain open.


M3 actual composer commands (2026-10-15): frontend #44 RED reproduced eight
missing selectors across personal/team goal GET/DELETE/PUT and compact POST.
#45 SUCCESS: 21 tests (13 actual InputBox cases, six native API and two scoped
API), two-file formatting, target ESLint, early tsc and full pnpm check. The
component captures the confirmed REST client, fences full native goal success/
error decoding, passes the client to compact and checks preparation, response
publication and follow-up run boundaries. Native request epochs, permission
gating and prepare→goal-save→run ordering are preserved. Existing late-command
thread cleanup remains effective. Fixture supplies an explicit empty skills
catalog; no localhost server is required. The existing KaTeX happy-dom quirks
warning remains. Exact source/archive receipts and cleanup for #44/#45 and the
formatter are recorded in tenant-workspaces-progress.json. Real component/
Context with HTTP doubles does not prove actual browser/backend authorization.
ChatPage project/branch, sidecar, ancillary input tools, draft/attachment stores,
activity/projects/artifacts and actual shell/browser integration remain. Parent
M3 and all remaining M4-M11 gates stay open; activation stays closed.


M3 actual ChatPage (2026-10-15): frontend #46 RED reproduced missing P/T
precreation selectors, accepted late prepared metadata and retained branch
dispatch. #47 SUCCESS: three real-page/Context mains, formatting, target ESLint,
early tsc and full pnpm check. Native single-user and P/T project creation keep
the same payload. Scoped precreation captures REST and fences entry/decoder/
cache publication; its expired errors do not toast. Send preparation retains
the native conversation epoch and also checks scope. Branch entry/return/error
and reference-attachment URL callbacks refuse expired scopes; the new space's
normal branch still toasts/routes. The page comment now accurately describes
precreation as the membership channel; run requests do not seed projects.

The page and create API are real; leaf UI/stream/branch/catalog operations are
doubled to isolate page callback effects. Native branch hooks and stream/replay
were verified separately in #35/#39, and actual InputBox commands in #45. This
does not supply actual browser/backend/physical acceptance. Exact source/
archive receipts and empty #46/#47/formatter inventories are recorded in
tenant-workspaces-progress.json. Next: sidecar as one bundle (fixed SDK lookup,
REST-client-keyed in-flight creates, guarded restore→create→queued-send and
delete/trigger publication), then activity/resources/stores/shell/browser.
All parent gates remain open; activation remains closed.


M3 sidecar scoped lifecycle checkpoint (2026-10-15): #48 main RED reproduced
unscoped restore lookup; #49 main GREEN (seven cases) came before lifecycle
expansion. #50 was an observer-fixture failure, not behavior evidence. Removing
module wrapping and observing actual API coalescing/MutationCache yielded #51:
main passed, but pending P creation blocked T and late P delete toasted in T.
#52 passed 13 behaviors/format, then failed import/rejection lint; #53 passed
behaviors/target lint, then early typecheck rejected a bound-query generic.
A real textarea check fixes the type without a cast. #54 SUCCESS: same 13
cases, six-file formatting, target lint, early tsc and full pnpm check.

The actual provider uses fixed SDK lookup with post-JSON fences. Creation uses
fixed REST/owned decoding, and per-client WeakMap namespaces retain same-life
coalescing without blocking another actor/workspace/reset lifetime. The panel
checks restore→create→queued first-send and send/delete publication. Scope
expiry rejects queued submit with typed AbortError and removes its listener;
stale errors do not toast. Trigger opening checks lifetime after restoration.
The main preserves P/T reference contents and normal T deletion; native API
and four draft/send regressions remain. HTTP replies/React SDK adapter and
peripheral catalog/router/toast are doubled, while core hooks, composer, SDK
SSE parser/transport and REST remain real. Existing KaTeX warning is retained.
No real browser/backend/model/physical acceptance is implied. Exact receipts
and empty #48-#54/formatter inventories are in tenant-workspaces-progress.json.

Remaining M3 audit includes same-space parent navigation/unmount: native
ChatBox remounts panels through MessageDetailsProvider keyed by threadId, but
SidecarProvider is outside it. Late callbacks and queued/quiet stream gaps
still need targeted UI/fault proof before activation. Continue with activity
clocks/timers, project/artifact clients, direct links and UI stores; then actual
shell/selector and browser/backend two-tab acceptance. Preserve all M4-M11
gates; activation stays closed. No deployment, remote push or local runtime.


M3 activity/read frontend checkpoint (2026-10-15): #55 RED reproduced an
unscoped activity GET; #56 main GREEN (21 cases) preceded the additional
lifecycle case. #57 SUCCESS: 22 cases (two new, 20 native regressions),
two-file Prettier, target ESLint, early tsc and full pnpm check.

Both hooks capture their confirmed REST lifetime. Polls combine Query/workspace
cancellation, fence cursor/clock updates and invalid-cursor recovery. Read
callbacks/timers refuse expired scope, and late read success/errors cannot
update clocks or invalidate lists. Native 15s polling, 1s read debounce, cursor
reseed and monotonic read versions remain. The P/T main uses real Context,
hooks and REST with synthetic HTTP. A held old GET and POST JSON pair is
released after selecting T: reset P state stays empty, old callbacks cannot
POST, and T reads continue. Feature/router fixtures are doubled; this is not
actual browser/backend/principal or physical isolation acceptance.

Source hashes match the final archive, with exact build/formatter resource
inventories empty. See frontend_thread_activity in the progress JSON. Next:
same-space sidecar parent/unmount faults, project/artifact clients/direct URLs
and UI stores, then shell/selector and browser/backend two tabs. M3 remains
partial; all M0-M11 parent gates remain open and runtime activation stays closed.
No deployment, remote push, model call or local runtime was performed.


M3 project/shelf client checkpoint (2026-10-15): #58 RED reproduced project
reads without a selector; #59 main GREEN (39 cases) came before adding one
lifecycle scenario. #60 passed all 40 behaviors but Prettier caught two await
method-chain layouts. Reformatting the same source package showed only those
test-layout changes. #61 SUCCESS: 40 cases (two new, 38 native regressions),
three-file Prettier/target lint, early tsc and full pnpm check.

All 16 native project API functions accept optional fixed REST/signal options;
15 native hooks bind the confirmed lifetime, combine Query cancellation and
workspace abort, and suppress stale onSettled invalidations. Preserve native
request bodies/arguments/errors and full preview Range/text/empty/PDF/binary
decoding inside the response lifetime. No new project execution service exists.
The real Context/hooks/REST main runs P/T project reads/writes, shelf upload,
preview, thread attach/promotion, archive/restore and deletion. Delayed old
upload JSON/preview byte decoding rejects after selection; a retained old
delete cannot dispatch and T upload still works. HTTP replies/router are
fixtures, not actual page/browser/backend or physical authorization proof.

Final source hashes match the verified archive; exact #58-#61 and formatter
resource inventories are empty. Detailed receipts: frontend_project_clients
in progress JSON. Next bind actual project/shelf/settings/sidebar/move-menu
callbacks and preview effects, including same-space project navigation
(the shelf currently has no project key); then document/artifact URLs, relative HTML
assets and remaining UI stores. htmlBaseHref currently strips search, so
adding a workspace query only to a top-level HTML URL cannot scope relative
assets. Preserve the native safe preview architecture and verify that chain.
Same-space sidecar parent/unmount/quiet-stream, actual shell/selector/two-tab
and principal acceptance remain; M3 is partial, all parent M0-M11 gates stay
open and activation remains closed. No deployment, Git remote push, model
call or local runtime was performed.


M3 shelf/composer handoff checkpoint (2026-10-15): #62 main RED showed
preview-null in the actual preview dialog. #63 main GREEN (42 cases) came
before two lifecycle scenarios; its new duplicate sibling keys were spotted
in console and corrected to distinct shelf/files keys. #64 passed 108
behaviors/format, without the key warning, then target lint rejected a test
fixture match() boolean. Replacing it with test() changes no production bytes.
#65 SUCCESS: 108 cases (three new, 105 existing), five-file Prettier/target
lint, early tsc and required full pnpm check. Source hashes match the final
archive; #62-#65 exact owned resources and formatter inventories are empty.

The native attachment list persists per actor/workspace/thread and captures
an immutable lifetime; expired handles cannot read/write/retire it. Native
unscoped keys stay unchanged and are never adopted. Mounted setters also
fence thread/store identity. The real shelf stages into this store; InputBox
reads it and retires sent files using the captured store, with onSent scope
fencing. File-mention prepare/attach awaits use captured REST and guard stale
continuations while native mention behavior stays covered by its regressions.

The actual preview effect uses fixed REST plus scope/effect cancellation.
Document row download and preview iframe/full-file URLs carry the existing
workspace_id selector; it is not a credential. Cached project navigation
remounts distinct shelf/files views; current-view guards stop later files in
an old multi-file loop and stale state/toast/router/save/attach publication.
P/T/P main proves own draft persistence, actual attachment-only composer
submission, legacy isolation and scoped preview/link selection. The two
additional scenarios observe actual old mutation state and old onSent, and
stop an old file loop after navigation while current project upload works.
The first old upload may finish in its original project; no remote STOP or
rollback is claimed. HTTP/router/model/toast/preview-leaf and final onSubmit
are doubled; no real backend/browser download, iframe or Run proof implied.
Existing Radix/KaTeX and native iframe fixture network/cleanup warnings remain;
the newly introduced duplicate-key warning is fixed.

Next: actual settings/sidebar/create/move-menu callbacks, composer text/
reference drafts and other UI stores; explicit scoped file-picker/focus race
proof; artifact/direct/relative HTML and standalone views, then actual shell/
selector/browser/backend two-tab acceptance. Same-space sidecar faults and
principal/session/revocation remain. M3 is partial, every M0-M11 parent gate
remains open and activation stays closed. No deployment, Git remote push,
model call or local application runtime was performed.


M3 composer drafts/native project workflow checkpoint (2026-10-15): #66 RED
proved a scoped composer restored Legacy personal notes from an unscoped
key. The separate project-page fixture hit a label ambiguity (Instructions
tabpanel and textbox); querying the actual textbox fixes the fixture. #67
main GREEN (21 cases: two new, 19 existing) preceded lifecycle expansion.
#68 passed 78 behaviors/format but target lint rejected unknown test-field
string coercion; typeof narrowing fixes only the fixture. #69 SUCCESS:
78 cases (three new, 75 existing), eight files, three-file Prettier/target
lint, early tsc and required full pnpm check. Production bytes match #68;
source/archive hashes and exact empty #66-#69/formatter resource inventories
are captured in frontend_composer_drafts in progress JSON.

The text/reference draft namespace is disjoint from legacy keys and binds
actor/workspace/agent/thread. Captured Storage handles refuse foreign or
legacy keys and all access after expiry. InputBox hydration, save, flush,
retirement/clear and new-thread file-reference transfer use this client/key.
Scoped edits persist the visible snapshot while active: selection aborts
before React cleanup, so relying on a final expired flush would lose the
latest keystrokes. Native unscoped keys, 300ms debounce, disabled-storage
behavior and draft reconciliation stay unchanged. No automatic legacy
adoption occurs. Current namespace remains persistent across own remounts;
old handles cannot change a fresh lifetime's same-space replacement.

Positive UI verification reuses ProjectPage, ProjectsSection and
NewProjectDialog unchanged: P/T instructions editing, rename, archive/restore,
sidebar create, create-then-move and delete navigation pass through real
project/thread hooks and REST. No replacement project UI or extra mutation
layer was necessary. Their unchanged source hashes are recorded alongside
the code changes. Real InputBox P/T immediate switching preserves own draft;
old onSent and expired/foreign Storage cannot clear replacements; stored
reference metadata restores its own chip after P/T/P. HTTP/catalog/router/
toast, layout/document/thread leaves and final onSubmit are fixtures; this
is not actual backend/browser/Run/principal authorization proof. Existing
KaTeX/Radix warnings remain; production styles were not changed.

A bounded existing-image browser inventory (uid 999:987) found no standard
PATH browser or four common cache/install directories; probe exit 0 and
owned resources empty. This does not inventory other images/host/custom or
inaccessible caches; inspect reusable tools before preparing browser gates.

Next: artifact clients/direct/relative HTML/standalone/iframe URLs and remaining
UI-store/global-title audit, explicit scoped file-picker/focus and same-space
sidecar faults, then actual shell/capability/selector and browser/backend
two-tab acceptance. Positive project UI workflow is not every publication
fault. Principal/session/revocation and all M4-M11 gates remain. M3 is partial,
every parent M0-M11 gate stays open and activation remains closed. No
deployment, Git remote push, model call or local application runtime ran.


M3 artifact panel checkpoint (2026-10-15): frontend #70 RED reproduced an
unscoped native artifact read (Report-null-thread-1). #71 main GREEN first:
35 tests (one new, 34 existing), real P/T native detail read/revision save and
archive download plus legacy panel-state non-adoption. Native archive UI
appears only above one file, so the manifest fixture correctly lists two.
Only then add two lifecycle scenarios. #72 passed 50 tests/format; target
lint found four import-order issues and one redundant assertion. #73 SUCCESS
passes the same 50 tests (three new, 47 existing), eight files, nine-file
Prettier/target lint, early tsc and required full pnpm check. Exact archive/
source/image IDs, terminal timings and empty #70-#73/formatter inventories
are recorded in frontend_artifacts in progress JSON.

Native byte/range/ETag/hash/416 preview, revision PUT/error handling, archive
manifest and Blob decoding now accept the captured workspace REST client.
The whole native decoder, including awaited bodies/hashing/errors, is inside
consume; queries retain cancellation. Native unscoped argument counts,
payloads/methods/decoder semantics and styles remain. Save/ZIP completion,
toasts/cache/draft writes and pending flags belong to one mounted resource
incarnation; same-space navigation and A/B/A cannot revive an old callback.
Panel storage is a disjoint actor/workspace/path namespace, never adopting
legacy data. Retained context setters and beforeunload/persistence callbacks
are fenced. Route transitions reset this provider's state without keying/
remounting its chat subtree; draft buffers stay in memory.

The two added scenarios verify delayed same-space save/ZIP decoders and
retained panel callbacks do not touch a replacement view; its new save/ZIP
still work. A separate deterministic client check releases byte/JSON/Blob
decoders after workspace switch and observes AbortError. Real components/
providers/hooks/REST execute against HTTP/catalog/router/toast fixtures and
editor/preview leaves. This is not live ChatPage/Run, backend authorization,
actual ZIP extraction, browser-download or HTML resource proof. Native iframe
cases log happy-dom fetch/abort teardown output; archive rejection logs and
KaTeX warning remain. A detached save may already have reached the server;
no remote cancellation is claimed.

A read-only inventory found the existing DeerFlow browser-mcr image; its
custom /opt/deerflow-browsers installation is documented in native scripts
and historical #41. Prior PATH/standard-directory absence was only a bounded
probe. Fresh exact-image native distribution verification passed as uid/gid
1000:1000, network none: Chromium 149.0.7827.55 launch/input/PNG, owned
resources empty. This proves browser tooling only, not DeerFlow page/backend
acceptance. No image download.

Next: direct/standalone/new-window/media/Markdown and nested HTML/CSS URLs,
remaining UI stores/title/focus/sidecar faults, then real shell/capability/
selector and browser/backend two-tab proof. Artifact skill installation is
a separate operator/M5 authority boundary. All M0-M11 parent gates remain
unchecked; M3 is partial and startup activation remains false. No deployment,
Git remote push, model call or local application runtime occurred.


M3 standalone artifact/locator checkpoint (2026-10-15): backend #90 RED
missing workspaces capability; #91 GREEN 23 feature API tests (one new), actual
FastAPI startup-state projection, no database gate needed. Frontend #74 RED
reproduced the unbound original standalone renderer; #75 main GREEN first
(47 tests: one new, 46 existing). Only then add two boundary scenarios. #76
passed 75 behaviors/format/target lint but early tsc rejected an unsupported
fixture ByRoleOptions.exact. It was already FAILURE when the stop helper
inspected it; no stop request was sent and it was not aborted. #77 RED in the
same three-case suite proved auth-disabled development incorrectly entered
workspace mode (two passed, one failed). Reuse the native operator predicate
to retain that supported non-tenant path, and fix the test query option.
#78 SUCCESS: 75 tests (three new, 72 existing), nine files, 19-file format/
target lint, early tsc and required full pnpm check. Backend source still
exactly matches #91. Exact source/archive/image/terminal/empty resource
receipts are in frontend_artifact_windows in progress JSON.

The read-only /api/features workspaces block reports isolation requirement
separately from service presence. It cannot activate the runtime. A standalone
page reads server capability with the native cookie, no-store, refused redirects
and a body-spanning timeout. A URL selector is only a locator. Its requested
workspace is pinned before content through the existing catalog/current
handshake, actor/target-keyed provider and per-lifetime ReadyBoundary cache.
The original renderer and styles remain; the scoped AuthProvider is actor-keyed.
Malformed/duplicate selectors, mock+workspace, missing required service, failed
capability or denied current membership cannot fall back to an unscoped read.
Legacy JSON without the optional block remains native, while a scoped locator
on a legacy server is refused. Public allowlisted showcase and supported
auth-disabled/static flows retain native behavior. Workspace locators survive
viewer build/parse and login next; panel/source/download/list/fallback/PDF
top-level URLs now include only the confirmed locator. Entry-stale panel
open/download actions are inert. Existing panel main checks both actual window
open calls and their selectors. No second file/auth service was added.

Positive P/T real renderer/route-function/Context/REST and body-held old actor
replacement, login target preservation, refusal paths and native developer/
legacy compatibility execute against HTTP fixtures. SSR auth/cookies/router/
locale are mocked. This is not compiled Next RSC, actual JWT/session/principal
revocation, real browser/window/download HTTP, physical NAS or model proof.
Native iframe teardown abort/fetch output, expected archive rejection logs and
KaTeX warning remain. Previous actual backend file receipts are independent.

Next: Markdown/message image resolvers, browser/change-panel artifact links,
then nested HTML/CSS relative resources and real browser/cookie/backend
acceptance. Main shell capability/selector, remaining UI-store/title/focus/
sidecar faults and all M4-M11 remain. Every parent gate is unchecked, M3 partial
and startup activation false. No deployment, Git remote push, model call, local
application runtime or new image download occurred.


M3 message/report resource checkpoint: frontend #79 RED reproduced the real
message link's missing workspace locator. Its HTML compiler diagnostic also
failed before browser launch because it lacked the existing pnpm symlink; fix
that fixture prerequisite. #80 main GREEN first: 28 tests (one new, 27 native).
Then add only two boundary scenarios; #81 GREEN: six tests (three new and the
three existing artifact lifetime cases). #82 kept Streamdown's default image
renderer via its native defaultUrlTransform interface: 53 passed, one boundary
failed because native Streamdown omits a rejected image instead of emitting an
empty-src img. Preserve that native behavior and correct the same assertion;
the positive main now requires native image/image-wrapper markup as well.
#83 passed 54 behaviors/format but was actively stopped (ABORTED) after review
found file citation links bypassing scope. #84 RED reproduced this by extending
the same main with /mnt and raw native file citations (two boundaries passed).
Resolve scoped file locators before native citation early returns, retaining
unscoped behavior. #85 SUCCESS: 54 tests (three new, 51 existing), 11 files, 15-file format/
target ESLint, early full tsc and required full pnpm check. Exact source/archive/image/
terminal/empty-resource receipts: frontend_resource_surfaces in progress JSON.

Native /mnt and configured-Gateway raw artifact links, message/upload/report
images, tool/static browser screenshots and file-change links use captured
workspace locators. Preserve query/hash/literal percent names and native safe
link/citation guards. Content-authored duplicate/foreign selectors are replaced,
web references remain unchanged, and scoped relative report paths cannot escape
the source thread file route. Scoped successful write_file preview derives its
source base too. Streamdown's default URL safety and original image renderer/
controls remain, without overriding img. Feedback and file changes share the
whole-decoder fixed REST helper (artifact API aliases preserved). No-options
legacy API calls retain native payload/error semantics; DELETE404 clears local
feedback as before. Same-space route changes cannot publish old feedback or
reset a new pending indicator; obsolete change reads are cancelled and cannot
publish into their old query. Real providers/REST/components use HTTP/router
fixtures; live browser stream is doubled. Native Streamdown paragraph/image
nesting, happy-dom teardown and KaTeX warnings remain; actual browser hydration
is not accepted. These are not actual Gateway/Next/
browser/principal/physical authorization proofs. Live WSS/navigation is open.

The new repeatable scripts/tenant_artifact_html_probe.py transpiles archived
unchanged native preview helpers in the pinned CI image and runs Python
Playwright in the pinned Chromium149 image, network none. Synthetic HttpOnly
SameSite=Lax cookie and strict container-local file/scope fixture only. The
parent image positive control succeeds. Native query-base and fixture-only
path-prefix candidates fail image/CSS/fetch; cookie is absent in the opaque
iframe (query selector is also dropped by native base handling). Parent-made
Blob assets fail too. Parent authorized byte reads transferred into iframe-made
Blobs load image, stylesheet and JSON. #81/#82/#83/#85 retain all four observations;
#80 had the first two candidates. This is a transport experiment, not implemented
product HTML/Gateway acceptance. Keep sandbox allow-scripts allow-forms with
allow-same-origin absent and native Cookie policy unchanged. Production source
validation, nested CSS/dynamic requests, lifecycle cancellation and Blob cleanup
still need implementation and real-browser verification. No production alias
route was added.

Next: bind CitationSourcesPanel native file source links/copied references and
its pending clipboard publication, then implement scoped HTML resource delivery
through captured parent REST and actual shell/selector/browser/backend acceptance.
Remaining UI stores/title/focus, sidecar faults, browser live transport, M4-M11
and physical/principal/revocation gates remain. M3 partial, every parent gate
unchecked, runtime activation false; no deployment, remote push, model call,
local application runtime or new image download.

Staged whitespace check then caught four blank-line spaces inside the diagnostic
script strings. Remove only those spaces; all 15 frontend files still exactly
match #85. The cleaned script's four browser observations were reverified in
pinned Shanghai containers with empty owned resources, directly on Jenkins host
(not a new Jenkins build). Full frontend checks were not repeated. Exact script/
archive hashes and results: frontend_resource_surfaces.post_gate_probe.


M3 source-list references checkpoint: frontend #86 RED extended the existing
main and reproduced a source-list link retaining a foreign content-authored
selector. #87 main GREEN first: eight tests in two files, including five native
source-panel SSR/style/locale regressions. Actual message/report lists link and
copy in P/T through native parsing, reference formatting and clipboard helper;
external web sources keep their original URL/text. No new cases were added.
Then extend the same two existing boundary cases: old same-space copy completion
and an expired workspace/clipboard failure, plus an unbindable native source.
#88 controlled regression omits only the new artifact owner's resourceKey with
locator binding retained: two reports cite the same URL, and the old copy adds
a second toast after a new-view copy (one failed, two passed). Restore the owner
key. #89 SUCCESS: 59 tests/12 files, four-file formatting/target lint, early full
tsc and required full pnpm check. The same three integration cases were extended,
with 56 unchanged regressions; zero additional cases. Source/archive/image/
terminal/empty-resource receipts: frontend_source_references in progress JSON.

Source-list file hrefs and copied Markdown use the confirmed locator; unbindable
native file links are inert with copy disabled. Native layout, counts, locales,
formatter and clipboard fallback stay. Both actual callers pass the owning
thread/message or artifact scrollKey/active identity. Copied feedback, success/
error publication and timers belong to that source/view/workspace incarnation;
old cleanup cannot clear a replacement timer. HTTP/router/clipboard wires are
doubled, and source details are opened in the DOM fixture. This does not prove
OS clipboard cancellation, browser permissions/downloads, compiled Next/hydration,
live backend/principal/two-tab or physical isolation. Already-issued clipboard
operations cannot be undone; guards protect UI publication. Native paragraph/
image nesting and KaTeX warnings remain. Existing HTML helper/probe code is
unchanged and was not rerun; its prior transport evidence is not product HTML
acceptance.

Next: scoped HTML resource delivery through captured parent REST into iframe-
owned bytes, retaining native sandbox/Cookie policy, then source validation,
nested CSS/dynamic requests, disposal and actual browser/backend acceptance.
Main shell/selector, UI stores/title/focus/sidecar faults, live browser transport
and M4-M11 remain open. M3 partial, every parent gate unchecked, activation
false. No deployment, remote push, local application runtime, model call or new
image download.


M3 HTML parent-read foundation: frontend #90 is a missing-feature build RED
(new reader module absent, zero tests executed), not a network failure. #91
main GREEN first: 14 tests (one new byte main, 13 existing URL regressions).
#92 GREEN: 16 tests after only two boundary scenarios. Extend the same refusal
case for encoded structural paths: #93 RED (two passed, one failed) shows literal
prefix validation accepted a path that can normalize outside the thread route.
Inspect structural normalization without rewriting actual filenames; safe literal
percent names remain. #94 passed behaviors/format/target lint, but early tsc rejected an implicit
RstestUtilities return from test afterEach (TS2322). Use an explicit void body;
production code remains unchanged. #95 SUCCESS: 28 tests (three new, 25 existing), four files,
three-file format/target lint, early full tsc and required full pnpm check. Exact
source/archive/image/terminal/empty resources: frontend_html_resource_reader.

The new reader snapshots native source/lifetime scope/rest, reads only that
thread's configured-Gateway files through existing GET/no-store/whole ArrayBuffer
decoding, and returns bytes/MIME/status/locator without response credentials or
headers. Invalid/external/API/foreign-thread and normalized escape targets are
refused before send. Source/client mutation cannot retarget an existing reader.
Per-read abort, report dispose and workspace abort reject held byte decoders;
report disposal leaves other reports and the workspace alive. Native HTTP404
status remains typed. Pure Node HTTP-wire tests do not prove real proxy/backend,
principal revocation, browser rendering, React lifecycle or physical isolation.
This is source identity binding, not an atomic multi-file revision snapshot.

Important: this reader is not yet connected to the production iframe renderer;
HTML resource loading is still unaccepted and retains its previous behavior.
Next wire it through a document/source-bound channel and child-owned byte/Blob
delivery, implementing nested CSS, local scripts/module graphs, dynamic data
requests and disposal. Verify an actual Chromium rich-report main before needed
fault boundaries. Keep sandbox and Cookie policy unchanged. Main shell, actual
backend/two-tab/principal, remaining UI/live-browser and all M4-M11 gates remain.
M3 partial, parent boxes unchecked, activation false. No deployment, remote push,
local application runtime, model call or new image download.


M3 native HTML byte bridge checkpoint (2026-10-16): #96 compiled/mounted the
native React fixture, but a Playwright variable error prevented full assertions;
it is not a clean domain RED. Correct only that predicate: #97 RED shows both
P/T parent controls render while private iframe image/CSS/script/data fail.
#98 GREEN first: actual production preview/parent reader/private channel/child
Blob integration renders both rich-report mains and refreshes local GET data;
16 existing regressions pass. Only then extend the browser fixture with held
read hide/reopen and read-only API/foreign-thread/fetch-POST refusal. #99 SUCCESS:
all browser observations pass, forbidden network hits empty, and 40 existing
Rstest cases/five files pass. Zero new Rstest cases. #100 SUCCESS on formatted
sources: same browser main/boundaries and 40 regressions, seven-file formatting/
target lint, early full tsc and required full pnpm check. A separate temporary
formatter's default 1GiB typecheck exhausted heap; final gate uses the established
1536MiB setting. Exact archive/source/images/terminal/empty-resource receipts:
frontend_html_resource_bridge in progress JSON.

Native scoped ArtifactFilePreview now uses one document/view/lifetime-bound
MessageChannel. Parent captured REST grants only the existing same-thread native
file GET boundary; child gets bytes/MIME/status/locator, never credentials or
raw response headers. parse5 prepares inert HTML; PostCSS/value-parser prepare
nested stylesheet references. Child-owned Blobs keep opaque sandbox isolation
while supporting the tested image/nested CSS/classic script/local fetch main.
Reinstall runtime after document.open clears listeners, before author scripts.
Close/abort/revoke on retirement; hidden/replaced documents cannot own the shown
URL. Scoped scroll keys use a document nonce; legacy behavior stays on its path.
Keep allow-scripts/allow-forms without allow-same-origin, Cookie policy unchanged.

Limits: actual Chromium bundles native React/Auth/Workspace/REST with env/router
build doubles and an HttpOnly Cookie/scope HTTP fixture, not Next/Gateway/SQL/NAS
or live JWT/principal/two-tab/revocation proof. Native Streamdown paragraph/div
and KaTeX DOM warnings remain. General HTML support is unaccepted: next complete
local ESM/import graphs, dynamic elements/srcset/XHR and CSS/media/error fidelity,
including known external-base/fragment, CSS-cycle and malformed-style handling.
Then compiled Next/actual backend acceptance and shell/selector/remaining UI/live
browser gates. All M0-M11 parent gates remain unchecked, M3 partial, activation
false. No deployment, remote push, local application runtime, model call or new
image download.

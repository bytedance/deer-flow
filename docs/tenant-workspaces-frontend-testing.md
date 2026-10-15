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

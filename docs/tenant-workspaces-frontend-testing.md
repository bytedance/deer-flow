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

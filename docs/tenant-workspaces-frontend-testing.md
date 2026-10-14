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

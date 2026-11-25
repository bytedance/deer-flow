# Frontend (`frontend/`)

The Next.js web interface: threads, streamed runs, artifacts, the workspace and
its settings, and the documentation site. The directory map is in
[README.md](README.md#project-structure). Visual and accessibility rules are in
[DESIGN.md](DESIGN.md); read it before UI work.

Feature rules live next to the code. Read the guide for the area you change:

| Area                                                                    | Guide                                                                                                            |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Data flow, threads, streaming                                           | [src](src/AGENTS.md)                                                                                             |
| Model picker, artifact previews, Capability Center, plugin UI, composer | [workspace](src/components/workspace/AGENTS.md), [browser view](src/components/workspace/browser-view/AGENTS.md) |
| Model catalog and settings                                              | [core/models](src/core/models/AGENTS.md)                                                                         |
| Authentication, admin user management                                   | [core/auth](src/core/auth/AGENTS.md)                                                                             |
| Memory, background tasks                                                | [core/memory](src/core/memory/AGENTS.md), [core/background-tasks](src/core/background-tasks/AGENTS.md)           |
| End-to-end tests                                                        | [tests/e2e](tests/e2e/AGENTS.md)                                                                                 |

## Verify

```bash
cd frontend
pnpm check                    # ESLint and TypeScript; run before you commit
pnpm test                     # Rstest unit tests
pnpm rstest run <pattern>     # one unit test file
pnpm test:e2e                 # Playwright, Chromium
```

Other scripts are in `package.json`. From the repository root, host pnpm calls go
through `scripts/pnpm.py`.

## Tests

- **The file name selects the environment.** `*.test.*` runs in Node and is for
  logic. `*.dom.test.*` runs in happy-dom and is for components and hooks. Keep
  logic out of the DOM suite, which is about three times slower.
- **Test effect order, unmount cleanup and store re-renders with real React and
  a DOM**, not with a mocked hook.
- **Real animation is tested in Playwright.** happy-dom rejects a cancelled
  animation's `finished` promise, and rejection reporting stays enabled.
- **E2E tests mock the backend with `page.route()`** and drive real navigation,
  input and streaming.
- **A new permission is registered in two contract tests**:
  `tests/e2e-real-backend/auth-disabled-contract.spec.ts` and
  `backend/tests/test_auth_me_permissions.py`. Both hold the complete list.

## Conventions the tools do not enforce

- **Public shares stay outside the workspace auth layout.** Read snapshots
  without session credentials, rewrite file links through their manifest, and
  authenticate only when importing into a workspace. See
  [sharing](../docs/guide/sharing.md).
- **`src/components/ui/` and `src/components/ai-elements/` are generated** from
  component registries. Change them by regenerating, because a manual edit is
  lost on the next update.
- **Webpack is the development bundler.** `DEER_FLOW_DEV_BUNDLER=turbo pnpm dev`
  is for diagnosis.
- **Use `cn()` from `@/lib/utils`** for conditional class names, and inline type
  imports (`import { type Foo }`).

## Environment

- **Leave `NEXT_PUBLIC_BACKEND_BASE_URL` and `NEXT_PUBLIC_LANGGRAPH_BASE_URL`
  unset** for `make dev` and Docker. Nginx serves `/api/langgraph/*` and rewrites
  it to the Gateway routes. Set them only to reach a Gateway directly.
- **Development access from another host needs `DEER_FLOW_DEV_ALLOWED_ORIGINS`.**
  Without it Next.js answers `/_next/*` with 403, the page does not hydrate, and
  login appears broken. Production ignores the setting.
- **Windows development binds `127.0.0.1`**, because Hyper-V port reservations
  make the wildcard bind fail. For LAN access run
  `pnpm dev -- --hostname 0.0.0.0`.
- **`make build-static` produces a read-only demo.** Gateway reads come from
  bundled fixtures, and writes fail locally.

File attachments use typed session errors, preserving per-file causes independently
of display text. Preview and upload ownership, Office worker budgets and resource
regressions: [file preview ownership](docs/file-preview-ownership.md).

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

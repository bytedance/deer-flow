# Phase-4 knowledge center validation

## Library completion on 2026-11-02

This follow-up to merged #7518 completes the remaining capability-aware phase-4
page surfaces: document directories and processing filters, Wiki browsing/editing/
historical preview/guarded restoration, and real entity-relation graph queries.
The independent branch is based on upstream main
`3f86f071f3d26cb3fcf91841523f6f7be2796914`. Validation used Windows,
Python 3.12.15, Node 24.16.0 and the pinned pnpm environment.

| Check | Actual result |
| --- | --- |
| Library, center, management, platform and guidance backend tests | 171 passed, including 37 new library cases |
| Complete strict blocking-I/O suite | 363 passed, 8 skipped |
| Frontend extension/API unit tests | 192 passed |
| `pnpm check` | Passed: ESLint and TypeScript |
| Backend and extension Ruff formatting/lint | Passed |
| Production `next build --webpack` and search index | Passed; index scanned 137 pages |
| Knowledge-center and existing bookmark/business-plugin/icon browser tests | 36 passed (17 knowledge-center plus 19 existing regressions) |
| Final knowledge-center browser run after screenshot viewport adjustment | 17 passed |
| Guidance checker | 0 errors, 13 soft-limit warnings |
| Three 0.1.1 wheels and sdists; isolated installed-wheel smoke | Passed: entry points, LightRAG factory, library routes, all 7 browser assets byte-compared with source, no Python cache files in archives |
| `git diff --check` | Passed |

The backend cases cover opt-in grants, unchanged ingestion-only Providers,
post-capability and post-response policy revocation, response/resource identity,
version conflicts, real historical snapshot restoration, strict response limits,
credential-bearing or oversized editable content, graph identity and exact evidence
joins. Browser cases cover English/dark desktop and Chinese/light 375px mobile,
directory query parameters, draft and pending-input locks, historical preview,
confirmed restoration, uncertain-write reconciliation, bounded graphs and a late
directory response after cancellation. The new screenshot artifacts show synthetic
data in the actual host, including the sidebar entry point:

- [English desktop, dark](screenshots/library-en-dark.png)
- [Chinese mobile, light](screenshots/library-zh-mobile.png)

WeKnora routes and version semantics were checked against v0.8.3 source commit
`3e22822c1d2397be730c458c7539d0eb8c113a24`. The optional LightRAG graph adapter
uses the existing v1.5.7 `/query/data` shape. HTTP tests use synthetic responses;
**no live WeKnora/LightRAG acceptance or production deployment is claimed**.
WeKnora has no stored entity-query API in that version; its Wiki page-link graph
is deliberately not substituted. Unsupported capabilities remain explicit.
Processing controls project document states, not a global queue/attempt ledger.
Phase 5 Trace remains separate.

The baseline itself exceeded four hard guidance budgets. Minimal wording
compression in backend/Gateway guides preserves the documented invariants and
restores the hard checks; the 13 remaining warnings are soft limits. The entire
monorepo suite was not rerun, and historical broad-suite results below describe
only the earlier slice. Native Windows SWC remains blocked by local application
control, so the production build used Webpack. `make` is unavailable; equivalent
formatter/linter/test commands were executed directly.

Reproduction from `backend/`:

```sh
uv run --no-sync pytest tests/test_knowledge_library.py tests/test_knowledge_center_extension.py tests/test_knowledge_management_extension.py tests/test_knowledge_platform_extension.py tests/test_agent_guidance_check.py -q
uv run --no-sync pytest tests/blocking_io -q
uv run --no-sync ruff format .
uv run --no-sync ruff check .
```

From `frontend/`, use `pnpm check`,
`pnpm exec rstest run tests/unit/core/extensions tests/unit/core/api`, and the
production build/browser commands recorded below. The final browser host used
port 3107. Build each example package with `uv build`; install all three wheels
with the extension API into a separate environment before checking entry points,
routes and manifest asset contents.

## Historical first-slice validation

The following records apply to #7518, not to the current completion branch.

## CI follow-up on 2026-10-26

The initial GitHub run passed frontend unit tests, all four browser shards,
both replay-contract layers, package checks, blocking-I/O, lint, and backend
shards 1/2/4. Backend shard 3 reported 9,607 passed and one guidance-budget
failure: the merged runtime chain was 99,004 bytes against the 98,304-byte limit.
Upstream reproduced and fixed that same failure in #7522. Main at
`3d5107dc0dd13a1f83b696b6682483aea64da896` was merged into this branch;
the guidance checker now reports **0 errors and 0 warnings**. The combined
guidance/extension/auth/platform/bookmark regression passes **139 tests**;
backend Ruff formatting and lint pass. Frontend extension unit tests remain
**100 passed**. This records local follow-up evidence;
the new head's remote CI result must be checked separately.

Validated on 2026-10-25 on Windows with Python 3.12.15, Node 24.16.0 and pnpm 10.26.2, based on `885062e197d53abb771e6c3cd1fb1223e45e9bbb` (including phase 3, #7417).

## Passing checks

| Check | Actual result |
| --- | --- |
| Backend extension, authentication, platform, bookmark and platform blocking-I/O tests | 125 passed |
| Complete strict blocking-I/O suite | 277 passed, 8 skipped |
| Guidance and new knowledge-center tests after registering the new guide | 23 passed |
| Frontend extension unit tests (11 files) | 100 passed |
| Frontend API unit tests | 87 passed |
| `pnpm check` | Passed: ESLint and TypeScript |
| Changed TypeScript and shipped native-module/style formatting | Passed |
| Backend `ruff format .` and `ruff check .`, plus new package | Passed |
| `next build --webpack`, then `node scripts/build-search-index.mjs` | Passed; search index scanned 137 pages |
| Knowledge-center Chromium tests against production server | 11 passed |
| Existing bookmark, business-plugin and plugin-icon browser regressions | 19 passed |
| `scripts/check_agent_guidance.py` | 0 errors, 7 soft-limit warnings |
| `git diff --check` | Passed |
| Wheel and sdist build; isolated wheel installation and entry-point registration | Passed; all four manifest assets included and compared with source |

The new browser suite covers English desktop and Chinese 375px mobile, dark theme, manual/URL/raw-file imports, explicit false processing fields, invalid inputs, status lookup, confirmed reprocess/cancel, revoked capabilities, browse-only membership, uncertain writes without replay, delayed read/write ordering, resource switching, disabled/empty/unavailable states and recovery. Screenshots in `screenshots/` show synthetic data rendered through the actual host.

Backend HTTP tests prove mismatched descriptor viewers cannot reach contributed GET/POST handlers, including a proxy root path. Same-viewer and headerless clients retain existing behavior. The initial extension tests and stale-viewer tests failed before their corresponding implementation; the delayed-status browser regression also failed with the read-order guard removed.

## Broader-suite limitations

The whole local test run is **not green**:

- Backend offline attempt: **4,224 passed, 172 skipped, 14 deselected, 10 failed**, stopped by `--maxfail=10`. One failure was the newly added guide missing from the approved guidance inventory; fixed and verified by the 23-test run above. Other failures were an atomic worker timeout, a quantized-clock benchmark precondition and seven credential-staging cases using unsupported Windows `os.utime(..., follow_symlinks=False)`.
- The worker timeout and credential-staging failures were reproduced in a separate, unchanged worktree at the exact base commit. The quantized-clock case passed alone on this branch and on the unchanged base. These results do not establish that the rest of the unexecuted backend suite passes.
- Frontend full unit run: **3,544 passed, 5 failed** from five-second timeouts in the unchanged scheduled-task schedule-input and task-form-dialog tests. Rerunning those two files gave **45 passed, 1 timeout**; that remaining task-form case passed when run alone. No scheduled-task production or test files were changed. The complete suite was not rerun to claim an all-green result.
- The first production-build attempt used dependencies from an older worktree and failed on missing `@headlessui/react`. After a local `pnpm install --frozen-lockfile`, the production Webpack build and `pnpm check` both passed. No dependency manifests or locks changed.

Native Windows SWC is blocked by this machine's application-control policy, so the production build uses the supported Webpack option. `make` is unavailable locally; the equivalent formatter, linter and test commands were run directly.

## Reproduction

From `backend/`:

```sh
uv run --no-sync pytest tests/test_knowledge_center_extension.py tests/test_auth_middleware.py tests/test_knowledge_platform_extension.py tests/test_bookmark_plugin.py tests/blocking_io/test_knowledge_platform_extension.py -q
uv run --no-sync pytest tests/blocking_io -q
uv run --no-sync pytest tests/test_agent_guidance_check.py tests/test_knowledge_center_extension.py -q
uv run --no-sync ruff format .
uv run --no-sync ruff check .
```

From `frontend/`:

```sh
pnpm check
pnpm exec rstest run tests/unit/core/extensions
pnpm exec rstest run tests/unit/core/api
# Set BETTER_AUTH_SECRET=local-dev-secret, SKIP_ENV_VALIDATION=1,
# DEER_FLOW_AUTH_DISABLED=1 in the shell before building/starting.
pnpm exec next build --webpack
node scripts/build-search-index.mjs
pnpm exec next start --hostname 127.0.0.1 --port 3016
# In another shell, set PLAYWRIGHT_BASE_URL=http://127.0.0.1:3016
# and PLAYWRIGHT_SKIP_WEB_SERVER=1. Direct Node avoids a local Windows
# pnpm argument-forwarding issue with Playwright filename filters.
node node_modules/@playwright/test/cli.js test tests/e2e/knowledge-center.spec.ts --workers=2 --reporter=line
node node_modules/@playwright/test/cli.js test tests/e2e/bookmark-plugin.spec.ts tests/e2e/business-plugins.spec.ts tests/e2e/plugin-icons.spec.ts --workers=2 --reporter=line
```

From this package directory, `uv build` builds the independently installable wheel and sdist. Tests exercise the real extension loader/static registry, authentication middleware and native browser modules; management HTTP responses in the browser suite are mocked. No live WeKnora connection, production deployment, persistent task ledger, multi-user acceptance, complete phase-4 implementation or phase-5 Trace is claimed.

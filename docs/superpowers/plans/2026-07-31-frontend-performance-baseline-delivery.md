# Frontend Performance Baseline and Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current route-weight and delivery findings into repeatable gates, enable safe compression, eliminate eager case-study image downloads, and remove the mock route's whole-project trace.

**Architecture:** A production-server measurement script owns route asset accounting and compares it with a checked-in budget. Nginx owns textual response compression. Landing images become semantic lazy images. Static demo data is exposed through an explicit manifest so route handlers never derive filesystem paths from request input.

**Tech Stack:** Next.js 16, TypeScript, Rstest, Node.js, Nginx, pnpm.

**Global Constraints:** Work only in `/Users/minimax/workspace/deer-flow/.worktrees/fix-frontend-performance`. Preserve current API routes. Do not gzip SSE or already-compressed media. Every fix follows RED, GREEN, regression proof, then commit.

## Task 1: Add a reproducible route-asset budget gate

**Files:**
- Create: `frontend/scripts/measure-route-assets.mjs`
- Create: `frontend/performance-budgets.json`
- Create: `frontend/tests/unit/scripts/measure-route-assets.test.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/AGENTS.md`

- [ ] Write a failing unit test for exported `extractAssetPaths(html)` and `evaluateBudgets(measurements, budgets)`. Assert duplicate scripts are counted once and a one-byte overage fails with the route, asset class, actual bytes, and limit.
- [ ] Run `cd frontend && pnpm test -- tests/unit/scripts/measure-route-assets.test.ts` and record the missing-module failure.
- [ ] Implement pure helpers in `measure-route-assets.mjs`. The CLI must build with `NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true`, spawn `next start` on a free local port, fetch `/`, `/workspace/chats`, the canonical demo thread, `/en/docs`, and `/blog/posts`, resolve referenced `/_next/static/` files under `.next/static`, and emit `performance-results.json`.
- [ ] Check in these initial ceilings, all below the measured baseline: `/` JS 1,050,000 and CSS 150,000; `/workspace/chats` JS 2,750,000 and CSS 150,000; demo chat JS 3,500,000 and CSS 150,000; `/en/docs` and `/blog/posts` JS 3,000,000 and CSS 230,000.
- [ ] Add `"perf:check": "node scripts/measure-route-assets.mjs --check"` and document the gate and static-demo requirement in `frontend/AGENTS.md`.
- [ ] Run the focused test GREEN. Temporarily lower the `/` JS budget to `1`, prove `pnpm perf:check` fails, restore the file, and defer the final passing gate until the bundle plan lands.
- [ ] Commit: `test(frontend): add route asset performance budgets`.

## Task 2: Enable safe Nginx compression

**Files:**
- Modify: `docker/nginx/nginx.conf`
- Modify: `docker/nginx/nginx.local.conf`
- Create: `backend/tests/test_nginx_compression.py`
- Modify: `AGENTS.md`

- [ ] Write a failing test that parses both configs and asserts the same compression policy: `gzip on`, `gzip_vary on`, minimum length 1024, compression level 5, and types limited to HTML default plus CSS, JavaScript, JSON, XML, and SVG. Assert `text/event-stream`, fonts, images other than SVG, audio, and video are absent.
- [ ] Run `cd backend && uv run pytest tests/test_nginx_compression.py -q` and capture RED.
- [ ] Add the identical directives to both `http` blocks. Include `gzip_proxied any`; do not add a wildcard content type.
- [ ] Update the service-topology note in root `AGENTS.md` to state that Nginx compresses textual responses but deliberately excludes SSE and pre-compressed media.
- [ ] Run the focused test GREEN. If local Nginx is available, start the configured service and verify `curl --compressed -I` returns `Content-Encoding: gzip` for HTML while an SSE response is uncompressed.
- [ ] Revert the directive block, prove the test fails, restore it, rerun GREEN.
- [ ] Commit: `perf(nginx): compress textual responses safely`.

## Task 3: Lazy-load landing case-study images

**Files:**
- Modify: `frontend/src/components/landing/sections/case-study-section.tsx`
- Create: `frontend/tests/unit/components/landing/case-study-section.dom.test.tsx`

- [ ] Write a DOM test that renders the section and asserts each card has an actual `img` with `loading="lazy"`, `decoding="async"`, intrinsic dimensions, descriptive alt text, and no inline/background-image URL.
- [ ] Run the focused test and capture RED against the CSS backgrounds.
- [ ] Replace background-image cards with a positioned `next/image` or native image. Keep the overlay and visual crop, set explicit `sizes`, and make only an above-the-fold image eager if measurement proves it is visible on initial viewport.
- [ ] Run the DOM test GREEN and verify in a browser/network trace that offscreen JPEG requests do not start before scrolling.
- [ ] Revert the component change, prove RED, restore, rerun GREEN.
- [ ] Commit: `perf(frontend): lazy load case study media`.

## Task 4: Replace request-derived mock filesystem traversal with a static manifest

**Files:**
- Modify: `frontend/src/core/threads/static-demo.ts`
- Modify: `frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts`
- Modify: `frontend/src/app/mock/api/threads/[thread_id]/history/route.ts`
- Modify: `frontend/src/app/mock/api/threads/search/route.ts`
- Modify: `frontend/src/app/workspace/page.tsx`
- Create: `frontend/tests/unit/core/threads/static-demo.test.ts`
- Create: `frontend/tests/unit/app/mock/static-artifact-route.test.ts`

- [ ] Add failing tests for `resolveStaticDemoArtifact(threadId, segments)` covering a known artifact, unknown thread, traversal segments, and encoded traversal. Add a route test that asserts the response comes from the manifest-backed resolver.
- [ ] Run both focused tests and capture RED.
- [ ] Define an explicit immutable demo manifest in `static-demo.ts`; normalize and validate all path segments before a lookup. Route handlers may read only paths returned by that manifest.
- [ ] Replace request-time `readdirSync`, `readFileSync`, and `statSync` in mock routes/workspace discovery with manifest imports or `fs/promises` during server execution. Keep response payloads byte-for-byte compatible.
- [ ] Run focused tests GREEN.
- [ ] Run `NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true pnpm build` and assert the prior Turbopack "whole project unintentionally traced" warning and mock artifact import trace are absent.
- [ ] Revert the resolver use, prove the route test RED, restore, rerun focused tests and build.
- [ ] Commit: `perf(frontend): bound static demo file tracing`.

## Final verification

- [ ] Run `cd frontend && pnpm check && pnpm test`.
- [ ] Run `cd backend && uv run pytest tests/test_nginx_compression.py -q`.
- [ ] Run the static-demo production build and confirm zero unexpected-file/whole-project trace warnings.
- [ ] Record the new route measurements in the PR description; do not loosen a budget to make the gate pass.

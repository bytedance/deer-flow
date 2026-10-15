# Frontend Live Media and Artifact Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop hidden animations, remove Browser Live base64/JSON/frame-state overhead, and make large text artifact preview bounded end to end.

**Architecture:** A shared visibility hook gates animation loops. Browser Live negotiates binary JPEG frames while retaining legacy JSON/base64 fallback. The browser client owns an object URL outside React render cadence and presents at most once per animation frame. Artifact text uses `FileResponse` range semantics and a 1 MiB preview contract with an explicit full-load action.

**Tech Stack:** React 19, WebSocket, FastAPI/Starlette, Playwright CDP, TypeScript/Rstest, Python/pytest.

**Global Constraints:** Read the relevant Browser Automation and Artifact sections of `backend/AGENTS.md` before edits. Preserve legacy Browser Live clients. Revoke every object URL. Preserve artifact download/content-disposition security and path ownership checks. Backend changes are test-first and must pass Ruff.

## Task 1: Pause decorative work when hidden or offscreen

**Files:**
- Create: `frontend/src/core/dom/use-render-activity.ts`
- Create: `frontend/tests/unit/core/dom/use-render-activity.dom.test.tsx`
- Modify: `frontend/src/components/ui/galaxy.jsx`
- Modify: `frontend/src/components/ui/magic-bento.tsx`
- Create: `frontend/tests/unit/components/ui/galaxy.dom.test.tsx`
- Create: `frontend/tests/unit/components/ui/magic-bento.dom.test.tsx`

- [ ] Write failing tests for `useRenderActivity(ref)`: false when document hidden or intersection false, true only when both visible, and observer/listener cleanup on unmount.
- [ ] Add component tests proving Galaxy cancels RAF while inactive and Magic Bento attaches pointer movement only to its container and coalesces work to one RAF.
- [ ] Run focused tests and capture RED.
- [ ] Implement the shared hook using `visibilitychange` plus `IntersectionObserver`. Gate Galaxy's RAF lifecycle. Replace Magic Bento's document-wide mousemove with container `pointermove` and one pending RAF.
- [ ] Run GREEN; disable the visibility gate to prove the RAF test RED, restore.
- [ ] Commit: `perf(frontend): suspend hidden landing effects`.

## Task 2: Negotiate binary Browser Live frames in the backend

**Files:**
- Modify: `backend/packages/harness/deerflow/community/browser_automation/session.py`
- Modify: `backend/app/gateway/routers/browser.py`
- Modify: `backend/tests/test_browser_automation.py`
- Modify: `backend/tests/test_browser_router.py`
- Modify: `backend/AGENTS.md`

- [ ] Add failing session tests asserting `_live_frame()` returns raw JPEG `bytes`, never base64 text.
- [ ] Add router tests for `?frame_format=binary`: capability is accepted, frame events use `websocket.send_bytes`, control/status events remain JSON, and a client without the query receives the legacy `{"type":"frame","data":"..."}` JSON payload.
- [ ] Run `cd backend && uv run pytest tests/test_browser_automation.py tests/test_browser_router.py -q` and capture RED.
- [ ] Change `frame_queue` to `asyncio.Queue[bytes]`; keep drop-oldest backpressure. Encode base64 only inside the legacy gateway send path. Reject unsupported capability values with a JSON error and close code 1008.
- [ ] Update `backend/AGENTS.md` with the wire contract and compatibility boundary.
- [ ] Run focused tests GREEN. Reintroduce session-layer base64 to prove the raw-byte assertion RED, restore.
- [ ] Commit: `perf(browser): stream negotiated binary live frames`.

## Task 3: Present Browser Live frames outside React state cadence

**Files:**
- Modify: `frontend/src/components/workspace/browser-view/use-browser-stream.ts`
- Create: `frontend/src/components/workspace/browser-view/frame-buffer.ts`
- Create: `frontend/tests/unit/components/workspace/browser-view/frame-buffer.dom.test.ts`
- Modify: `frontend/tests/e2e/browser-feature.spec.ts`

- [ ] Write failing tests for `FrameBuffer`: multiple binary frames before RAF expose only the latest frame, replaced/dropped URLs are revoked, close revokes the current URL, and legacy JSON/base64 still renders.
- [ ] Assert the WebSocket URL includes `frame_format=binary` and binary frames are not passed through `JSON.parse`.
- [ ] Run focused tests and capture RED.
- [ ] Set `binaryType="blob"`. Keep status/control in React state, but feed frame blobs to `FrameBuffer`, which owns one pending RAF and one object URL. Expose the current URL through `useSyncExternalStore` or an imperative image ref; do not allocate a data URL.
- [ ] Run tests and browser E2E GREEN. Revert to per-message state to prove the coalescing test RED, restore.
- [ ] Commit: `perf(browser): coalesce binary frame presentation`.

## Task 4: Serve text artifacts with byte ranges

**Files:**
- Modify: `backend/app/gateway/routers/artifacts.py`
- Modify: `backend/tests/test_artifacts_router.py`
- Modify: `backend/tests/blocking_io/test_artifacts_router.py`

- [ ] Add failing API tests for a UTF-8 text file: full GET remains inline with the correct media type, `Range: bytes=0-1048575` returns 206/`Content-Range`, invalid ranges return 416, and active HTML/SVG content remains forced-download.
- [ ] Add a blocking-I/O regression asserting the async route does not call `Path.read_text` or `Path.read_bytes` for normal text preview.
- [ ] Run focused backend tests and capture RED.
- [ ] Use Starlette `FileResponse` for safe text and binary inline responses, passing the detected textual media type and existing security headers. Retain attachment handling for active content and explicit downloads.
- [ ] Run focused tests GREEN. Revert safe text to `PlainTextResponse`, prove range/blocking tests RED, restore.
- [ ] Commit: `perf(artifacts): stream ranged text responses`.

## Task 5: Bound the client artifact preview to 1 MiB

**Files:**
- Modify: `frontend/src/core/artifacts/loader.ts`
- Modify: `frontend/src/core/artifacts/preview.ts`
- Modify: `frontend/src/components/workspace/artifacts/artifact-file-detail.tsx`
- Create: `frontend/tests/unit/core/artifacts/loader.test.ts`
- Modify: `frontend/tests/unit/core/artifacts/preview.test.ts`
- Modify: `frontend/tests/e2e/artifact-preview.spec.ts`

- [ ] Write failing tests that require `Range: bytes=0-1048575`, parse status 206 and `Content-Range`, mark the result `{ truncated: true, totalBytes }`, and preserve full/small responses.
- [ ] Add a DOM/E2E assertion that truncated text shows byte counts plus an explicit “Load full file” action, and CodeMirror is not mounted before that action.
- [ ] Run focused tests and capture RED.
- [ ] Add `ARTIFACT_PREVIEW_MAX_BYTES = 1_048_576`. Decode only the returned prefix, display a truncation banner, and refetch without Range only after explicit consent. Plain/Markdown preview remains available for the prefix; editable CodeMirror requires full content.
- [ ] Run tests GREEN. Remove the Range header temporarily to prove RED, restore.
- [ ] Commit: `perf(artifacts): bound large text previews`.

## Task 6: Documentation and cross-stack verification

**Files:**
- Modify: `README.md`
- Modify: `frontend/AGENTS.md`
- Modify: `backend/AGENTS.md`
- Modify: `CHANGELOG.md`

- [ ] Document Browser Live binary negotiation/fallback, the 1 MiB artifact preview behavior, and performance verification commands.
- [ ] Run `cd backend && make format && make lint && uv run pytest tests/test_browser_automation.py tests/test_browser_router.py tests/test_artifacts_router.py tests/blocking_io/test_artifacts_router.py -q`.
- [ ] Run `cd frontend && pnpm check && pnpm test && pnpm test:e2e -- tests/e2e/browser-feature.spec.ts tests/e2e/artifact-preview.spec.ts`.
- [ ] Run the full root-supported checks that are practical locally, then `cd frontend && NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true pnpm build && pnpm perf:check`.
- [ ] Use browser DevTools to verify binary websocket frames, bounded frame presentation, object URL cleanup after panel close, a 206 artifact preview, and an explicit full-load request.
- [ ] Commit: `docs: document frontend performance boundaries`.

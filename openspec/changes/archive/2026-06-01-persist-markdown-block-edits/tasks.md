## 1. Backend — PUT payload endpoint

- [x] 1.1 Add `PUT /api/report-runs/{report_run_id}/payload` endpoint in `backend/app/gateway/routers/report_runs.py`
- [x] 1.2 Endpoint validates `report_run_id`, resolves scope, checks `report_payload_path` exists (404 if not assembled, 410 if file missing), and overwrites `report_payload.json` with the request body

## 2. Frontend — API layer

- [x] 2.1 Add `updateReportRunPayload(runId, payload)` in `frontend/src/core/report-templates/api.ts`

## 3. Frontend — BlockPersistContext

- [x] 3.1 Create `frontend/src/core/genui/block-persist-context.tsx` with `BlockPersistContext`, `BlockPersistProvider`, and `useBlockPersist` hook
- [x] 3.2 `useBlockPersist()` returns `{ saveContent } | null` — null when no provider in tree

## 4. Frontend — MarkdownBlock

- [x] 4.1 Revert localStorage changes from `MarkdownBlock.tsx` (remove `BLOCK_OVERRIDE_PREFIX` helpers and override `useEffect`)
- [x] 4.2 Call `useBlockPersist()` hook; on save, if `saveContent` exists call it and await, otherwise fall back to store-only update
- [x] 4.3 On save failure, show error toast and keep editor open with edited content preserved

## 5. Frontend — Wire up report detail page

- [x] 5.1 In `report-run-detail-page.tsx`, wrap `GenUIRenderer` with `<BlockPersistProvider>` providing a `saveContent` that parses `blockId`, updates the corresponding section, and calls `updateReportRunPayload`
- [x] 5.2 Pass `runId` into the provider so it can map `blockId` → section and call the API

## 6. Verification

- [x] 6.1 Open a completed report, edit a markdown section, save, refresh the page — verify content persists
- [x] 6.2 Open a chat thread with markdown blocks, edit and save — verify in-memory update still works (no regression)
- [x] 6.3 Run `pnpm typecheck` and `pnpm lint` to verify no type or lint errors

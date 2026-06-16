## 1. Frontend — Extract TrackedDocumentItem component

- [x] 1.1 Create `frontend/src/components/workspace/knowledge-bases/kb-tracked-document-item.tsx` — `TrackedDocumentItem` component that accepts `kbId`, `docId`, `title`, `fileName`, `onDismiss` and uses `useDocumentIndexStatus` internally for per-document polling (extracted from `kb-documents-dialog.tsx` to keep files under 800 lines)
- [x] 1.2 Fix the spinner gap: add `indexStatus.isPending` to the `isIndexing` condition so the spinner appears immediately
- [x] 1.3 Support individual dismiss: show a dismiss button when the document reaches terminal state (indexed/failed); hide it while still pending/indexing
- [x] 1.4 Update `getDocumentStatusMeta` to show different badges for "pending" (`knowledgeBase.statusPending`) vs "indexing" (`knowledgeBase.statusIndexing`), and add `statusPending` + `uploadingCount` i18n keys to types.ts, en-US.ts, zh-CN.ts
- [x] 1.5 Render tracker list header "Uploading (N)" (using `knowledgeBase.uploadingCount`) between form and document list, only when `trackedDocs.length > 0`

## 2. Frontend — Refactor AddDocumentForm for concurrent uploads

- [x] 2.1 Replace `trackingDocId: string | null` with `trackedDocs: Array<{ id: string; title: string; fileName: string }>`
- [x] 2.2 After file upload succeeds: capture `title` and `fileName` into a new entry, append to `trackedDocs`, then reset `title` and `file` fields (capture-before-reset ordering is critical)
- [x] 2.3 Render the upload form and tracker list as siblings (not mutually exclusive) — form always visible, tracker list between form and document list
- [x] 2.4 Keep text mode unchanged: `handleTextSubmit` calls `onDone()` immediately on success
- [x] 2.5 "Cancel" button always calls `onDone()` — closes form; active trackers unmount but backend indexing continues

## 3. Nginx — Add upload timeouts

- [x] 3.1 Add `proxy_read_timeout 600s`, `proxy_send_timeout 600s`, `proxy_connect_timeout 600s` to the `/api/` catch-all location in `docker/nginx/nginx.conf`, adjacent to existing `client_max_body_size` and `proxy_request_buffering`
- [x] 3.2 Add the same timeout settings to the `~ ^/api/threads/[^/]+/uploads` location in `docker/nginx/nginx.conf`
- [x] 3.3 Sync both timeout additions to `docker/nginx/nginx.local.conf`

## 4. Tests

- [x] 4.1 Add unit test: `TrackedDocumentItem` shows spinner when `isPending` is true
- [x] 4.2 Add unit test: `TrackedDocumentItem` shows success badge when status is `indexed`
- [x] 4.3 Add unit test: `TrackedDocumentItem` shows dismiss button only when status is terminal
- [x] 4.4 Add unit test: `AddDocumentForm` appends to `trackedDocs` and resets fields in correct order after upload
- [x] 4.5 Add unit test: `AddDocumentForm` keeps form visible when `trackedDocs` is non-empty
- [x] 4.6 Add unit test: `AddDocumentForm` text mode calls `onDone` immediately without adding to `trackedDocs`
- [x] 4.7 Add unit test: `getDocumentStatusMeta` returns distinct labels for "pending" vs "indexing" status

## 5. Verification

- [x] 5.1 Run `pnpm typecheck` and `pnpm lint`
- [x] 5.2 Run `pnpm test` and verify no regressions
- [ ] 5.3 Manually verify: upload file A, then immediately upload file B — confirm both appear in tracker list with independent spinners; document list shows correct different badges for each (pending vs indexing)
- [ ] 5.4 Manually verify: close add form while a file is indexing — confirm tracker unmounts but document list badge continues updating
- [ ] 5.5 Manually verify: upload a large file (>10 MB) and confirm no gateway timeout
- [ ] 5.6 Manually verify: document list shows "等待索引"/"Pending" badge for queued documents and "索引中"/"Indexing" badge for actively indexing documents

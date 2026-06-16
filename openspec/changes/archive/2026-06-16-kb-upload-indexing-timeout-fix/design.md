## Context

The knowledge base upload pipeline has three issues:

1. **Progress tracker renders blank after upload**: When `trackingDocId` is set and `useDocumentIndexStatus` starts its first poll, `indexStatus.data` is `undefined` — `isIndexing` evaluates to `false` and `isTerminal` also `false`. The user sees only a filename div with no spinner for up to 2 seconds.

2. **Upload form blocked by progress tracker**: `AddDocumentForm` uses a single `trackingDocId` state. After upload, the form is replaced by a progress view. The user cannot upload another document until the current one reaches terminal state (`indexed`/`failed`). This is a UX bottleneck — the backend dispatcher already supports concurrent queueing (256-slot queue, 2 parallel workers, `pending` → `indexing` → `ready` state machine).

3. **Nginx timeout on large uploads**: The `/api/` catch-all and `~ ^/api/threads/[^/]+/uploads` locations inherit the nginx default `proxy_read_timeout` of 60 s. Since the upload endpoint reads the full file and converts binary formats before responding, large files exceed this limit.

## Goals / Non-Goals

**Goals:**
- Show the indexing spinner immediately after a document upload completes
- Allow users to upload multiple files without waiting for previous ones to finish indexing, with per-document status tracking visible simultaneously
- Prevent nginx 504 timeout on large file uploads (up to 20 MB)

**Non-Goals:**
- Drag-and-drop or batch file selection (still one file per upload action)
- Changing the upload size limit (stays at 20 MB)
- Backend async reply pattern for upload
- Reducing upload memory pressure from `await file.read()`
- Changing text-mode behavior (text documents keep existing submit→close flow; only file uploads get concurrent tracking)
- Limiting the number of concurrent tracked documents (the backend queue handles back-pressure; the UI tracker list is a convenience, not a gate)

## Decisions

### Decision 1: Use `isPending` for immediate spinner

**Chosen**: Add `indexStatus.isPending` to the indexing condition in `TrackedDocumentItem`.

TanStack Query v5's `isPending` is `true` when the query is enabled but has no cached data — exactly the gap between mounting with a docId and the first poll completing. Since `TrackedDocumentItem` is only rendered with a valid docId (query enabled), `isPending` won't be accidentally true from a disabled query.

```tsx
const isIndexing = status === "pending" || status === "indexing" || indexStatus.isPending;
```

**Alternative**: `placeholderData` from upload response — rejected because it couples the hook to the upload response shape and requires constructing a full `DocumentIndexStatus` object. `isPending` is a one-line change with zero coupling.

### Decision 2: Array of tracked documents instead of single ID

**Chosen**: Replace `trackingDocId: string | null` with `trackedDocs: TrackedDoc[]` where each entry has `{ id, title, fileName }`. Extract `TrackedDocumentItem` into `kb-tracked-document-item.tsx` (separate file — `kb-documents-dialog.tsx` is already 637 lines and would exceed 800 with a 6th component). Each `TrackedDocumentItem` owns its `useDocumentIndexStatus` call.

**Critical timing detail**: After upload succeeds, capture `title` and `fileName` **before** resetting fields:

```tsx
const doc = await uploadDoc.mutateAsync({ file, title: title.trim() || undefined });
setTrackedDocs(prev => [...prev, {
  id: doc.id,
  title: title.trim() || file.name,  // ← capture before reset
  fileName: file.name,
}]);
setTitle("");   // reset after capture
setFile(null);  // reset after capture
```

**Text mode**: Keeps existing behavior — `handleTextSubmit` calls `onDone()` immediately on success. Text documents are small, index quickly, and don't benefit from concurrent tracking UX.

### Decision 3: Upload form stays visible while tracking

**Chosen**: The upload form and tracker list render as siblings. After each successful file upload, fields reset but the form remains open. The tracker list renders between the form and the document list.

```
┌─ Add Document ──────────────────────────┐
│ [Text] [Upload]                          │
│ Title: [________]  [Choose File]         │
│                         [Cancel] [Upload]│
├─ Uploading (2) ─────────────────────────┤
│ 📄 report.pdf    🔄 索引中...        [×] │
│ 📄 notes.txt     ⏳ 等待索引         [×] │
├─ Documents (5) ─────────────────────────┤
│ 📄 report.pdf  [索引中] 0 chunks         │
│ ...                                      │
└──────────────────────────────────────────┘
```

**"Cancel" button semantics**: When the user clicks "Cancel":
- If no active trackers → closes form immediately (existing behavior)
- If active trackers exist → closes form; trackers unmount but backend indexing continues; document list badges remain accurate via its own polling. No confirmation dialog needed — the tracker is a convenience view, not a data-integrity requirement.

**Individual dismiss**: Each `TrackedDocumentItem` shows a dismiss button (×) when it reaches terminal state (`indexed` or `failed`). Dismissing removes the item from `trackedDocs`. Active (non-terminal) items cannot be dismissed from the tracker — they only disappear when the form is closed or when they reach terminal state and are dismissed.

**Dialog close/reopen lifecycle**:
- User closes dialog → `AddDocumentForm` unmounts → `trackedDocs` state destroyed
- User reopens dialog → `useDocuments` fetches fresh data → any still-indexing docs show correct badges in the list
- User clicks "Add Document" → new `AddDocumentForm` with empty `trackedDocs` — no orphan trackers

### Decision 4: Extend nginx timeouts on both upload locations

**Chosen**: Add `proxy_read_timeout 600s`, `proxy_send_timeout 600s`, `proxy_connect_timeout 600s` to:

1. `/api/` catch-all location (handles KB uploads at `/api/knowledge-bases/{id}/documents/upload`)
2. `~ ^/api/threads/[^/]+/uploads` location (handles thread file uploads)

Place new directives adjacent to existing `client_max_body_size` / `proxy_request_buffering` for readability. 600 s matches the existing timeout for `/api/langgraph/` and `/` locations.

**Alternative**: Move file conversion to async background job. Rejected — larger architectural change; timeout extension is the minimal fix.

## Risks / Trade-offs

- **[Risk] Multiple concurrent poll queries** → At 5 concurrent tracked docs, that's 2.5 req/s to the lightweight index-status endpoint (single row read). Documents auto-dismiss on terminal state, so polling duration is bounded. If a user uploads 20+ documents, the tracker list will be long but the request rate (~10 req/s) remains negligible for a local API.
- **[Risk] Long tracker list with many concurrent uploads** → No hard limit on `trackedDocs`; the backend queue handles back-pressure. The tracker list is scrollable within the dialog. A future enhancement could add a "show N / M" collapse, but this is deferred.
- **[Risk] `isPending` briefly true if query errors immediately** → Query transitions to `isError`; the spinner shows momentarily then the document list's "failed" badge takes over on the next list poll. Acceptable.
- **[Risk] Long-lived nginx connections** → `keepalive_timeout 65` limits idle connections; uploads complete within minutes. 600 s matches existing timeouts elsewhere in the config.

## Implementation Order

```
Phase 1: Extract TrackedDocumentItem + isPending fix
         → Single-document tracking works correctly first
Phase 2: Refactor AddDocumentForm to trackedDocs[]
         → Build concurrent upload on top of working tracker
Phase 3: Nginx timeout configuration
         → Independent change, can run in parallel with Phase 1/2
Phase 4: Tests + verification
```

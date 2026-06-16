## Why

After uploading a document to a knowledge base, the UI replaces the upload form with a progress tracker, blocking further uploads until indexing completes. Users cannot queue multiple documents — they must wait for each to finish before uploading the next. Additionally, the progress tracker renders blank (no spinner) for up to 2 seconds after upload because it waits for the first poll result. Large file uploads (>10 MB) also cause nginx 504 timeout errors because the upload location lacks explicit timeout overrides (defaults to 60 s).

## What Changes

- **Frontend**: Extract `TrackedDocumentItem` component with independent per-document polling via `useDocumentIndexStatus`. Fix the blank-state bug by adding `isPending` to the indexing condition.
- **Frontend**: Refactor `AddDocumentForm` from a single `trackingDocId` to a `trackedDocs[]` array — the upload form stays visible after each upload (fields reset), and a tracker list renders between the form and the document list showing each document's index progress independently. File upload mode supports concurrent uploading; text mode keeps its existing behavior (submit → close form immediately).
- **Nginx**: Add `proxy_read_timeout`, `proxy_send_timeout`, and `proxy_connect_timeout` (each 600 s) to both the `/api/` catch-all location and the thread uploads location to prevent gateway timeout on large file uploads.

## Capabilities

### Modified Capabilities
- `upload-index-pipeline-visibility`: Fix the upload progress tracker blank-state bug; add support for concurrent file uploads with per-document status tracking, so users can queue multiple documents while earlier ones are still indexing.

## Impact

- **Frontend**: `kb-documents-dialog.tsx` (extract `TrackedDocumentItem`, refactor form to `trackedDocs[]`, fix spinner via `isPending`), `hooks.ts` (no changes needed — `useDocumentIndexStatus` already supports per-doc polling)
- **Nginx**: `docker/nginx/nginx.conf`, `docker/nginx/nginx.local.conf` (timeout settings on `/api/` and `~ ^/api/threads/[^/]+/uploads` locations)
- No API or backend changes required (dispatcher already supports queue semantics with 256-slot queue and 2 parallel workers)

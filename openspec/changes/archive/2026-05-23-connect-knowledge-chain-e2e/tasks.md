## 1. Frontend — upload index polling verification

- [x] 1.1 Verify `useDocumentIndexStatus` polls every 2s and stops on terminal states (`indexed`/`failed`)
- [x] 1.2 Verify `useDocuments` auto-polls via `getDocumentRefetchInterval` while any document is `pending`/`indexing`
- [x] 1.3 Verify `AddDocumentForm` shows upload progress tracker with spinner, indexed badge (chunk count), and failed state with error + retry action
- [x] 1.4 Verify `DocumentRow` shows index status badge (indexing/failed) and displays `index_error` with reindex button on failure
- [x] 1.5 Add unit tests for `getDocumentRefetchInterval` covering all 4 statuses and mixed document lists

## 2. Backend — explicit KbAccessControl.can_read in retrieval path

- [x] 2.1 Add per-KB `can_read()` check in `_search_selected_kbs` that reports denied KBs with structured error in the response
- [x] 2.2 Add per-KB `can_read()` check in `_search_single_collection` for collection-scoped retrieval
- [x] 2.3 Add unit test verifying `_search_selected_kbs` returns structured access-denied for blocked KBs
- [x] 2.4 Add unit test verifying `_search_selected_kbs` permits authorized KBs and returns chunks

## 3. E2E integration tests — real pipeline

- [x] 3.1 Add real pipeline test: create KB → upload document → trigger inline index → search → verify chunks returned
- [x] 3.2 Add index-incomplete boundary test: document with `pending` status excluded from retrieval results
- [x] 3.3 Add permission-denied boundary test: user without read access receives structured access-denied error through retrieval path
- [x] 3.4 Mark all new integration tests with `@pytest.mark.integration`

## 4. Verification

- [x] 4.1 Run backend unit tests (`make test`) and verify all pass
- [x] 4.2 Run frontend type check and lint (`pnpm check`) and verify clean
- [x] 4.3 Run frontend unit tests (`pnpm test`) and verify all pass

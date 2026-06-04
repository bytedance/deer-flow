## 1. Verify title sync coverage

- [ ] 1.1 Confirm `worker.py:467-478` title sync handles all terminal states (success / failed / cancelled / rollback) — all paths go through the `finally` block
- [ ] 1.2 Confirm no other Phase 2 side effect is relied upon by external code (check for callers depending on lazy migration or tombstone filtering behavior)

## 2. Remove Phase 2 from search_threads

- [ ] 2.1 Delete `checkpointer` and `store` variable declarations (lines 388–389) since they're only used in Phase 2
- [ ] 2.2 Delete `deleted_thread_ids` tombstone query (lines 427–438)
- [ ] 2.3 Delete `current_tenant` and `current_user` local vars (lines 424–425)
- [ ] 2.4 Delete the Phase 2 `checkpointer.alist(None)` iteration block (lines 440–521)

## 3. Simplify result assembly

- [ ] 3.1 Replace `merged: dict[str, ThreadResponse]` with direct `list[ThreadResponse]` — Phase 1 results go directly into a list
- [ ] 3.2 Remove the dict-to-list conversion (`merged.values()` → list) in Phase 3
- [ ] 3.3 Update the docstring from "Two-phase approach" to describe the single Store-based approach

## 4. Verify

- [ ] 4.1 Run `backend/tests/test_threads_router.py` and ensure all tests pass; update any tests that mock Phase 2 behavior
- [ ] 4.2 Run full backend test suite to check for regressions
- [ ] 4.3 Manually verify: create a new thread → send a message → check that title appears in sidebar and "查看全部" without waiting for Phase 2 backfill

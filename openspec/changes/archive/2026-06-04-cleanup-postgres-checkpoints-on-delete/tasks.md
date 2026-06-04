## 1. Core Implementation

- [x] 1.1 Add `_delete_postgres_checkpoints` helper function in `threads.py` that accepts a checkpointer and thread_id, checks `isinstance` against `AsyncPostgresSaver`, and executes `DELETE FROM checkpoints/checkpoint_writes/checkpoint_blobs WHERE thread_id = $1` using a pooled connection
- [x] 1.2 Wire the helper into the `delete_thread_data` handler, called after the existing `adelete_thread` check and before `thread_store.delete()`, gated by `hasattr(checkpointer, "adelete_thread")` being false
- [x] 1.3 Add a `hasattr(checkpointer, "conn")` guard before accessing the pool to avoid `AttributeError` on backends that don't carry a `conn` attribute

## 2. Testing

- [x] 2.1 Write unit test `test_delete_postgres_checkpoints` that mocks `AsyncPostgresSaver` with a fake pool and verifies three DELETE statements execute with correct `thread_id`
- [x] 2.2 Write unit test `test_delete_thread_skips_postgres_cleanup_when_adelete_thread_exists` verifying the raw SQL path is NOT called when the checkpointer has `adelete_thread`
- [x] 2.3 Write unit test `test_delete_postgres_checkpoints_failure_is_non_fatal` verifying that exceptions during cleanup do not propagate
- [x] 2.4 Verify existing `test_threads_router.py` tests still pass

## 3. Verification

- [x] 3.1 Run `make test` in backend directory to confirm all tests pass
- [x] 3.2 Run `make lint` in backend directory to confirm code style

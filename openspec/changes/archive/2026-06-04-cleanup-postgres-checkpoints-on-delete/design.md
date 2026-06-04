## Context

The `DELETE /api/threads/{thread_id}` handler in [threads.py:251-298](backend/app/gateway/routers/threads.py#L251-L298) cleans up four things: local filesystem, Store records, checkpoints, and thread_meta. For checkpoints, it relies on `checkpointer.adelete_thread(thread_id)` — but this method exists only on `AsyncSqliteSaver`, not on `AsyncPostgresSaver`. The existing code already checks `hasattr(checkpointer, "adelete_thread")` (line 285), so PostgreSQL silently skips this step.

The LangGraph `AsyncPostgresSaver` stores checkpoints across three tables:
- `checkpoints` — one row per checkpoint (keyed by `thread_id` + `checkpoint_ns` + `checkpoint_id`)
- `checkpoint_writes` — pending writes for each checkpoint
- `checkpoint_blobs` — channel blob data for each checkpoint

All three tables share `thread_id` as a key column, making cleanup a simple `DELETE ... WHERE thread_id = $1`.

The checkpointer's `conn` attribute is the `AsyncConnectionPool` created in [async_provider.py:76-84](backend/packages/harness/deerflow/runtime/checkpointer/async_provider.py#L76-L84). We can borrow a connection from this pool to execute raw SQL, then return it — no new pool or connection needed.

## Goals / Non-Goals

**Goals:**
- Delete all PostgreSQL checkpoint rows (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) for a thread when it is deleted
- Keep the change minimal — a single new helper function, invoked from the existing handler
- Maintain the existing best-effort semantics (failure logs a warning, never blocks deletion)

**Non-Goals:**
- Adding `adelete_thread` to upstream LangGraph's `AsyncPostgresSaver` — that's a langgraph issue
- Changing the SQLite or Memory backend paths
- Adding a garbage-collection background job
- Adding admin API endpoints for manual checkpoint cleanup
- Handling partially-deleted checkpoints across multiple `checkpoint_ns` values (we delete for all namespaces)

## Decisions

### Decision 1: Direct SQL DELETE vs. monkey-patching `adelete_thread`

**Chosen: Direct SQL DELETE from the router handler.**

Alternative considered: monkey-patching `adelete_thread` onto `AsyncPostgresSaver` at startup. Rejected because it couples the router to the checkpointer lifecycle, is harder to test, and feels fragile.

The approach: add a private `_delete_postgres_checkpoints(checkpointer, thread_id)` helper to `threads.py` that:
1. Checks `isinstance(checkpointer, AsyncPostgresSaver)`
2. Borrows a connection from `checkpointer.conn` (the pool)
3. Executes three `DELETE` statements
4. Returns the connection to the pool

### Decision 2: How to detect PostgreSQL backend

**Chosen: `isinstance()` check against `AsyncPostgresSaver`.**

Alternative considered: reading `get_app_config().database.backend`. Rejected because:
- The handler already has access to the checkpointer object
- `isinstance` is more robust — it works regardless of which config path (legacy `checkpointer:` vs unified `database:`) created the saver
- It's a single import of `AsyncPostgresSaver`

### Decision 3: Use the existing pool vs. create a new connection

**Chosen: Borrow from the existing pool via `checkpointer.conn`.**

The `AsyncPostgresSaver` holds `self.conn` which is the `AsyncConnectionPool`. We use `pool.connection()` as an async context manager to get a connection, execute, and return it. This avoids creating a second pool or managing a separate connection lifecycle.

### Decision 4: namespace handling

**Chosen: Delete all checkpoints for the thread regardless of `checkpoint_ns`.**

The `WHERE thread_id = $1` clause deletes rows for all namespaces. This is consistent with `adelete_thread` behavior on SQLite, which also deletes all namespaces for a given thread.

## Risks / Trade-offs

- **Pool contention**: The DELETE runs inside the request lifecycle, briefly holding a pool connection. For very large checkpoint histories (thousands of checkpoints), this could be a slow query. Mitigation: the deletion is best-effort with a try/except; it won't block the response.
- **Partial deletion**: If the process crashes mid-DELETE, orphaned rows may remain. Recovery requires manual SQL or a future GC job. Acceptable for now — this is strictly better than the current state where ALL checkpoints are left behind.
- **LangGraph upstream**: Future versions of langgraph may add `adelete_thread` to `AsyncPostgresSaver`. Our `isinstance` check naturally coexists — we can gate on the absence of the method and fall through if upstream adds it. When upstream adds it, we remove our custom path.

## Migration Plan

1. Deploy the code change (new helper + one-line call in handler)
2. No database migration needed — existing orphaned checkpoints remain (they're garbage that doesn't affect anything)
3. New deletions from this point forward will be clean
4. For existing orphaned data, provide a short SQL snippet in the commit message for manual cleanup:
   ```sql
   -- Optional: clean pre-existing orphans (run during maintenance window)
   DELETE FROM checkpoint_blobs WHERE thread_id NOT IN (SELECT thread_id FROM thread_meta);
   DELETE FROM checkpoint_writes WHERE thread_id NOT IN (SELECT thread_id FROM thread_meta);
   DELETE FROM checkpoints WHERE thread_id NOT IN (SELECT thread_id FROM thread_meta);
   ```
5. Rollback: revert the commit. No data migration to undo.

## Open Questions

<!-- None — the approach is straightforward and contained to a single function -->

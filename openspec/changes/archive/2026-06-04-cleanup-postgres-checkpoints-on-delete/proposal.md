## Why

When a user deletes a conversation (thread) via `DELETE /api/threads/{thread_id}`, the PostgreSQL checkpointer (`AsyncPostgresSaver`) does not expose an `adelete_thread` method. The current deletion handler silently skips checkpoint cleanup for PostgreSQL backends, leaving orphaned rows in `checkpoints`, `checkpoint_writes`, and `checkpoint_blobs` tables. Over time, this accumulates dead data that bloats storage, slows checkpointer scans, and wastes disk space with no recovery path. PostgreSQL deployments have no way to clean this garbage short of manual SQL intervention.

## What Changes

- Implement SQL-level checkpoint cleanup in the thread deletion handler for PostgreSQL backends
- Directly delete rows from `checkpoints`, `checkpoint_writes`, and `checkpoint_blobs` tables when the checkpointer lacks `adelete_thread`
- Guard the cleanup behind a PostgreSQL backend check so SQLite and Memory backends remain unchanged
- Make cleanup best-effort (failure logs a warning but does not block thread deletion)

## Capabilities

### New Capabilities
- `postgres-checkpoint-cleanup`: Direct deletion of PostgreSQL checkpoint rows for a given thread_id when the LangGraph checkpointer does not provide `adelete_thread`

### Modified Capabilities
<!-- None — this is a backend implementation detail, not a spec-level requirement change -->

## Impact

- Affected code: `backend/app/gateway/routers/threads.py` (`delete_thread_data` handler)
- Affected tables: `checkpoints`, `checkpoint_writes`, `checkpoint_blobs` (only when PostgreSQL backend is active)
- No API surface change — the `DELETE /api/threads/{thread_id}` endpoint contract is unchanged
- No new dependencies — uses `psycopg` connection already available via the checkpointer's pool
- Risk: Low — wrapped in best-effort try/except matching the existing pattern for `adelete_thread`

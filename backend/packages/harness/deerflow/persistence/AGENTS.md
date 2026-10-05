# Persistence lifecycle

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

Acquire that lock by polling `pg_try_advisory_lock`, never with a blocking `pg_advisory_lock`: the app engine's asyncpg `command_timeout` bounds every statement, so a blocking acquire fails a second instance's startup whenever a peer's migration outlasts it.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

Alembic stamp/upgrade workers started inside `bootstrap_schema()` remain owned by the bootstrap critical section until the worker finishes. Drain those `asyncio.to_thread()` calls across host cancellation before releasing the in-process SQLite bootstrap lock or PostgreSQL advisory lock; otherwise another bootstrap can overlap a still-running migration worker.

On SQLite, `BEGIN IMMEDIATE` takes the database-wide write lock, so every unrelated writer (run status, thread metadata, the scheduler) waits for the transaction and fails with `database is locked` after `busy_timeout` (30s). Do slow work such as document conversion before opening a locked transaction; lock only to revalidate and publish, as `ProjectDocumentRepository.publish_under_live_lock` does. `tests/test_project_document_tools.py::TestConversionSerialization` pins this.

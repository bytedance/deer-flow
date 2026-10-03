# Persistence lifecycle

Notification outbox claims carry a nullable UUID-hex `claim_token` (migration 0029). Both completion methods require the token and atomically UPDATE only the matching `sending` row. Reset clears the token; reclaim replaces it; completion clears it. Never replace this SQL fence with a SELECT/ORM-flush ownership check. Workers must pass the original claim token through every success, failure, parking, disconnect, and crash-recovery path. Tokenless legacy sending rows wait for stale recovery. External sends remain at-least-once.

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

Alembic stamp/upgrade workers started inside `bootstrap_schema()` remain owned by the bootstrap critical section until the worker finishes. Drain those `asyncio.to_thread()` calls across host cancellation before releasing the in-process SQLite bootstrap lock or PostgreSQL advisory lock; otherwise another bootstrap can overlap a still-running migration worker.

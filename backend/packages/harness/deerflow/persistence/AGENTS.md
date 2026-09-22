# Persistence lifecycle

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

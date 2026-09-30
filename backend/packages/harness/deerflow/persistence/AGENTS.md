# Persistence lifecycle

MCP cancellation targets are resolved by `McpTaskRepository.find_active_matches()`: look up the exact ID within the caller scope first, returning no match for a terminal task; otherwise filter by name key before reading at most two matches. `task_name_key` stores the original `task_name.casefold().encode("utf-8")`; only the input selector is stripped. Binary comparison preserves the same semantics on SQLite and Postgres. Names are immutable after creation; any new rename path must update the key. The key is internal and removed from repository output. Migration `0027_mcp_task_name_key` backfills existing rows and adds the index. Stop older writers before upgrading; the required key does not support mixed-version writers.

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

Alembic stamp/upgrade workers started inside `bootstrap_schema()` remain owned by the bootstrap critical section until the worker finishes. Drain those `asyncio.to_thread()` calls across host cancellation before releasing the in-process SQLite bootstrap lock or PostgreSQL advisory lock; otherwise another bootstrap can overlap a still-running migration worker.

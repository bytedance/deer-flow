# Recovering the original thread-incarnation database revision

The Projects build requires `projects` and `threads_meta.project_id`. An older
deployment may have stamped `0019_thread_incarnations` on a database containing
only `0018_oauth_identity_pg_partial` plus two nullable `VARCHAR(32)` columns:
`threads_meta.incarnation` and `mcp_tasks.thread_incarnation`. That shape cannot
serve this build's repositories. Startup now rejects it without changing the
schema or revision, and reports the missing tables/columns.

Normal databases on this tree's known migration chain upgrade automatically.
The procedure below is only for the exact original incarnation rollout shape.
An incarnation-stamped database that already has all current ORM tables and
columns can still use the audited compatibility exception without re-stamping.

## Offline migration

1. Stop every Gateway, scheduler, and other process writing to the database.
   Take a restorable database backup and rehearse these steps on a copy.
2. Verify there is exactly one `alembic_version` row, containing
   `0019_thread_incarnations`. Inspect the owning deployment's migration and
   actual database schema: it must be the local 0018 schema plus only the two
   nullable columns above, with no added defaults, constraints, tables, indexes,
   or data backfills. Neither `projects` nor `threads_meta.project_id` may already
   exist for this recovery path. If the shape differs, use a migration reviewed
   for that deployment; do not use the commands below.
3. From this checkout's `backend/`, set `DEERFLOW_RECOVERY_DATABASE_URL` to the
   target async SQLAlchemy URL (`sqlite+aiosqlite:////absolute/path/database.db`
   or `postgresql+asyncpg://…`). For Postgres, also set
   `DEERFLOW_RECOVERY_POSTGRES_SCHEMA` to the configured application schema, if
   one is used. Keep credentials out of shell history.
4. Rebase the version marker to the verified common parent and run the normal
   migrations. `purge=True` is necessary because this tree does not contain the
   out-of-tree revision; it replaces the version row, not application data.

   ```bash
   uv run python - <<'PY'
   import asyncio
   import os

   from alembic import command
   from sqlalchemy.ext.asyncio import create_async_engine

   from deerflow.persistence.bootstrap import _get_alembic_config

   engine = create_async_engine(os.environ["DEERFLOW_RECOVERY_DATABASE_URL"])
   cfg = _get_alembic_config(
       engine,
       postgres_schema=os.environ.get("DEERFLOW_RECOVERY_POSTGRES_SCHEMA", ""),
   )
   command.stamp(cfg, "0018_oauth_identity_pg_partial", purge=True)
   command.upgrade(cfg, "head")
   asyncio.run(engine.dispose())
   PY
   ```

   This applies `0019_projects` and `0020_threads_meta_project_id`, preserving
   the two incarnation columns and their existing values. Do not stamp directly
   to head: that would skip the DDL and reproduce the missing-column failure.
5. Confirm the version is `0020_threads_meta_project_id`, the project table and
   membership column/index exist, and existing incarnation values are retained.
   Start this build, verify existing conversations load and a new conversation
   can be created, then resume service. Do not restart older binaries that
   cannot read this tree's head revision.

Bootstrap never performs this re-stamp itself. The regression in
`backend/tests/test_persistence_forward_revision_compat.py` constructs the
original schema, verifies startup rejection, and exercises the recovery while
checking thread reads/inserts and preservation of incarnation data. The future
incarnation migration must chain from the current local head and handle these
already-present nullable columns idempotently.

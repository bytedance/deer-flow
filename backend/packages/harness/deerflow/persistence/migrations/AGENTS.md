# Schema migrations (`deerflow/persistence/migrations/`)

Alembic revisions for the DeerFlow-owned tables, and the filters that keep
LangGraph checkpointer tables and extension tables out of Alembic's view.
`persistence/bootstrap.py::bootstrap_schema` applies them at Gateway startup, so a
routine upgrade needs no manual Alembic command. The chain itself is
`versions/`; `alembic history` prints it. Recovery from a revision this tree does
not know:
[database forward-revision recovery](../../../../../../docs/database-forward-revision-recovery.md).

## Verify

```bash
cd backend
make migrate-rev MSG="add foo column to runs"   # autogenerate a revision
python -m pytest tests -q -k "migration or bootstrap"
```

Set `TEST_POSTGRES_URI` to run the same cases against PostgreSQL. Test both
`upgrade` and `downgrade` of a new revision.

## Authoring a revision

- **Every ORM model change ships with a revision** in the same change.
- **Chain onto the current head.** Alembic walks forward from the stamped
  revision and orders by `down_revision`, not by the numeric prefix. A revision
  inserted ahead of one that already shipped is treated as applied by every
  database stamped past that point, and never runs there.
- **Use the idempotent helpers in `_helpers.py`** in place of raw `op.add_column`
  and `op.drop_column`. A database created by `create_all` can already have the
  column, and a retried upgrade must not fail on it.
- **New columns on existing tables are nullable and have no server default**
  unless the revision backfills them. An older binary that shares the database
  during a rolling upgrade or after a rollback then still reads and writes its
  rows.
- **Deduplicate before you add a unique index.** Existing rows can violate it.
- **A guard that the fresh-database path needs is installed twice**: in the
  revision and on metadata `after_create`. The empty-database path does not run
  revisions.
- **There is no `make migrate` or `make migrate-stamp` target**, on purpose.
  Upgrades run at startup.

## Bootstrap

- **An empty database is built with `create_all` and stamped at head.**
  `Base.metadata` is the only authoritative schema, and it renders the SQLite and
  PostgreSQL forms correctly. The baseline revision is a stamp target and is
  almost never executed.
- **A pre-Alembic database gets baseline tables only**, is stamped at the
  baseline and then upgraded. The backfill must not create a table that a later
  revision creates, or that revision fails with "already exists". Keep
  `_BASELINE_TABLE_NAMES` equal to what the baseline revision creates.
- **An unknown revision, an empty version table or several version rows stop
  startup.** Bootstrap never re-stamps automatically. Follow the recovery
  document offline.
- **Downgrade is refused once the forward policy is active.** Dispose the
  migration engine on refusal as well.
- **Concurrent Gateways serialize the upgrade** with a PostgreSQL advisory lock.

## Tables that Alembic must ignore

- **An extension owns its schema.** It uses a private `MetaData` and one table
  prefix declared as `table_prefix` in its `plugins:` record. A model registered
  on `deerflow.persistence.base.Base` would be created by the host on installs
  that never enabled the extension.
- **The prefix is registered in two processes.** The Gateway registers it when it
  loads extensions, also for a disabled or failing one, because its tables can
  already exist. The Alembic process reads it from `config.yaml` and never imports
  extension code: a migration process must not run third-party code.
- **`make migrate-rev` is safe without the filter**, because it diffs against a
  throwaway database built from the chain. The filter protects a direct
  `alembic revision --autogenerate`, which reflects the real database and would
  propose dropping every table it does not know.

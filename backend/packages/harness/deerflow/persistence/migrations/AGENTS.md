### Schema Migrations (`packages/harness/deerflow/persistence/migrations/`)

DeerFlow's application tables (`runs`, `threads_meta`, `feedback`, `users`, `run_events`, plus the four `channel_*` tables) are owned by alembic via a **hybrid bootstrap** strategy. LangGraph's checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) live in the same database but are owned by LangGraph and excluded from alembic's view via `migrations/_env_filters.py::include_object`.

**Convention**: every ORM model change (new column, new table, new index) MUST ship as an alembic revision under `migrations/versions/`. The Gateway runs `alembic upgrade head` automatically on startup; users do not run `alembic` manually in production.

**Hybrid bootstrap** (`persistence/bootstrap.py::bootstrap_schema`, invoked from `persistence/engine.py::init_engine`):

| DB state                                  | Action                                  |
|-------------------------------------------|-----------------------------------------|
| empty (no DeerFlow tables)                | `create_all` + `alembic stamp head`     |
| legacy (DeerFlow tables, no `alembic_version`) | `create_all` (baseline tables only, backfill) + `alembic stamp 0001_baseline` + `upgrade head` |
| versioned (`alembic_version` row exists)  | `alembic upgrade head`                  |

The legacy branch handles pre-alembic databases that already have at least one DeerFlow-owned table. `create_all` runs first because stamping at `0001_baseline` makes alembic skip the baseline's own `create_table` DDL on the subsequent upgrade — so any baseline table introduced into `Base.metadata` after the user's DB was first provisioned (e.g. the `channel_*` tables from PR #1930 for users upgrading across multiple releases) would otherwise never be created, and the first request hitting that table would 500 with `no such table`. The backfill is **restricted to `_BASELINE_TABLE_NAMES`** so it does not also create tables that future revisions introduce — those revisions' own `op.create_table` would otherwise fail with `relation already exists`. A guard test pins `_BASELINE_TABLE_NAMES` against `0001_baseline.upgrade()`'s actual output, so editing 0001 to add or remove a table forces a matching update to the constant. Column-level shape (pre-#3658 vs post-#3658 vs manual-ALTER for `token_usage_by_model`) is answered by each `versions/*.py` revision via the idempotent helpers in `migrations/_helpers.py` (`safe_add_column` / `safe_drop_column`) which no-op when the change is already present and `logger.warning` on shape drift. **Adding a new ORM column / table only requires a new revision file — no edit to `bootstrap.py` is needed** *unless* the new revision adds a new baseline table (rare; only happens when a new model is part of the baseline rather than introduced by its own revision).

The empty-DB path keeps using `create_all` because `Base.metadata` is the only authoritative schema source — `create_all` renders both SQLite (JSON, type affinity) and Postgres (JSONB, partial indexes) correctly without anyone having to keep a hand-written baseline in lockstep. `0001_baseline.upgrade()` is therefore almost never executed in practice; it exists as a stamp target + chain root.

**Concurrency safety**: Postgres uses `pg_advisory_lock` to serialise concurrent Gateway instances. SQLite uses a per-engine `asyncio.Lock` for same-process startup and is best-effort across processes via SQLite's file-level write lock + `PRAGMA busy_timeout`; multi-instance deployments should use Postgres. Column revisions in `versions/` additionally use idempotent helpers (`_helpers.py::safe_add_column`, `safe_drop_column`) so repeated post-baseline changes and retries are no-ops when the change is already present.

**Authoring a new revision**:
```bash
cd backend && make migrate-rev MSG="add foo column to runs"
```
This invokes `alembic revision --autogenerate` against the live ORM models. Review the generated file under `migrations/versions/` and switch raw `op.add_column` / `op.drop_column` calls to the idempotent helpers from `_helpers.py` before committing. There is no `make migrate` / `make migrate-stamp` target on purpose — the only execution path is Gateway startup, which keeps operational mistakes off the table.

**Extension-owned tables.** An extension that persists data owns its schema
end to end and must not register models against `deerflow.persistence.base.Base`
— doing so makes the host's empty-DB `create_all` create the extension's tables
on installs that never enabled it. The convention is:

- one `MetaData` instance private to the extension;
- every table sharing one prefix, declared via the `plugins:` record's
  `ExtensionSpec.table_prefix` field, so `alembic revision --autogenerate`
  ignores them instead of reflecting them, finding them absent from
  `Base.metadata`, and proposing `drop_table`. Registration happens in two
  places on purpose, because two different processes read the filter:
  `extensions/loader.py::load_extensions` covers the Gateway, and
  `register_configured_extension_table_prefixes()` — called from
  `migrations/env.py` — covers the alembic process, which never starts a
  Gateway and would otherwise see an empty prefix set exactly where
  `include_object` consumes it. The alembic side reads the declaration out of
  `config.yaml` and never imports extension code: a migration process must not
  execute third-party code. The Gateway side registers unconditionally, even
  for a disabled or later-failing spec, because the tables it names may
  already exist in the database from a previous run. Because those two readers
  cannot both be right about an empty prefix — the Gateway's truthiness test
  reads it as "no prefix", a literal reader as one matching every table —
  `ExtensionSpec.table_prefix` carries `min_length=1`, and the alembic-side
  reader (which parses raw YAML, so pydantic never runs there) skips anything
  that model would reject rather than raising: an operator does not expect to
  hear about a malformed `config.yaml` from alembic, and Gateway startup runs
  that same module through `bootstrap_schema`;

  Scope, because it is narrower than it first appears: **`make migrate-rev` is
  already safe without this.** `scripts/_autogen_revision.py` builds a
  throwaway SQLite from the migration chain and diffs against that, so no
  extension table — and no LangGraph table — is ever reflected. The exposed
  path is running `alembic revision --autogenerate` directly from the
  migrations directory, where `alembic.ini` points `sqlalchemy.url` at a real
  `./data/deerflow.db`. That is the same path `LANGGRAPH_OWNED_TABLES` covers,
  which is why that exclusion exists even though the throwaway-DB script
  landed in the same commit;
- an independent alembic chain with its own
  `version_table="<prefix>alembic_version"`, run from `ExtensionService.start()`
  against `ExtensionRuntimeDeps.session_factory`'s bind — which is sequenced
  after the host's own bootstrap by construction, since services start once
  persistence is ready;
- a Postgres advisory lock around that upgrade, mirroring `bootstrap_schema`,
  so concurrent Gateway instances serialise.

**Where things live**:
- `migrations/env.py` — alembic env, delegates filter to `_env_filters.py`, sets `render_as_batch=True` for SQLite ALTER support
- `migrations/_env_filters.py::include_object` — drops LangGraph checkpointer tables and any registered extension-owned tables (`EXTENSION_TABLE_PREFIXES`) from alembic's view
- `migrations/_env_filters.py::register_configured_extension_table_prefixes` — populates that set inside the alembic process, reading `plugins[*].table_prefix` from `config.yaml` and never importing extension code; called at import from `migrations/env.py`, because `load_extensions()` only ever runs in the Gateway
- `migrations/_helpers.py` — `safe_add_column` / `safe_drop_column`
- `migrations/versions/0001_baseline.py` — chain root, matches the schema `create_all` produces from `Base.metadata`
- `migrations/versions/0002_runs_token_usage.py` — fixes issue #3682
- `migrations/versions/0004_run_ownership.py` — `runs` multi-worker ownership + the `uq_runs_thread_active` partial unique index, with a `_dedupe_active_runs_per_thread()` pre-step so `CREATE UNIQUE INDEX` cannot fail on a field DB that already has duplicate active rows per thread
- `migrations/versions/0007_scheduled_run_active_index.py` — the `uq_scheduled_task_run_active` partial unique index (at most one queued/running `scheduled_task_runs` row per `task_id`), with a `_dedupe_active_scheduled_runs_per_task()` pre-step (keeps the newest active row per task, supersedes the rest to `interrupted` with an explanatory `error` + `finished_at`) mirroring 0004; chains after `0006_agents`
- `migrations/versions/0008_thread_operation_kind.py` — adds `runs.operation_kind` for durable non-run thread reservations; chains after `0007_scheduled_run_active_index`
- `migrations/versions/0010_run_cancel_request.py` — adds the nullable `runs.cancel_action` / `cancel_requested_at` handoff used by non-owning workers; chains after `0009_webhook_dedupe`
- `migrations/versions/0011_mcp_tasks.py` — creates the durable long-running MCP task table and its user/server/remote uniqueness constraint
- `migrations/versions/0012_mcp_task_results.py` — adds bounded result preview/truncation/artifact fields for ordinary task drivers
- `migrations/versions/0013_mcp_task_notifications.py` — adds durable Agent-run notification snapshots, delivery leases, idempotency fields, and the separate bounded-retry attempt counter
- `migrations/versions/0014_managed_subagents.py` — creates the deployment-level managed Subagent catalog table
- `migrations/versions/0015_scheduled_task_enqueue.py` — interrupts legacy transient queued rows, adds durable scheduled-run launch leases and attempt counts, expands the one-active-occurrence index to `queued`/`launching`/`running`, and migrates the overlap policy from `skip` to `enqueue`; chains after `0014_managed_subagents`
- `migrations/versions/0016_subagent_batches.py` — creates durable native-subagent batch and item tables, including owner/submission idempotency, item identity, lease/recovery state, and result fields
- `persistence/bootstrap.py` — `bootstrap_schema(engine, backend=...)`, the three-branch decision + locking
- `extensions/loader.py::load_extensions` — registers each spec's `table_prefix` with `register_extension_table_prefix()`
- Tests: `tests/test_persistence_bootstrap.py` (branches), `tests/test_persistence_bootstrap_concurrency.py` (concurrency), `tests/test_persistence_bootstrap_regression.py` (issue #3682), `tests/test_persistence_migrations_env.py` (filter, including extension-owned tables), `tests/test_extension_loader.py::TestTablePrefixRegistration` (spec-to-filter wiring), `tests/blocking_io/test_persistence_bootstrap.py` (asyncio.to_thread anchor), `tests/test_migration_0004_run_ownership_dedupe.py` + `tests/test_migration_0007_scheduled_run_active_dedupe.py` (dedupe-before-unique-index pre-steps)

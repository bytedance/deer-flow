### Schema Migrations (`packages/harness/deerflow/persistence/migrations/`)

DeerFlow's application tables (`runs`, `threads_meta`, `feedback`, `users`, `run_events`, plus the four `channel_*` tables) are owned by alembic via a **hybrid bootstrap** strategy. LangGraph's checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) live in the same database but are owned by LangGraph and excluded from alembic's view via `migrations/_env_filters.py::include_object`.

**Convention**: every ORM model change (new column, new table, new index) MUST ship as an alembic revision under `migrations/versions/`. The Gateway runs `alembic upgrade head` automatically on startup; routine production upgrades do not require manual Alembic commands. The audited offline recovery below is an exception for the out-of-tree incarnation revision.

**Hybrid bootstrap** (`persistence/bootstrap.py::bootstrap_schema`, invoked from `persistence/engine.py::init_engine`):

| DB state                                  | Action                                  |
|-------------------------------------------|-----------------------------------------|
| empty (no DeerFlow tables)                | `create_all` + `alembic stamp head`     |
| legacy (DeerFlow tables, no `alembic_version`) | `create_all` (baseline tables only, backfill) + `alembic stamp 0001_baseline` + `upgrade head` |
| versioned (one locally known `alembic_version` row) | `alembic upgrade head`          |
| `0019_thread_incarnations` with all current ORM tables/columns | warn and skip migration |
| `0019_thread_incarnations` missing local tables/columns | refuse startup; offline recovery required |
| unknown revision, empty version table, or multiple version rows | fail closed and refuse to start |

The legacy branch handles pre-alembic databases that already have at least one DeerFlow-owned table. `create_all` runs first because stamping at `0001_baseline` makes alembic skip the baseline's own `create_table` DDL on the subsequent upgrade — so any baseline table introduced into `Base.metadata` after the user's DB was first provisioned (e.g. the `channel_*` tables from PR #1930 for users upgrading across multiple releases) would otherwise never be created, and the first request hitting that table would 500 with `no such table`. The backfill is **restricted to `_BASELINE_TABLE_NAMES`** so it does not also create tables that future revisions introduce — those revisions' own `op.create_table` would otherwise fail with `relation already exists`. A guard test pins `_BASELINE_TABLE_NAMES` against `0001_baseline.upgrade()`'s actual output, so editing 0001 to add or remove a table forces a matching update to the constant. Column-level shape (pre-#3658 vs post-#3658 vs manual-ALTER for `token_usage_by_model`) is answered by each `versions/*.py` revision via the idempotent helpers in `migrations/_helpers.py` (`safe_add_column` / `safe_drop_column`) which no-op when the change is already present and `logger.warning` on shape drift. **Adding a new ORM column / table only requires a new revision file — no edit to `bootstrap.py` is needed** *unless* the new revision adds a new baseline table (rare; only happens when a new model is part of the baseline rather than introduced by its own revision).

The empty-DB path keeps using `create_all` because `Base.metadata` is the only authoritative schema source — `create_all` renders both SQLite (JSON, type affinity) and Postgres (JSONB, partial indexes) correctly without anyone having to keep a hand-written baseline in lockstep. `0001_baseline.upgrade()` is therefore almost never executed in practice; it exists as a stamp target + chain root.

**Rolling forward compatibility**: the local chain head is `0021_batch_acceptance`
(`0018_oauth_identity_pg_partial` → `0019_projects` → `0020_threads_meta_project_id` → `0021_batch_acceptance`).
Bootstrap reads `alembic_version` while holding its backend lock and accepts
exactly one row. A locally known revision follows the normal upgrade path. The
one unknown revision `0019_thread_incarnations` is conditionally allowlisted:
bootstrap first requires every current ORM table and column, then logs a
warning and leaves the schema untouched. The original rollout shape (0018 plus
the two incarnation columns) is now rejected: it lacks `projects` and
`threads_meta.project_id`, and the batch acceptance columns. Seeding current head is only a positive compatibility
fixture; tests must also construct the original 0018-based schema and assert
rejection on both the direct startup and SQLite race-recovery paths. The check
uses `conn.run_sync` reflection and derives its local floor from `Base.metadata`
so future ORM additions cannot silently bypass it. This checks presence only;
the additive DDL audit below still owns type/constraint compatibility. Any other
unknown revision, an empty version table, or multiple version rows fails
closed. Do not broaden the allowlist without proving that old repositories can
read, insert, and update through the newer schema; nullable additive columns
are covered by `tests/test_persistence_forward_revision_compat.py`. This
exception is reviewed only for the expand-only 0019 shape: nullable VARCHAR(32)
`threads_meta.incarnation` and `mcp_tasks.thread_incarnation` columns with no
server default, table, index, constraint, or data backfill. The owning
`0019_thread_incarnations` migration must cross-pin its revision id and schema
shape against the bootstrap contract; amending that DDL requires a fresh
old-repository compatibility audit. The `0019_` numeric prefix is intentionally
reused: `0019_projects` is this tree's in-chain revision, while
`0019_thread_incarnations` is the reserved, out-of-tree rollout id allowlisted
above — revision ids only need to be unique, not numerically ordered, but the
owning rollout revision must re-parent from `0018_oauth_identity_pg_partial`
onto this tree's head when it merges so `alembic` never sees two heads off
0018. Because SQLite has no cross-process bootstrap mutex, an old process may
read 0018 immediately before another process commits 0019. If its now-stale
Alembic upgrade fails, bootstrap re-reads the version and recovers only for the
exact allowlisted 0019 with all current ORM tables and columns while that
revision remains absent from the local migration tree. Do not generalize this recovery or apply it to a binary that
owns 0019; its migration failures must remain fatal.

For an existing database with the original 0018-plus-incarnation shape, use the
[audited offline recovery procedure](../../../../../../docs/database-forward-revision-recovery.md).
Bootstrap never re-stamps an unknown revision automatically. After stopping all
writers, backing up, and verifying the exact additive schema, the operator may
purge-stamp the known 0018 parent and apply this tree's 0019/0020 migrations;
the extra nullable columns and their data remain intact. A regression exercises
that procedure from the original schema and verifies repository reads/inserts
and preservation of incarnation data.

**Concurrency safety**: Postgres uses `pg_advisory_lock` to serialise concurrent Gateway instances. SQLite uses a per-engine `asyncio.Lock` for same-process startup and is best-effort across processes via SQLite's file-level write lock + `PRAGMA busy_timeout`; multi-instance deployments should use Postgres. Column revisions in `versions/` additionally use idempotent helpers (`_helpers.py::safe_add_column`, `safe_drop_column`) so repeated post-baseline changes and retries are no-ops when the change is already present.

**Authoring a new revision**:
```bash
cd backend && make migrate-rev MSG="add foo column to runs"
```
This invokes `alembic revision --autogenerate` against the live ORM models. Review the generated file under `migrations/versions/` and switch raw `op.add_column` / `op.drop_column` calls to the idempotent helpers from `_helpers.py` before committing. There is no `make migrate` / `make migrate-stamp` target on purpose — routine upgrades execute at Gateway startup; the documented offline recovery is reserved for the audited out-of-tree schema.

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
- `migrations/versions/0017_personal_access_tokens.py` — creates the personal access token table for programmatic API access
- `migrations/versions/0018_oauth_identity_pg_partial.py` — converts `idx_users_oauth_identity` to a partial index on Postgres (`postgresql_where`), matching what `UserRow.__table_args__` already builds via `create_all`; `0001_baseline` never applied the predicate on Postgres, so every `alembic upgrade head`-provisioned deployment carried a full index until this revision. Postgres-only, idempotent (checks `pg_index.indpred` directly), no-op on SQLite (already partial via `sqlite_where`) and on a DB where the index doesn't exist yet. Originally generated as 0017 and renumbered to 0018 after 0017_personal_access_tokens merged first and kept that slot
- `migrations/versions/0019_projects.py` — creates the `projects` table (id/user_id/name/instructions/presentation/status + timestamps) for the Projects Phase-1 organization feature; chains after `0018_oauth_identity_pg_partial`
- `migrations/versions/0020_threads_meta_project_id.py` — adds nullable `threads_meta.project_id` plus `ix_threads_meta_project_id` (no FK by design: project delete clears membership first, and the reserved `deerflow_project_id` metadata key stays in sync); chains after `0019_projects`. The `0019_` numeric prefix is reused by the reserved out-of-tree `0019_thread_incarnations` — see the rolling-forward section above
- `persistence/bootstrap.py` — `bootstrap_schema(engine, backend=...)`, the three-branch provisioning decision, locked revision validation, and the narrow 0019 forward-compatibility exception
- `extensions/loader.py::load_extensions` — registers each spec's `table_prefix` with `register_extension_table_prefix()`
- Tests: `tests/test_persistence_bootstrap.py` (branches), `tests/test_persistence_bootstrap_concurrency.py` (concurrency), `tests/test_persistence_bootstrap_regression.py` (issue #3682), `tests/test_persistence_migrations_env.py` (filter, including extension-owned tables), `tests/test_extension_loader.py::TestTablePrefixRegistration` (spec-to-filter wiring), `tests/blocking_io/test_persistence_bootstrap.py` (asyncio.to_thread anchor), `tests/test_migration_0004_run_ownership_dedupe.py` + `tests/test_migration_0007_scheduled_run_active_dedupe.py` (dedupe-before-unique-index pre-steps)

- `migrations/versions/0021_batch_acceptance.py` — adds nullable per-item acceptance criteria and verdict JSON columns after `0020_threads_meta_project_id`; legacy rows remain unchecked.

# Storage adapters for application extensions

A small synchronous SQLAlchemy package for extensions that own their own tables.
It supports explicit MySQL/PyMySQL and SQLite configuration, lazy session creation,
application-provided schema initialization, transactions, and provider-owned upserts.
It has no dependency on DeerFlow, LangGraph, application models, or environment variables.

This package does **not** add MySQL support to DeerFlow's built-in authentication,
run persistence, scheduler leases or LangGraph checkpointer. Those stores are unchanged.
The package name is provisional and is not a published PyPI release.

## Install

From this directory:

```bash
pip install .                 # SQLite only
pip install '.[mysql]'        # MySQL with RSA authentication dependencies
pip install -e '.[mysql,test]'
python -m pytest tests -q
```

This example is independent of the backend workspace. Install it as a normal Python
dependency in an extension environment; no `sys.path` modifications are required.

## Use

```python
from sqlalchemy import Column, Integer, MetaData, String, Table
from deerflow_storage import Database, DatabaseConfig

metadata = MetaData()
record = Table("example_record", metadata,
               Column("id", Integer, primary_key=True),
               Column("value", String(100)))

database = Database(
    DatabaseConfig("sqlite", "sqlite:///example.db"),
    initialize=metadata.create_all,
)
try:
    with database.transaction() as session:
        session.execute(database.upsert(
            record, {"id": 1, "value": "new"}, {"value": "new"},
        ))
finally:
    database.dispose()
```

Use `DatabaseConfig("mysql", url)` for MySQL. Construct a SQLAlchemy `URL.create()`
value when credentials contain reserved URL characters. Both fields are explicit:
the library never reads environment variables or silently changes backends.
Malformed URLs and backend mismatches fail before a connection is attempted.
`DatabaseConfig` hides its URL in `repr`; callers must still avoid logging raw URLs
or database-driver exceptions containing connection details.

Use `DatabaseConfig("mysql", url, options=EngineOptions(...))` to configure per-process
connection budgets (`EngineOptions` is exported from `deerflow_storage`). Defaults:
pool size 5, max overflow 10, pool wait 30 seconds, recycle 1800 seconds, connect
timeout 10 seconds, socket read/write timeout 30 seconds. Values are validated before
connecting; unbounded/negative pool settings and nonfinite timeouts are rejected.
Socket timeouts bound individual socket operations, not an end-to-end query or request
deadline. A timed-out write may have committed: callers must reconcile its idempotency
key rather than blindly retrying the transaction. No write retry is performed here.

SQLite connections enable foreign-key checks and WAL (in-memory mode remains memory),
use FULL synchronous durability and a configurable busy wait (default 30 seconds).
`sqlite_foreign_keys=False` or `sqlite_wal=False` explicitly opt out of enabling those
features; disabling WAL setup does not change an existing file's journal mode.
WAL requires a writable database on a compatible local filesystem, not a shared
network filesystem. Enabling foreign keys can expose invalid legacy writes; existing
rows are not retroactively validated. Assess old schemas before rollout.

`database.session()` returns a caller-owned session without an implicit commit.
`database.transaction()` commits on normal exit and rolls back on exceptions.
Each session must be closed. `dispose()` is terminal and must run after workers and
sessions have stopped; create a new `Database` to connect again. Sessions are not
thread-safe; use one per unit of work. The synchronous API must be offloaded when
used from async request handlers. In-memory SQLite follows SQLAlchemy's normal
per-thread connection semantics; use a file database for multiple worker threads.

An initializer runs once on first engine/session use. If it fails, the engine is
disposed and the next call may retry. Applications own model registration, schema
migrations, DDL permissions and recovery. `create_all()` is only a minimal example,
not a replacement for a migration tool. MySQL DDL may commit independently.

## Provider contract

`DatabaseProvider` supplies `name`, `url()`, `engine(url, *, options=...)` and `upsert()`. Register an
implementation on a `ProviderRegistry` before constructing a database and pass it
as `registry=...`. Registries are independent; duplicate names are rejected.
Additional providers must supply their own SQL dialect handling and tests. No new
backend is implied by registration alone.

SQLite upsert targets the table's primary key (including composite keys); MySQL
uses `ON DUPLICATE KEY UPDATE`, which can match **any** unique key. These semantics
are not identical. Use it only where the schema's uniqueness constraints match the
application's intent. `updates` must be nonempty. `LONG_TEXT` is an optional
`Text`/MySQL `LONGTEXT` mapping; the library defines no base class or business table.

## Validation

Offline tests cover real SQLite commit/rollback, composite-key upserts, concurrent
initialization, initialization-failure cleanup/retry, registry isolation, URL
validation and MySQL statement compilation, plus foreign-key enforcement, per-connection
PRAGMAs and bounded writer contention while WAL readers continue.

For an actual MySQL integration test, set `STORAGE_TEST_MYSQL_URL` to an **isolated,
disposable test database** and run `python -m pytest tests -q`. The test creates and
drops only its randomly named table. It is skipped without explicit configuration;
SQL compilation alone does not establish compatibility with a running MySQL server.
Additional MySQL checks exhaust the configured pool, time out a slow socket read and
kill an idle test connection to verify pool recovery. The test account needs permission
to terminate its own connections. These are fault checks, not a capacity benchmark.

## Contribution scope

This directory is an optional example library for extension-owned data.
Application-specific environment configuration, business schemas, legacy imports,
backfills and production deployment records belong in the host application.
Maintainer agreement on a synchronous extension-storage API should precede a
framework-wide MySQL implementation. Async persistence, checkpoint support and
multi-instance coordination require separate design and validation.

# Persistence (`deerflow/persistence/`)

The SQL engine, repositories and models for runs, threads, scheduled tasks,
durable MCP tasks, batches and extension leases, on SQLite and PostgreSQL. Tables,
columns and status vocabularies are in the model modules. Schema changes follow
the [migrations guide](migrations/AGENTS.md). Background:
[thread lifecycle](../../../../docs/THREAD_LIFECYCLE.md),
[MCP control leases](../../../../docs/mcp-control-leases.md),
[multi-instance settings](../../../../docs/CONFIGURATION.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "persistence or repository or scheduled_task or lease or mcp_task or thread_meta"
make test-blocking-io
```

Set `TEST_POSTGRES_URI` to run the dialect-sensitive cases on PostgreSQL. A
change to a query, a lock or a JSON predicate is verified on both dialects.

## Both dialects

- **Write JSON columns through `dumps_json_safe`.** PostgreSQL `jsonb` rejects
  `NaN` and `Infinity`, and SQLite accepts them, so the fault shows only in
  production. Every engine that writes JSON is wired to it.
- **JSON filters mean the same in memory, SQLite and PostgreSQL.** Missing
  differs from null, and a boolean differs from an integer. Stored JSON integers
  can exceed 64 bits, so compare without casting a stored number to a bounded
  type.
- **`BEGIN IMMEDIATE` locks the whole SQLite database for writes.** Do slow work
  before you open the transaction, and lock only to revalidate and publish.
  Otherwise unrelated writers fail with `database is locked`.
- **`FOR UPDATE SKIP LOCKED` does not serialize SQLite readers.** A claim on
  SQLite reserves the writer before it selects.
- **A create-or-update by unique key must survive two first writers.** Both can
  miss the SELECT. Use the dialect's `on_conflict_do_update`, or roll back and
  retry the select-then-write.
- **Every engine uses the same `search_path`** when `database.postgres_schema` is
  set, including the synchronous engines for agents and skills.
- **URL normalization never drops an authentication or TLS requirement.** A
  conflicting or unsupported option is an error.
- **Create the database only on SQLSTATE `3D000`.** A missing relation, column or
  role also reads as "does not exist", and a `CREATE DATABASE` retry would hide
  it.

## Bootstrap locks

- **Poll `pg_try_advisory_lock`.** A blocking acquire is cut off by the statement
  timeout, and a second instance then fails to start while a peer migrates.
- **The bootstrap owns its lock until the migration worker thread finishes and
  the unlock completes.** Drain both through cancellation. Otherwise a second
  bootstrap overlaps a running migration, or a pooled session keeps the lock.

## Managed subagent file creation

Stage and fsync complete definitions before publishing them. The RLock is local
to one process, so create claims the destination with `os.link` and maps only
`FileExistsError` to a name conflict. Updates retain `os.replace`. Discard staging
with best-effort cleanup, preserving the original publication outcome.

## Leases, claims and terminal writes

- **A scan selects candidates; it grants nothing.** After you take the row locks,
  check status and lease expiry again. The row can have been requeued and
  reclaimed while recovery waited, also by the same process.
- **Check expiry against the database clock after the lock wait.** The
  transaction-start time is already stale. A lease that expires exactly at scan
  time is still live.
- **An owned run write requires the owner and a live lease.** This covers terminal
  writes and `merge_owned_metadata`. Take the change clock before the run row lock;
  the documented lock order has no exception.
- **A heartbeat store declares the owner-fenced keywords explicitly.** A method
  that accepts `**kwargs` gives no atomic guarantee, so the manager skips the
  call and reports it. An unsupported owned call fails closed.
- **These fences are scoped guards.** They cannot tell a deleted and recreated
  run with the same ID, owner and outcome from the original.
- **An `ExecutionFence` is data, not authority.** The Gateway binds it to the
  current plugin and user. When the extension generation is stale, a fenced
  cancel never falls back to a local cancel.
- **Lease renewal changes the expiry only.** It must not touch `updated_at` or
  overwrite a cancellation that arrived in between.

## Scheduled tasks and MCP tasks

- **One method owns reactivation**: `ScheduledTaskRepository.update`. A new path
  that enables a task goes through it, so the end-condition check cannot be
  skipped.
- **At most one active occurrence exists per task**, enforced by a unique index.
  The queue survives a restart, and only a lease-fenced launch calls the Gateway.
- **Recovery never takes over a live run.** It finalizes an occurrence whose
  durable run row is already terminal, and it returns expired launch claims to
  the queue.
- **The scheduler is single-instance by default.** Multi-instance mode needs
  shared PostgreSQL and the settings that startup validates.
- **Run-history filters are occurrence states**, not task states. Apply the
  owner check before reading history and the predicates before pagination.
- **A claimed MCP notification always carries a dispatch event.** A pending
  snapshot whose condition resolved before delivery is consumed at claim time.
- **The database is the source of truth for durable MCP tasks.** The agent only
  submits. The remote handle and the polling stay out of the agent loop.
- **A paused batch is reconciled but not advanced.** Lease recovery includes a
  paused parent with expired items, and skips promotion and claiming.

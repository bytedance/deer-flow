# Persistence lifecycle

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

Acquire that lock by polling `pg_try_advisory_lock`, never with a blocking `pg_advisory_lock`: the app engine's asyncpg `command_timeout` bounds every statement, so a blocking acquire fails a second instance's startup whenever a peer's migration outlasts it.

`init_engine` auto-creates a Postgres database only on SQLSTATE `3D000`. Missing relations, columns and roles also "do not exist"; a `CREATE DATABASE` retry would mask them.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

Alembic stamp/upgrade workers started inside `bootstrap_schema()` remain owned by the bootstrap critical section until the worker finishes. Drain those `asyncio.to_thread()` calls across host cancellation before releasing the in-process SQLite bootstrap lock or PostgreSQL advisory lock; otherwise another bootstrap can overlap a still-running migration worker.

On SQLite, `BEGIN IMMEDIATE` takes the database-wide write lock, so every unrelated writer (run status, thread metadata, the scheduler) waits for the transaction and fails with `database is locked` after `busy_timeout` (30s). Do slow work such as document conversion before opening a locked transaction; lock only to revalidate and publish, as `ProjectDocumentRepository.publish_under_live_lock` does. `tests/test_project_document_tools.py::TestConversionSerialization` pins this.

## Unique-key upserts

A repository method that creates or updates a row by a unique key must survive two first writers: both can miss the SELECT, and the later INSERT raises `IntegrityError`, a 500 for the caller. Use a dialect `on_conflict_do_update` when every key column is non-null, or retry the select-then-write after rolling back the session, as `ChannelConnectionRepository.upsert_connection` / `set_thread_id` and `FeedbackRepository.upsert` do. Feedback keeps the retry because `user_id` is nullable and a NULL key never conflicts, so ON CONFLICT would stop updating the NULL-user row.

## JSON integer filters

Stored JSON integers are not bounded by the signed-64-bit filter input contract.
SQLite predicates must check the extracted SQL value's `typeof`, not only JSON
`json_type`, to exclude oversized integers decoded as REAL. PostgreSQL predicates
compare integer text (including `-0` for zero) without casting arbitrary stored
numbers to BIGINT or NUMERIC. Preserve integer/float/boolean/string distinctions.
`tests/test_json_integer_matching.py` exercises both dialects; PostgreSQL opts in
with `DEERFLOW_TEST_POSTGRES_URL` and uses connection-local temporary tables.
## Scheduled-task lifecycle

Scheduled-task lifecycle rules live in one place each. `ScheduledTaskRepository.update` is the single reactivation choke point: any `status -> enabled` from a non-enabled row re-checks `end_condition_reached` after applying the same request's renewal fields and raises `ScheduledTaskLimitsExhausted` (HTTP/tool `limits_exhausted`). The same method moves `unmet_streak_after_seq` when `goal_objective`, `prompt` or `stop_condition` actually changes (`append_standing_note` too; Resume never), and `_unmet_streak` skips both rows at/below that boundary and goal-check failures (`finalization.CHECK_FAILURE_CODES`). A host pause marker (`is_host_pause_marker`) survives a manual trial on a paused task. A trial launched before a `once` task's run time is not that run: the parent keeps its status and `next_run_at` instead of the once outcome (`projection.once_run_still_scheduled`, applied at launch, in `finalize_occurrence` and in the launch repair). A manual `interval`/`cron` trial never advances `next_run_at`, even when it is already overdue (`scheduler.schedules.should_advance_schedule_cursor`, shared by the launch, finalization and launch-repair paths). The single-active-occurrence slot blocks the due scheduled run while the trial is active; after the trial finishes, the overdue occurrence remains claimable once, and its catch-up dispatch advances the cursor from the dispatch time. `tests/test_scheduler_manual_once_trial.py` pins both early trials and missed-slot catch-up for interval and cron tasks. `update_after_launch` clears the parent's dispatch lease only for a write with no occurrence row: an occurrence's launch write never owns it, so a lease there is a newer due-task claim. A task is finished (`completed` by `max_runs`/`end_at`) only by `finalize_occurrence` or `finish_task_at_end_condition` (both in `scheduled_task_runs/finalization.py`), which report `task_stopped`/`task_paused`/`task_finished` to the finalization observer on a live -> paused/finished transition only, inside the caller's transaction; `test_no_inline_end_condition_completion` fails on any other `status = "completed"` in the two repositories. The scheduler's observer (`ScheduledTaskService._on_finalization`) is always installed and writes `scheduled_task_events` rows for the originating chat in that transaction; its lookups fall back on bad stored data and only database errors propagate, because it runs inside batch recovery. Pausing a terminal task returns `"finished"`. `stop_condition` has its own column; only `ScheduledTaskService` composes it into the launched message (`scheduler/stop_rule.launch_prompt`), so never write it into `prompt`. REST and capability validation share `app/gateway/scheduled_task_validation.py`, and every error raised there, in `routers/scheduled_tasks.py` and in `scheduled_task_access.py` uses `scheduler_error(status, code, message, **params)` with a code listed in `contracts/scheduled_task_errors_contract.json` (request models declare types only, so value rules never become FastAPI list details).

The per-owner run cap `scheduler.max_concurrent_runs_per_user` is effective `min(per_user, max_concurrent_runs)` (0 = off) and is checked in `claim_queued_run` right after the global count, under the same budget lock. `list_queued_runs` ranks same-thread FIFO heads per owner (`ROW_NUMBER() OVER (PARTITION BY owner)`) and orders the batch by that rank, so the drain is owner-fair even with the cap off; owners at their cap drop out before the batch limit, and orphan rows (task deleted while queued) are never held back by the cap. Scheduled-task repository boundaries coerce serialized timestamps before SQL `DateTime` binding.

Recovery locks task/run pairs in task-id/run-id order and restores `run_id`, `started_at` and live errors before releasing launch claims. Launch/failure/timeout updates use one parent-first transaction to prevent interleaved claims. Queue timeout fails the occurrence and advances scheduled work to prevent immediate requeue.

Single-instance polling also performs a non-destructive terminal-run reconciliation: a `running` occurrence whose durable `runs` row is already terminal is finalized from that row's status, error and goal verdict. Live runs are never taken over or interrupted; multi-instance reconciliation already covers terminal runs through lease ownership. This repairs a completion hook that failed after the run committed its terminal status.

Expired-launch scans select candidates, not ownership. After taking the parent
and occurrence locks, recheck launch status and lease expiry before recovery.
A busy launch may have requeued and a manual trigger reclaimed the same row
while recovery waited; the new claim can have the same process owner. Preserve
its full row and execution-budget slot. A lease equal to scan time is still live;
missing or strictly older leases remain recoverable.

## MCP task notifications

`mcp_tasks/sql.py::claim_notification_work` never returns a row without a dispatch event. A pending snapshot whose condition resolved before delivery (tracking recovered, or an answered `input_required` prompt returned the task to `working`) is consumed at claim time: `notified_version` advances, the content fingerprint clears so an identical later event is recorded again, stale error/attempt/dispatch state clears, status returns to `none`, and the claim lease is released instead of launching an empty event. A legacy row left without a dispatch event is consumed only when nothing newer exists; a newer recorded event is rebuilt and claimed instead. Consumption is a conditional UPDATE fenced on the event version and phase the claim read, so a concurrent newer event (SQLite has no row locks) is never acknowledged and stays claimable. Coverage: `tests/test_mcp_task_repository.py` (resolved snapshot, legacy retry, expired-claim reclaim, identical-event recurrence, interleaved newer completion, legacy launching/dispatched with and without a newer completion).

## MCP control leases

`McpTaskRepository` retains upstream poll claims' eligibility-fenced UPDATE after candidate selection, so an interleaved cancellation or competing claim is not overwritten. Cancel claims reserve the SQLite writer before SELECT; `FOR UPDATE SKIP LOCKED` alone does not serialize SQLite readers. Renewal is one owner/token/phase/expiry-fenced UPDATE and changes only lease expiry, explicitly preserving the ORM `updated_at` column. A stale generation, expired lease, terminal task or changed cancellation phase cannot renew. Keep local draining-row exclusions before LIMIT. See [control-call leases](../../../../docs/mcp-control-leases.md).

## Run terminal authority and lease expiry

`RunRepository.update_status(..., owner_worker_id=...)` and
`finalize_if_not_cancelled(..., owner_worker_id=...)` require that owner and a
live lease. Increment the change clock before taking the run row lock to retain
the existing clock/row lock order. PostgreSQL checks `clock_timestamp()` after
`SELECT FOR UPDATE`, rather than transaction-start `now()`; SQLite evaluates its
database clock in the conditional UPDATE after acquiring its writer lock.
`renew_lease` and legacy `update_lease` also reject expired existing leases and
already-expired target leases. `allow_interrupted=True` additionally permits
interrupted rows for the owning Worker's unfinished rollback; Manager requires
its own interrupted ACK and a rollback barrier before requesting it. Success/error
remain ineligible, and owner/live-lease conditions are identical. Atomic admission
returns immutable outcome snapshots of its committed claimed rows; a subsequent
interrupted -> error write must not mutate an earlier ACK (including in Memory).
Success returns only after transaction commit.
`update_run_completion(require_terminal=True, owner_worker_id=...)` requires the
exact terminal status/owner atomically and leaves outcome fields unchanged;
it cannot transition an active row. Metadata may arrive after the terminal lease
expires: it authorizes no execution or outcome transition, and Manager already
requires its own matching ACK. The owner/status predicate protects against a
changed row, but cannot distinguish deletion/recreation with the same run ID,
owner and outcome without a persistent generation. Third-party heartbeat stores
must implement these keyword contracts and atomic predicates, returning explicit
commit results; accepting `**kwargs` alone does not establish that guarantee.
For strict completion, explicitly declare both `require_terminal` and
`owner_worker_id`, or set `supports_terminal_completion_kwargs=True` on the class
defining `update_run_completion`. A flag-only child cannot opt in an inherited
method, and an override must declare its own opt-in. Manager skips unsupported
completion calls with a diagnostic before invoking the Store.
Unsupported owned calls fail closed; single-worker legacy calls remain supported.
These are scoped guards, not a generation
protocol covering every mutation. Contract/lock-wait tests live in
`tests/test_terminal_store_contract.py` (Postgres uses `TEST_POSTGRES_URI`).

## Extension execution fences

Migration 0047 owns `extension_execution_leases`. Public `ExecutionFence` carries
namespace/resource/holder/epoch, not authority: Gateway binds it to the current
plugin and user. SQL run admission and fenced cancellation take the run change
clock first, then lock the lease row and check the database clock after lock wait,
retaining that lock through commit. Unsupported stores fail closed. Fenced cancel
persists a request for the existing run owner; never fall back to local cancellation
when the extension generation is stale. Extension-owned state/quota/control logic
stays in its package. Tests: `test_extension_execution_fence.py` (PostgreSQL via
`DEERFLOW_TEST_WORKFLOW_POSTGRES`).

# Persistence lifecycle

Postgres bootstrap owns its session-scoped advisory lock until `pg_advisory_unlock` completes. Drain that unlock across host cancellation before leaving the SQLAlchemy connection context; repeated cancellation must not return a pooled session while it still holds the bootstrap mutex. Ordinary database errors remain best-effort and are logged.

Acquire that lock by polling `pg_try_advisory_lock`, never with a blocking `pg_advisory_lock`: the app engine's asyncpg `command_timeout` bounds every statement, so a blocking acquire fails a second instance's startup whenever a peer's migration outlasts it.

When `database.postgres_schema` is configured, both async ORM connections and the synchronous SQLAlchemy connections used by DB-backed custom agents and managed subagents must use the same `search_path`; preserve this invariant when adding another persistence entry point.

Alembic stamp/upgrade workers started inside `bootstrap_schema()` remain owned by the bootstrap critical section until the worker finishes. Drain those `asyncio.to_thread()` calls across host cancellation before releasing the in-process SQLite bootstrap lock or PostgreSQL advisory lock; otherwise another bootstrap can overlap a still-running migration worker.

On SQLite, `BEGIN IMMEDIATE` takes the database-wide write lock, so every unrelated writer (run status, thread metadata, the scheduler) waits for the transaction and fails with `database is locked` after `busy_timeout` (30s). Do slow work such as document conversion before opening a locked transaction; lock only to revalidate and publish, as `ProjectDocumentRepository.publish_under_live_lock` does. `tests/test_project_document_tools.py::TestConversionSerialization` pins this.

## JSON integer filters

Stored JSON integers are not bounded by the signed-64-bit filter input contract.
SQLite predicates must check the extracted SQL value's `typeof`, not only JSON
`json_type`, to exclude oversized integers decoded as REAL. PostgreSQL predicates
compare integer text (including `-0` for zero) without casting arbitrary stored
numbers to BIGINT or NUMERIC. Preserve integer/float/boolean/string distinctions.
`tests/test_json_integer_matching.py` exercises both dialects; PostgreSQL opts in
with `DEERFLOW_TEST_POSTGRES_URL` and uses connection-local temporary tables.
## Scheduled-task lifecycle

Scheduled-task lifecycle rules live in one place each. `ScheduledTaskRepository.update` is the single reactivation choke point: any `status -> enabled` from a non-enabled row re-checks `end_condition_reached` after applying the same request's renewal fields and raises `ScheduledTaskLimitsExhausted` (HTTP/tool `limits_exhausted`). The same method moves `unmet_streak_after_seq` when `goal_objective`, `prompt` or `stop_condition` actually changes (`append_standing_note` too; Resume never), and `_unmet_streak` skips both rows at/below that boundary and goal-check failures (`finalization.CHECK_FAILURE_CODES`). A host pause marker (`is_host_pause_marker`) survives a manual trial on a paused task. A task is finished (`completed` by `max_runs`/`end_at`) only by `finalize_occurrence` or `finish_task_at_end_condition` (both in `scheduled_task_runs/finalization.py`), which report `task_stopped`/`task_paused`/`task_finished` to the finalization observer on a live -> paused/finished transition only, inside the caller's transaction; `test_no_inline_end_condition_completion` fails on any other `status = "completed"` in the two repositories. The scheduler's observer (`ScheduledTaskService._on_finalization`) is always installed and writes `scheduled_task_events` rows for the originating chat in that transaction; its lookups fall back on bad stored data and only database errors propagate, because it runs inside batch recovery. Pausing a terminal task returns `"finished"`. `stop_condition` has its own column; only `ScheduledTaskService` composes it into the launched message (`scheduler/stop_rule.launch_prompt`), so never write it into `prompt`. REST and capability validation share `app/gateway/scheduled_task_validation.py`, and every error raised there, in `routers/scheduled_tasks.py` and in `scheduled_task_access.py` uses `scheduler_error(status, code, message, **params)` with a code listed in `contracts/scheduled_task_errors_contract.json` (request models declare types only, so value rules never become FastAPI list details).

The per-owner run cap `scheduler.max_concurrent_runs_per_user` is effective `min(per_user, max_concurrent_runs)` (0 = off) and is checked in `claim_queued_run` right after the global count, under the same budget lock. `list_queued_runs` ranks same-thread FIFO heads per owner (`ROW_NUMBER() OVER (PARTITION BY owner)`) and orders the batch by that rank, so the drain is owner-fair even with the cap off; owners at their cap drop out before the batch limit, and orphan rows (task deleted while queued) are never held back by the cap. Scheduled-task repository boundaries coerce serialized timestamps before SQL `DateTime` binding.

Recovery locks task/run pairs in task-id/run-id order and restores `run_id`, `started_at` and live errors before releasing launch claims. Launch/failure/timeout updates use one parent-first transaction to prevent interleaved claims. Queue timeout fails the occurrence and advances scheduled work to prevent immediate requeue.

## Tenant schema foundation

`0036_tenant_workspaces` appends to the audited `0035` join. Native tenant
control-plane tables live in `workspaces/model.py` and register with shared
Base.metadata. Resource workspace_id columns remain nullable during explicit
legacy backfill. DDL never guesses owners or marks email verified. An existing
channel_connections.workspace_id is a provider workspace identifier, not the
DeerFlow tenant; do not reuse it as tenant authority. This schema alone does not
enable tenant access. Controlled backfill, both database receipts and admission
coverage remain required before multi-tenant activation.

`workspaces/backfill.py` is an explicit offline native metadata operation, never
startup recovery. `plan_personal_backfill` is read-only; apply requires a caller
transaction, stopped writers and coherent operator backups. It serializes its
maintenance path, refuses after team provisioning, and never repairs unknown or
contradictory owners. Parent resources precede children; source data remains.
Plans/quarantine identifiers belong in private receipts, public logs only counts.
Native backfill alone does not satisfy executor or NAS rollout prerequisites.

`export_native_workspace_bindings` reads only thread/run ownership metadata
after completed personal backfill and exact personal owner membership checks.
It excludes quarantine, binds each run to its matching thread and produces a
private versioned DTO for executor attribution. Keep writers fenced across both
database phases; this export is not live membership authorization.

`workspaces/sql.py` uses the native async session factory for personal/team
provisioning and live membership reads. Tenant mode requires persistent SQL;
the disabled factory returns None and does not create an ephemeral authority.
Provisioning and membership access require active, verified native accounts.
Personal IDs share the offline backfill namespace. Team create idempotency is
bound to actor, request key and name; replays recheck live membership.
Membership mutations lock the workspace first (SQLite BEGIN IMMEDIATE; Postgres
FOR UPDATE). Role changes increment membership version; owner transfer flushes
the prior owner's downgrade before promotion in one transaction, preserving the
active-owner index. Direct last-owner removal/demotion is refused. Reads filter
workspace/member/account state in SQL and do not confer platform-admin bypass.
This repository is not yet Gateway wiring: callers must authenticate actors,
apply native credential scopes and enforce recent reauthentication for transfer.
Internal add_member is for managed/invitation services, not a public invite bypass.
HTTP control callers supply an expected immutable context; writes compare its
actor, workspace and live versions under the workspace lock. Password-proved
transfer additionally locks the native account row while checking persisted
token version/password hash, serializing with native password/token updates. Member
disclosure applies actor access in the same SELECT. Gateway lifecycle wiring,
invitations and revocation effects remain acceptance gates.

`workspaces/scope.py` reuses the native live membership query for resource SQL
predicates and fences writes with workspace -> native actor -> resource locking
(SQLite BEGIN IMMEDIATE first). ProjectRepository accepts a trusted explicit or
task-local WorkspaceContext; workspace_required instances refuse missing scope.
Private project reads retain native owner filtering and selected workspace,
and write checks happen within their mutation transaction. Delete refuses any
incompatible document/thread child before trash or unlink statements. Default
legacy mode retains existing ownership behavior. Shared project/document progress is recorded below; scoped threads and background
coverage still need implementation. No activation is implied.


ProjectDocumentRepository scopes insert/dedup/list/count/snapshot/get/trash by
project ACL, workspace, live versions and matching project. Mutations use the
same workspace -> actor -> project -> document order. Required scope is captured
at native bootstrap. Scoped conversion and trash maintenance are refused
until integrated, including absent scope on required repositories. Commit-error
reconciliation must not treat a scoped invisible row as proof of rollback or
remove bytes that a committed row may still own. Thread, conversion and retention integration remain M3/M8 work.


Project sharing revision `0037_project_visibility` appends after unchanged 0036.
Project.visibility is non-null, private by default, with a two-value CHECK in
both ORM and migration. Shared SQL scopes use a live team predicate; write
predicates additionally require owner/admin. Documents inherit parent-project
ACLs instead of treating uploader identity as a separate shared-data grant.
Scoped project delete trashes all compatible authors' document rows atomically;
foreign/null-scope children still refuse. Native backfill and independent
executor export consumption both require the current native head. Keep past
receipts immutable; e0002 executor schema is unchanged.

ThreadMetaRepository accepts workspace_required and consumes trusted task-local scope. Reads and pagination combine original owner, selected workspace, live membership and parent-workspace consistency. Private thread history remains owner-private when its project visibility changes; project source access must separately use current ProjectRepository ACL. Association locks workspace -> actor -> project; row mutations lock workspace -> actor -> thread. Workspace mode refuses orphan claiming, owner reassignment and user_id=None bypass. make_thread_store cannot fall back to memory when scope is required. Gateway admission must bind scope before native owner checks; remaining runtime/background coverage is not implied by this repository foundation.

Scoped stage_live_copy adds workspace/actor/project locks before the document lock
and read ACL; archived source projects remain readable. Its file-copy callback is
drained before releasing the transaction. Thread-origin insert_active additionally
locks/checks the owner-private source in the same workspace before publication.
ThreadMetaRepository.publish_under_live_lock fences only short file operations
under workspace/actor/thread locks. Callers must not put model or network work in
that callback. Controlled withdrawal/cancellation and physical mount checks remain
required; isolated byte-level mains do not close those gates.

Current native head is 0038_workspace_read_clocks; workspace_thread_read_versions
uses (workspace_id,user_id) PK and a non-null BIGINT zero-default version. Legacy
per-user clocks/marker PKs stay unchanged. ThreadReadRepository captures the
operator workspace_required flag, consumes trusted scope and filters run rows
by matching owner-private thread/workspace before unread/max-position queries.
Marker mutation locks workspace -> actor -> thread and updates its workspace
clock only when the native monotonic marker moves. Version reads use one live
membership SELECT; missing required scope is refused. Scoped delete_by_thread
is refused pending thread lifecycle integration, never blind all-viewer cleanup.
Current offline native/executor ownership receipts require 0038/e0002; physical
paired rollout, activity/run feeds and lifecycle acceptance remain required.

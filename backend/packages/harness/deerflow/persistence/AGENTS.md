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

Read-clock revision 0038_workspace_read_clocks (now followed by 0039); workspace_thread_read_versions
uses (workspace_id,user_id) PK and a non-null BIGINT zero-default version. Legacy
per-user clocks/marker PKs stay unchanged. ThreadReadRepository captures the
operator workspace_required flag, consumes trusted scope and filters run rows
by matching owner-private thread/workspace before unread/max-position queries.
Marker mutation locks workspace -> actor -> thread and updates its workspace
clock only when the native monotonic marker moves. Version reads use one live
membership SELECT; missing required scope is refused. Scoped delete_by_thread
is refused pending thread lifecycle integration, never blind all-viewer cleanup.
Current offline native/executor ownership receipts require 0040/e0002; physical
paired rollout, activity/run feeds and lifecycle acceptance remain required.

RunRepository read scope consumes trusted task-local context and the operator
workspace_required setting captured at bootstrap. Its SQL combines Run owner/space
with the compatible private ThreadMeta predicate before pagination, cursor lookup
or token reduction. Scope validation precedes empty batch returns. Default unbound
legacy mode is preserved. Run admission, operation cleanup, global worker recovery
and HTTP feeds are not yet integrated; do not infer activation from read tests.

Scoped non-run reject reservations lock workspace -> actor -> private thread,
then preserve clock -> Run row order and persist workspace_id. Invisible global
idempotency conflicts never return a foreign payload. Operation release uses
captured workspace/user/worker and excludes normal runs; it deliberately does
not require live membership/parent so withdrawal/deletion cannot strand cleanup.
This release is not authority for reads/publication. Normal scoped Run lifecycle
and HTTP goal/state writers remain unintegrated; activation stays refused.

ThreadMetaRepository.commit_checkpoint_under_live_lock is a dedicated final
checkpoint commit fence, separate from file publication. Callers hold durable
non-run admission, capture incarnation before preparing state and construct
graphs outside SQL locks. The fence rechecks workspace/actor/thread/incarnation
and drains prepared native checkpoint IO while authorization/lifecycle locks
remain held. It cannot make separate checkpoint/metadata databases atomic; never
put model/tool/graph setup in the callback. Crash/cancellation acceptance remains
required beyond the current actual HTTP withdrawal/incarnation evidence.

publish_branch_from_private_source is a tenant-only native branch publication
transaction. It rechecks live source ownership/incarnation and current project
assignability, adds and flushes child metadata in the same transaction, drains
only prepared native checkpoint IO and commits metadata afterwards. Graph setup
and file staging must occur before it, under durable source branch admission.
Private files remain unpublished until metadata exists. It is not a cross-store
atomic transaction; uncertain commits cannot authorize file cleanup. Orphan
staging/retention and fault acceptance remain separate required work.

ThreadDeletionRepository is a tenant-only lifecycle helper sharing ThreadMeta's
session factory, not a new execution authority. Native delete reservations may
see tombstones; other scoped reads/mutations may not. begin validates incarnation
and child attribution before persisting deleting plus a private receipt token.
finish locks workspace -> actor -> exact parent and verifies receipt before
precise child/marker deletion; native reservation release remains independent.
No unknown cleanup replay is authorized. publish_under_live_lock requires the
captured incarnation whenever scope is bound, including rejected-upload cleanup.
Do not silently look up and adopt a replacement incarnation. #62 proves the
local HTTP mains; remote STOP, Run cache/background writers and crash recovery
remain integration requirements, so compiled tenant activation stays closed.

RunRepository advertises supports_workspace_reads and freezes the public
workspace_scope_required capability from its constructor flag, so native
RunManager can validate cached reads without binding to a concrete SQL class.
Its existing scoped get/get_many predicates remain the authorization authority;
a capability flag alone does not authorize any record. #67 confirms resident
filtering/withdrawal/deletion/fault refusal with both SQL dialects.

RunRepository.can_observe_private_run is a read-only delivery predicate, not
admission or execution authority. It checks a normal Run, original private
thread incarnation and live workspace/actor, plus captured token version,
setup/role/OAuth principal attributes in one statement. _read_scope keeps its
legacy default and accepts optional thread_incarnation for this check.
The Gateway owns JWT expiry and native route permission evaluation; no SQL
writer lock spans delivery. Producer lease/generation scope remains M4.

FeedbackRepository scopes reads using original actor/thread/Run relations;
compatible workspace, private parent and live versions precede limit/count/
grouping. Scoped user writes require captured entry incarnation and the standard
workspace -> actor -> thread -> Run -> feedback lock order. ID deletion discovers
only a locator in a separate read session and rechecks after locking. Bulk
workspace cleanup must use the canonical ThreadDeletion receipt, not generic
feedback.delete_by_thread. Unbound stats defaults remain all-owner; scoped
callers pass the explicit actor. Constructor workspace_required is not yet full
runtime-factory activation. #82 evidence/limits live in workspace progress JSON.


0039_run_workspace_identity follows unchanged 0038 (current head is 0040). It adds
nullable runs.workspace_context_json and runs.thread_incarnation without
backfilling live authority. Scoped atomic short-operation admission captures
immutable WorkspaceContext and parent incarnation under the existing private
thread lock. RunRepository advertises supports_workspace_admission; scoped normal Run
reject admission and pending transitions are now integrated as documented below.
Interrupt/rollback admission remains refused. Legacy put
refuses bound workspace callers and any existing workspace row, including
unbound callers, rather than retargeting a captured identity. Dedicated scoped
worker write/recovery methods remain M4 work. Backfill/export and executor import
agree on current 0040/e0002 but do not fabricate permission snapshots for history.


M4 pending execution: scoped create_thread_operation_atomic admits normal Runs
only with reject strategy, retaining the lock-captured identity snapshot.
find_by_idempotency_key and durable conflict recovery additionally join the
current private parent's incarnation to the original Run; do not reuse a row
across parent replacement. start_run and transfer_pending receive the captured
context/nonce, lock workspace -> actor -> parent -> clock -> Run, validate live
membership and exact stored identity, then execute the native pending/owner/
cancel CAS. Legacy unbound calls require workspace_id IS NULL and cannot touch
a scoped row. A denied CAS must preserve the pending row and its owner/lease.
These start/transfer fences do not authorize terminal publication, lease renewal,
recovery, cancellation, remote dispatch or external writes; all remain M4 work.


0040_mcp_workspace_identity is the native head after unchanged 0039. It adds
nullable mcp_tasks.workspace_context_json with no historical authority backfill.
McpTaskRepository fixes workspace_scope_required at construction. Scoped submit
validation locks workspace -> native actor -> private parent -> source Run,
checks immutable identity and current executing owner/lease/cancel intent, then
releases before IO. Create repeats the checks in its insert transaction. Poll
validation/result commit lock that source and exact task, validate original
scope and native claim token; the source may have ended while the durable task
continues. Resource reads filter private scope before limits. Legacy unbound
snapshot writes require workspace_id NULL. Mandatory workers skip unattributed
legacy rows; unsupported scoped cancellation/notification cannot use legacy
claims. Releasing retry diagnostics is not permission to publish a result.
Native backfill/export and executor import require 0040/e0002; release/schema
startup alignment and full M4 control/publication/physical evidence stay pending.

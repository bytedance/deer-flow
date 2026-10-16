# Workspace HTTP control plane (implementation in progress)

The first M2 adapters are verified in an isolated ASGI composition with the
production AuthMiddleware, CSRFMiddleware, JWT implementation, SQL user
repository and RBAC provider. They are now registered by the shipped Gateway;
workspace admission is resolved once at native database bootstrap. The default
service is inactive. No tenant deployment or public registration has been performed.
Full resource isolation is not complete. The project CRUD integration below
is verified separately. Private and explicitly shared project documents now have
real file evidence. Thread files, client integration and background entrypoints
still need integration.

## Implemented adapter contracts

| Method/path | Authentication and behavior |
| --- | --- |
| GET /api/workspaces | Browser session plus native workspaces:read. SQL returns only active memberships, active spaces and an active verified account. |
| GET /api/workspaces/current | Same permission. X-Deerflow-Workspace selects an opaque canonical UUID, then the server checks live membership. Without the header, only the actor's personal space can be selected. |
| POST /api/workspaces | Browser session plus native workspaces:write; strict name/idempotency_key body. The same native team provisioner creates owner membership and quota transactionally. |
| GET /api/workspaces/{workspace_id}/members | Session and native read permission; active members disclosed only to a live member. |
| PATCH /api/workspaces/{workspace_id}/members/{user_id} | Native write permission; current owner assigns admin/member, never directly demotes the owner. |
| DELETE /api/workspaces/{workspace_id}/members/{user_id} | Owner removes non-owners, admin removes ordinary members, non-owner may leave. |
| POST /api/workspaces/{workspace_id}/leave | Removes the authenticated non-owner; last owner must transfer or close first (409). |
| POST /api/workspaces/{workspace_id}/ownership-transfer | Current owner, native write permission and fresh local-password proof; active verified target member required. |
| POST /api/admin/workspaces | Browser session, native workspaces:write and native platform administrator role. Strict owner_user_id, kind, name and idempotency_key body; owner must be active and verified. Uses the same personal/team provisioner and grants the operator no membership or content bypass. |

Missing authentication is 401; missing native permission/role is 403; unknown
or unauthorized selected space/resource is 404; onboarding/idempotency conflicts
are 409; extra client fields are 422. The full Gateway must retain its existing
CSRF/Origin middleware when registering these routers. Middleware-less API
composition is not supported: the management dependency requires the native
session source and matching authenticated AuthContext.

A missing app.state.workspace_service returns 503. `workspaces.enabled` is a
strict boolean, false by default, and startup-only. The native bootstrap invokes
`validate_workspace_bootstrap` after database initialization and before
checkpointer/Store creation, extension services or RunManager recovery. An
enabled mode requires persistent SQL, authenticated callers and the exact
supported native schema. Any team row, including a closed team, prevents legacy
startup against that database. This check does not fence an already-running peer
or detect a database that the operator removed from configuration; M10 owns the
paired release/generation controls.

The current compiled runtime coverage gate refuses activation even with valid
operator YAML. M3-M11 still need resource/files/background isolation and paired
rollout evidence. There is no operator override for this missing implementation;
public registration stays closed for tenant delivery. Do not assign service state
from an API request. Completing route registration is not tenant activation.

## Trusted identity and resource checks

`WorkspaceService.resolve_context(actor_user_id, selector)` reads live SQL and
constructs the immutable WorkspaceContext. The selector is never an actor or
membership assertion. `revalidate` rejects missing, inactive or changed
membership/policy versions. Client context dictionaries are not accepted.

`authorize_resource` requires the authenticated native actor to match that
context, rechecks current membership and versions, requires resource workspace
equality and the exact native permission/action, then enforces visibility:
private content belongs only to its owner; explicitly workspace-visible content
is readable by members and writable/deletable only by owner/admin with the
native permission. Unknown visibility and unscoped resources are refused.
Platform system_role=admin confers no additional resource rights.

These helpers do not replace resource repository filters or publication locks.
M3 must scope actual lists/counts/downloads/caches and bind requests/runs; M4
must repeat checks at background claim/effect/publication points. PAT and
internal channels need their own validated persisted/signed bindings rather
than using the browser management dependency. Member-control writes compare server-resolved membership/policy versions
again under the workspace transaction lock. Transfer also rechecks the native
password hash and token version under the native account row lock before
committing. A credential reset already holding that row commits first, so the
waiting transfer sees the new token version and refuses its old proof. The explicit workspace URL
is a selector; a conflicting header returns 404. Wrong local-password proof is
401; direct last-owner departure is 409. Passwordless SSO transfer currently
returns 409; its reauthentication flow remains an M6 acceptance requirement.
Invitation acceptance and background revoke effects remain pending.

## Evidence

`backend/tests/test_workspace_http.py` runs one actual JWT/RBAC/CSRF/native-SQL
main on each database. It proves operator-created personal access, no platform
admin bypass, actor-field rejection, same-user personal/team resource isolation,
foreign member rejection, native permission denial despite owner membership,
and stale policy context rejection. The same main exercises member listing,
role transitions, stale member versions, protected-owner removal, incorrect and
correct native-password transfers, last-owner departure refusal and removed
member access denial. Fixture member activation uses the internal SQL service;
it does not prove the email invitation workflow. Its project proof endpoint exercises the
helper against an actual SQL row; it is not a claim about all production
project/file routes. Exact Jenkins artifacts and source hashes are retained in
[implementation progress](tenant-workspaces-progress.json).

## Project CRUD integration (partial M3)

The production project router now passes a server-resolved workspace context to
the native SQL repository when workspace services are present. Create persists
the selected workspace while retaining the real native user ID. List/get/patch,
archive/restore and delete combine private project ownership or explicit shared
project ACL, selected workspace and live account/membership/policy versions in SQL. Filtering happens before
materializing the list, not after returning another space's rows. Missing headers
select only the personal space. Client ownership/workspace fields are rejected.

Writes lock workspace, native actor and then project; SQLite obtains its write
lock first. They recheck current versions before mutation. Scoped deletion refuses
incompatible document/thread children instead of cascading into another space.
Persistent HTTP mutations drain before request cancellation completes. A repository
created with workspace_required=True refuses calls without explicit or trusted
task-local scope; Gateway derives this requirement from its startup snapshot.

Projects default to native-owner private. Explicit workspace visibility is now
implemented as described below; no platform-admin bypass or tenant activation
is implied.
The project thread-list endpoint now uses trusted session scope and lists only
the current user’s private threads after current project ACL authorization. It
retains existing behavior in legacy mode. PAT handling
and background caller bindings remain M4 work. None of this opens the compiled
tenant activation gate.

The existing JWT/CSRF/RBAC main now calls the actual production project router on
SQLite and PostgreSQL: persisted scope, personal/team lists and direct accesses,
cross-space mutation refusal, normal patch/archive/restore/delete, stale scope,
mandatory scope and refusal to delete a foreign-scope document child. The child
fixture is metadata only; no physical file or NAS acceptance is implied.


## Private project documents (partial M3)

The production shelf router binds a server-resolved native-session workspace
for upload, list/count, inline content/download and individual trash. Native
project permissions remain required. Upload preflight checks the project before
staging; the mutation locks workspace, native actor and active project before
placement/insert. Rows retain the actual user and persist the selected workspace.
Reads and counts filter workspace, inherited project ACL, live account/member/policy
and matching parent project in SQL. Unscoped rows are not exposed in scoped mode.

Trusted task-local scope is propagated by the existing file-I/O workers. Shelf
bytes use `workspaces/{workspace_id}/projects/{stored_relpath}/original/{name}`;
legacy calls without a scope retain `users/{user_id}/projects`. A project path
cannot select another actor's namespace. This is application path scoping;
NAS migration, sandbox mount confinement and physical hostile-file defenses
remain separate M3/M10/M11 gates.

Browser content navigation may use the canonical UUID query locator
`workspace_id` when it cannot send `X-Deerflow-Workspace`. Both are authenticated
selectors; conflicting values return 404. Missing selection chooses only the
personal workspace. A captured file response binds its original context and
rechecks live versions plus document/parent access before emitting ASGI headers.
Scoped content has `Cache-Control: private, no-store`. This before-send check
does not promise recalling bytes already delivered by an ongoing download.

Upload publication and trash drain their owned async writes on cancellation.
A failed insert followed by a scoped liveness miss does not prove rollback:
revocation may hide a committed row. Its possibly owned bytes remain for later
scope-aware reconciliation instead of being deleted based on that miss.

Thread promotion/attachment are now scoped, as described in the checkpoint below.
Conversion publication, trash recovery/purge and retention inventory also
refuse scoped or required-but-missing calls until integrated. These temporary
refusals are tracked work, not an accepted substitute for the full requirement.
Threads/runs, frontend switching/cache, background scope,
quota accounting and release evidence remain pending; activation stays blocked.

Jenkins #20 observed the actual missing row workspace on SQLite/PostgreSQL.
#21 ran the same actual JWT/RBAC/CSRF production-router main: personal/team
uploads, team-file physical bytes, list/count, header/query downloads, mismatched
selectors/parents, permission change between response preparation and send,
wrong-space trash and post-trash refusal. Two affected legacy roundtrip/dedup
checks passed as well (4 passed in 22.68s). Exact source hashes and archived
log names are in the progress JSON. No NAS or deployed tenant acceptance is implied.


## Explicit shared projects and documents (partial M3)

POST/PATCH `/api/projects` accepts `visibility: private | workspace`; omission
keeps a new project private, and omitted/null PATCH preserves its visibility.
Sharing requires a live team owner/admin plus native project write permission.
Personal spaces and legacy unscoped calls cannot publish shared projects.
Ordinary team members can create their own private projects, but cannot publish
or modify shared projects. SQL repeats the role check under the workspace lock.

Private projects are visible only to their creator. Explicit shared projects are
readable by live members of the selected team, and editable/deletable only by its
owner/admin with matching native permission. Project lists filter this ACL in
SQL; the native platform admin has no content bypass. Resource author identity
is never replaced with a tenant or the current reader.

Project shelf documents inherit their parent project's current ACL. Their
`user_id` is the real uploader, not a separate grant overriding project access.
This permits an admin to upload into another creator's shared project and all
members to read the published bytes. Parent workspace and document workspace
must match. Changing a project back to private restricts its published shelf to
the project creator; it does not grant access to any private thread or memory.
The captured file response rechecks the current parent ACL before sending.

Deleting a shared project trashes all its compatible document rows in the same
transaction, regardless of which authorized admin uploaded them; bytes remain
recoverable. Cross-workspace/null-owner children refuse deletion. Thread child
handling retains the current private-owner restriction until M3 thread integration;
shared project membership alone never permits reading another user's chat.

The project sharing revision is `0037_project_visibility`, appended after unchanged
`0036_tenant_workspaces`. The new non-null default/check constraint keeps
historical projects private. Startup, native backfill and executor export
consumption now require current `0038_workspace_read_clocks`; old phase receipts are not reused.
Executor schema remains `e0002_workspace_scope`. Tenant activation is still
compiled off; the old `0035/e0001` deployment/release lock remains immutable.

Jenkins #22 reproduced rejected sharing requests on both databases. #23 passed
the same actual HTTP/SQL/file main, both real old-data upgrades, startup refusal,
paired attribution, immutable revision ancestry and two affected native mains
(11 passed, 40.55s). Browser shared-data controls, thread/run scope, conversion,
retention, quota accounting and physical migration/release remain required.

## Private thread repository (partial M3)

Native thread SQL now binds the trusted workspace and original owner, checks live membership before reads/pagination and locks workspace/actor before mutations. Shared project membership grants access to project sources, never another member’s conversation. An authorized member may associate their private thread with a shared project; later project unsharing does not remove their private conversation, while project source access still uses the current project ACL. Project deletion detaches compatible private threads without exposing or transferring them. Workspace scope refuses legacy orphan claims, owner reassignment and explicit user bypass. Required mode needs SQL storage and a trusted context.

Jenkins #25 reproduced NULL scope on both databases; #26 passed 7 checks in 29.58s. This is repository evidence, not completed thread HTTP, checkpoint/run, client or deployed tenant acceptance. Those remain M3/M4 requirements and activation stays blocked.

## Native thread metadata HTTP (partial M3)

Creation, search, PATCH, move and GET bind trusted session scope before native
permission/owner checks. Forward annotations are resolved from the original
handler, preserving FastAPI’s public signature through decorator chains. The
adapter resets task-local scope on every exit and revalidates before returning.
Creation strips workspace identity metadata; a globally unique ID collision
outside the selected scope returns 404 without claiming or revealing that row.
Project thread listing intersects current project access with native private
thread ownership; shared project membership never lists another member’s chats.

Jenkins #27 reproduced missing HTTP scope on both databases. #28 passed 7 checks
in 30.21s, retaining three legacy route regressions and the SQL thread main.
The actual HTTP flow covers creation, retry, pagination, pin PATCH, cross-space
move/PATCH denial, shared project association and private project thread lists.
Checkpoint creation uses the native InMemorySaver in this isolated fixture;
persistent checkpoint/state/recovery, files/branches/delete/goal/history/read
clock, Run/background, PAT/internal and frontend acceptance remain required.
GET scope binding is implemented but full state materialization is not established
by this main. The compiled activation gate stays closed.

## Thread uploads and project transfer (partial M3)

Trusted scope selects `workspaces/{workspace_id}/users/{user_id}/threads/{thread_id}`
for local and configured host path construction; absent scope retains legacy paths.
An explicit user must match the actual scope actor. This path binding is not
membership authorization. Upload routes bind scope before native owner checks;
the original pipeline still handles staging, name collisions, conversion and
permissions. Original/derived final links and readability chmod are short drained
operations fenced under native workspace/actor/thread locks.

Shelf attachment checks native project/thread permissions, current parent/document
ACL and private target ownership. Source copying locks workspace/actor/project/document;
after that transaction ends, ingestion rechecks the source before publishing into
the target. Existing legacy `projects:write` and `threads:write` requirements remain.
Transfer neither overwrites nor moves the original. Thread-to-shelf promotion checks
destination write ACL before reading a source; SQL verifies source thread ownership
and matching workspace again before inserting provenance/publishing the shelf copy.

Jenkins #29 reproduced missing upload scope; #30 found the unsupported document-get
argument in source revalidation; #31 passed the actual byte-level main on both
databases and two affected native transfer regressions (6 passed, 30.99s).
The fixture uses the real mounted LocalSandboxProvider and private temporary files;
it is not evidence for physical NAS/AIO mounts or remote sandbox synchronization.
Artifact link/query handling, before-send artifact checks, deletion/revocation
races, controlled mid-transfer cancellation/revocation, full thread lifecycle,
checkpoint/run and browser integration remain required. Activation remains blocked.

## Thread artifact downloads (partial M3)

Upload/output links include the selected workspace UUID as a query locator. It is
not a credential: live native session, workspace membership, private thread owner
and native read permission remain required. Conflicting header/query selectors
return 404. GET binds scope before native owner checks and prepares the existing
file/archive response; a wrapper rebinds captured scope and rechecks live membership
and the SQL thread incarnation before ASGI sends headers. Responses are private,
no-store, and preserve native MIME, download, Range and background-task behavior.

Jenkins #32 reproduced missing link scope; #33 passed the actual SQLite/PostgreSQL
HTTP main plus three native Range/download regressions (5 passed, 27.51s). The
main reads real file/ZIP bytes and changes persisted policy after preparation to
verify no private bytes are sent. This does not prove continuous-stream withdrawal,
credential-reset revocation, recreation faults, artifact writes, physical mounts
or full browser/runtime integration. Upload deletion and full thread lifecycle
remain required; compiled tenant activation stays closed.

## Thread upload deletion (partial M3)

Scoped DELETE rechecks live private-thread access under workspace/actor/thread SQL
locks immediately before its native unlink, and drains the short worker before
releasing those locks. Revocation denials propagate as scope 404 without deleting
the file. An authorized operation serialized before a withdrawal may finish; an
operation reaching the final check afterward is refused. Legacy companion-file
preservation and symlink confinement remain unchanged.

Jenkins #34 reproduced policy withdrawal after genuine owner admission deleting
bytes despite a 404. #35 passed the SQLite/PostgreSQL main with actual persisted
withdrawal, original-byte preservation and later authorized deletion, plus two
native deletion regressions (4 passed, 26.75s). Cancellation during unlink,
physical NAS/AIO, mid-transfer faults and full lifecycle/client acceptance remain
unproven; tenant activation remains blocked.

## Persistent thread checkpoint reads (partial M3)

Thread detail, state, history and goal reads bind live native-session workspace
scope before owner checks. `private_thread_read` additionally requires the
scoped SQL owner-private row and a nonempty incarnation; it rechecks the row and
incarnation after checkpoint materialization. Missing/changed ownership or
lifecycle identity returns 404. Graph assembly and checkpointer IO do not hold
workspace writer locks, and native full/delta accessor behavior remains intact.

Jenkins #36 reproduced missing state scope; #37 verified compiled-graph reads
and foreign-space denial but reproduced stale incarnation returning content;
#38 passed 6 checks in 30.28s, including four affected native read regressions.
The actual authenticated main uses SQLite/PostgreSQL metadata and a durable
AsyncSqliteSaver closed and reopened before reading distinct personal/team
messages and native goals. It explicitly refuses factory-unavailable raw fallback
and changes SQL incarnation during a real checkpoint read to verify denial.

This establishes SQLite checkpoint reopen, not PostgreSQL checkpoint recovery,
cross-process/reboot recovery, delta-mode acceptance or real model execution.
Read clocks, goal/state writes, branches/deletion/compaction, run-history
background backfill, Run/background events, frontend and physical migration
remain required. Compiled tenant activation is still closed.

## Workspace read markers and clocks (partial M3)

POST /threads/{id}/read binds trusted space before native owner checks. The
repository filters unread runs/max change positions by matching private thread
and run workspace. Marking read locks workspace, actor and thread and checks
live membership before updating the original monotonic marker. Only a changed
marker increments workspace_thread_read_versions, keyed by (workspace_id,user_id);
a team read never changes the personal-space clock. The original per-user clock
and marker primary keys remain unchanged for legacy mode. Version reads use a
single live membership SELECT, and HTTP async mutations use await_drained.

Jenkins #39 reproduced missing SQL/HTTP/schema boundaries. #40 passed 12 checks
in 54.07s on real SQLite/PostgreSQL: independent clocks, matching run parents,
repeat-read no-op, withdrawn SQL/HTTP writes retaining markers, actual old-data
upgrades preserving legacy version 23, two native behaviors and paired CLI.
#41 rechecked the only subsequent code change (HTTP async drain) through both
real authenticated HTTP mains: 2 passed, 30.34s. Native head is now 0038; the
executor stays e0002 and past release/phase receipts stay immutable.

This uses seeded Run rows; native Run admission/activity feeds, independent
mid-commit cancellation faults, thread deletion cleanup, lifecycle writes,
frontend and physical rollout remain unaccepted. Scoped marker cleanup currently
refuses until integrated into the thread lifecycle. Activation remains closed.

## Native Run read isolation (partial M3)

RunRepository now captures workspace_required from native bootstrap. Trusted
task-local scope filters individual/idempotency reads, activity cursor/feed,
thread history and keyset pages, timestamp lookups, edit/regeneration sources,
batch reads and token reduction. SQL requires matching Run workspace, original
owner and a compatible owner-private ThreadMeta parent, including live membership
and project-parent consistency, before ordering, limits or reduction. Bound
user_id=None and missing required scope are refused, including empty batch input.
Legacy unbound mode retains owner/global query behavior.

Jenkins #42 reproduced same-user foreign-space disclosure in both databases.
#43 passed 8 checks in 21.74s: actual SQLite/PostgreSQL reads, invalid/null parent
exclusion, pagination, selected cursors, source/batch/token filtering and actual
persisted policy withdrawal, existing read-marker mains and four affected native
compatibility regressions. Archive/source hashes are in tenant-workspaces-progress.json.
This proves repository reads, not HTTP activity/stream admission, scoped Run
creation/reservations, worker cancellation/recovery, frontend switching or deployed
multi-tenancy. Compiled activation remains false; M3 and M4 remain incomplete.

## Scoped native operation reservations (partial M3)

Non-run reject-strategy reservations now persist trusted workspace_id. SQL
admission locks workspace, native actor and matching owner-private ThreadMeta
before the existing global change clock and Run row. It requires a live
membership/policy and nonempty thread incarnation; no checkpoint/model IO runs
inside this transaction. An invisible global idempotency collision returns no
foreign payload. Scoped normal-run/interrupt lifecycle remains refused until M4.

RunManager captures immutable space context before admission for reservation
release. SQL cleanup matches reservation ID, captured original user/workspace
and admitting worker, excludes normal Run rows and does not require live
membership or a surviving thread parent. This narrow release grants no reads,
new work or publication; it remains possible after withdrawal and UI/context
selection changes. Legacy custom stores retain their unscoped call shape, while
the default store refuses captured workspace cleanup it cannot enforce.

Jenkins #44 reproduced NULL workspace on real SQLite/PostgreSQL reservations.
#45 passed 7 checks in 21.58s: real native RunManager/SQL admission and peer
exclusion, wrong-worker cleanup refusal, actual policy withdrawal followed by
ambient space change and successful own cleanup, foreign thread/key denial,
normal-run preservation, prior Run reads and three native compatibility tests.
HTTP goal/state writes, new-thread provisioning, interrupted/cancelled commits,
worker lease recovery and frontend remain separate acceptance requirements.
Tenant activation stays closed; no full M3/M4 completion is claimed.

## Native goal and state writes (partial M3)

PUT/DELETE /threads/{id}/goal and POST /threads/{id}/state now bind trusted
workspace scope before native ownership checks. A new-chat goal preserves the
existing UUID-on-demand behavior: native threads:write permission and live scoped
SQL metadata-only allocation precede the unchanged owner check; durable non-run
admission then precedes any checkpoint creation. Foreign global IDs return 404
without claiming ownership. Scope errors bypass generic ValueError/500 mapping.

State graph/schema preparation happens outside resource SQL locks. The Gateway
captures the private thread incarnation before checkpoint preparation; the final
commit locks workspace -> actor -> thread and compares that incarnation and live
policy before draining only prepared native checkpoint IO. Model/tool/graph setup
is not allowed inside this callback. Native goal/checkpoint authority, state
reducers, assistant bindings and durable reservations remain in use. This fence
serializes authorization/lifecycle changes across checkpoint commit; it does not
make separate metadata/checkpoint databases one atomic transaction.

Jenkins #46 reproduced absent scope; #47 exposed new-chat metadata/owner-check
ordering; #48 reached real graph writes and exposed integer versions manually
seeded by the HTTP fixture versus SQLite saver string versions. The fixture now
uses the actual saver allocator; production version handling is unchanged.
#49 passed both real authenticated HTTP mains in 33.24s with SQLite/PostgreSQL
metadata and durable native SQLite checkpoints: new goal creation, proper SQL
ownership and reservation cleanup, state/title update, personal data preservation,
foreign PUT/POST/DELETE denial, goal clear/read, real SQL incarnation replacement
and goal/state policy withdrawal leaving checkpoint IDs unchanged.

Six affected native regressions passed in #48 (the overall build remained failed
for the HTTP fixture): new-chat goal, goal clear, cross-worker run conflict, real
mutation graph and full/delta extension reducer channels. Archive comparison
shows #48→#49 changed only test_workspace_http.py, so those regressions cover the
unchanged production bytes. One existing Starlette TestClient SDK deprecation
warning was recorded with that native regression run; no dependency workaround
was added. Source hashes and all failures remain in the progress record.

No new live-model, PostgreSQL-checkpointer, cancellation-during-commit, cross-store
crash atomicity, physical migration or browser evidence is implied. Full Run/
activity feeds, branch/delete/compact lifecycle and frontend switching remain
M3/M4 requirements. Tenant activation stays closed.

The follow-up owner-admission fault #50 exposed a narrower lifecycle window:
re-reading incarnation after owner-check accepted a replacement and PUT goal
returned 200. The final binding now preserves the entry private identity across
owner-check; state/clear compare it before preparation, and PUT goal captures it
before its delegated native owner-check. The request-local tuple is installed
only by the trusted binder and restored on exit; it is never sourced from user
input. Final SQL commit still checks that same identity under live locks.

Jenkins #51 passed all 8 checks together in 34.31s, including actual owner-admission
SQL incarnation replacement for PUT goal, POST state and DELETE goal, each
returning 404 with unchanged checkpoint IDs, as well as both complete authenticated
HTTP mains and six native regressions. The existing TestClient SDK warning
remains diagnostic only. All final runtime/test bytes match the #51 archive.

## Checkpoint-only ID admission (partial M3)

Scoped POST /threads and new-chat PUT goal refuse to allocate metadata when a
caller-selected ID already has any checkpoint but no visible private ThreadMeta.
The bounded native alist occupancy probe omits checkpoint_ns to cover root and
subgraph namespaces, closes its iterator before proceeding and never returns
checkpoint content. Existing data yields generic 404; unsupported/storage-failed
validation yields 503 before allocation. Existing matching private metadata still
uses native idempotency. Unbound legacy behavior remains unchanged.

Scoped POST thread initializes its root only after durable native reservation and
the existing live incarnation fence. It preserves the original metadata fields,
but skips an already-initialized root: a same-owner admitted goal can legitimately
commit between metadata allocation and the creating request's initialization.
It must not be overwritten by a new empty root.

Jenkins #52 reproduced actual checkpoint-only IDs being claimed (both metadata
dialects). #53 passed 8 checks in 35.22s: both real HTTP mains reject root-only
legacy IDs through POST thread/PUT goal and subgraph-only IDs through POST thread,
leave metadata absent and original checkpoints/markers unchanged, and preserve
a real native goal committed through RunManager between allocation and root
initialization. Six native creation/goal regressions cover caller IDs, insert
races, owner conflict, storage error and trusted internal ownership. The existing
Starlette TestClient SDK deprecation warning remains diagnostic.

The checkpointer here is durable SQLite with SQLite/PostgreSQL metadata. This
probe is not atomic across stores and does not authorize mixed-version writers;
rollout fencing, orphan inventory/attribution and physical restore remain M10.
Postgres-checkpointer/cancellation/storage-fault acceptance, complete branch/
delete/compact/feed/client and normal Run lifecycle remain required. Activation
stays closed.

## Private native branches (partial M3)

POST /threads/{id}/branches binds trusted private scope before native permission
and owner checks and holds the original durable branch reservation. The source
incarnation is captured before graph/history preparation. Native replay-base
selection, effective schema, reducer replacement, excluded per-thread channels,
branch metadata, history seeding and historical-turn file behavior remain in use.

Scoped branch publication checks the generated destination ID for orphan
checkpoints and stages the native latest-turn file copy under its unpublished
private destination, outside SQL writer locks and drained across cancellation.
It then locks live workspace/actor/private source, compares the captured
incarnation, validates project inheritance and flushes the destination metadata
within that transaction. Only prepared native checkpoint IO runs under the lock;
metadata commits after that IO completes. The child retains the actual actor
and workspace; unavailable/moved projects use the native unassigned fallback.
Unbound legacy publication order remains unchanged.

Jenkins #54 reproduced missing branch scope in both metadata databases. #55
passed 8 checks in 35.34s: real authenticated native graph branching with durable
SQLite checkpoints and SQLite/PostgreSQL metadata, actual private bytes copied
without changing source, own-only child state, shared-project inheritance,
other-space and peer-admin denial, native history seeding and persisted source
incarnation replacement refusing any new metadata. Six native regressions cover
full/delta event history, current/historical file behavior and active/archived
project inheritance. The existing TestClient SDK warning remains diagnostic.

Cross-store atomicity is not claimed: failed/cancelled/uncertain publication can
leave inaccessible checkpoint or private file staging without published metadata.
Do not delete files on an uncertain metadata commit; retention/reconciliation
needs actual fault evidence and belongs with M4/M8/M10/M11. This is not physical
NAS, PostgreSQL-checkpointer, live-model, browser/feed or full lifecycle proof.
Delete/compact/feed/client and remaining M3–M11 acceptance still gate activation.

## Private manual compaction (partial M3)

POST /threads/{id}/compact binds private scope before native owner-check and
retains the original durable checkpoint-write reservation. The Gateway captures
the entry incarnation; the native compactor receives optional validate_scope
and commit_update adapters. It validates after materializing the source and
again after configuration/model preparation, before summary generation. Only
the prepared native messages/summary checkpoint update enters the existing
live workspace/actor/thread/incarnation fence. Model generation does not hold
SQL writer locks. Unbound callers omit the adapters, retaining native behavior.

Jenkins #56 reproduced missing compact scope. #57 passed 8 checks in 36.66s. The
actual authenticated HTTP workflow uses native summarization middleware,
selection/prompt construction, reducer replacement and durable SQLite graph
checkpoints with SQLite/PostgreSQL metadata; only the model response boundary
is deterministic. It summarizes the older pair, retains the latest pair and
persists summary_text. Actual SQL policy withdrawal/incarnation replacement
inside the model-call span returns 404 with unchanged checkpoint IDs; replacement
during snapshot read and foreign/peer requests make no model call.

Six native regressions retain delta mutation, extension channels, no-op/failure
semantics, recorded-agent memory bucket behavior and cross-worker busy denial.
The existing Starlette TestClient SDK deprecation warning remains diagnostic.
Memory and task-continuity archive are disabled in the scoped HTTP main; the
legacy memory regression is not workspace memory authorization. Live DeepSeek,
workspace credentials/memory/archive effects, PostgreSQL checkpointer, fault
recovery and full UI/event-history acceptance remain M4/M5/M9/M11 requirements.
Delete/feed/client and full M3 still gate tenant activation.

## Private conversation deletion (partial M3)

Scoped DELETE /threads/{id} keeps native permissions, goal locking and durable
non-run admission. It captures the original private incarnation, verifies child
attribution, and commits a metadata tombstone before physical cleanup. Ordinary
scoped reads/publication refuse tombstones. Cleanup uses native browser/MCP
session closure, checkpoint deletion, workspace thread paths and event cleanup.
A captured internal receipt then authorizes exact workspace/owner SQL cleanup,
including read markers, before removing metadata; the active delete reservation
survives until native release. Live revocation blocks admission before effects.

Only the local sandbox with compatible persistent stores is admitted by this
partial implementation. A remote admission host, any retained MCP task, or active
scheduled occurrence refuses cleanup. Unknown physical/checkpoint outcomes keep
the tombstone and return 503; a repeat deletion returns 409 rather than replaying
possibly destructive work. Verified STOP and recovery remain required future work.

Uploads, shelf attachments and file unlink capture the private entry incarnation.
Short file publication, chmod, companion registration and failure cleanup compare
it under live SQL locks. Cleanup loses authority after deletion/recreation or
revocation; it must defer instead of unlinking reusable paths. Deferred data needs
captured-provenance reconciliation. Conversion and sandbox network work remain
outside writer transactions; non-mounted sandbox effects still need M5 evidence.

Jenkins #58 was the missing-scope RED. #59 caught a test event-query signature
error. #60 reproduced an actual old multipart request deleting a new-generation
file after HTTP delete/recreate. #61 passed both repaired HTTP mains; its native
cancellation fixture still targeted the pre-refactor entry. #62 passed 10 checks
in 39.38s: SQLite/PostgreSQL authenticated mains and eight affected native
delete/upload regressions, including cancellation drain. The source archive and
hashes are in tenant-workspaces-progress.json; all runtime/test bytes match.
Each build's dedicated containers/networks were independently checked empty.

This verifies local deletion and generation-safe file cleanup mains, not full
M3 or runtime activation. Run cache/background history, remote STOP/recovery,
PostgreSQL checkpoints, NAS, full client flows and M4–M11 remain required.

## Workspace activity feed (partial M3)

GET /thread-activity binds the native browser workspace before permission and
SQL reads, then revalidates before returning. It reuses native Run filtering,
keyset pagination, interactive-change advancement and workspace viewer clocks.
#63 RED reproduced missing scope; #64 GREEN passed 7 checks in 39.36s: real JWT
HTTP on SQLite/PostgreSQL plus five native activity regressions. Personal/team
heads and read versions remain independent; peer and mismatched-parent rows are
filtered before pagination, and mid-request policy withdrawal returns 404.
Source bytes match the recorded archive; both builds' owned resources are empty.
RunManager cache/Run HTTP/SSE, frontend cursor/cache switching and M4–M11 remain
unverified; this does not activate tenant mode.

## Resident Run authorization (partial M3)

RunManager now consults a workspace-capable durable store before returning
resident records in scoped reads. get retains the exact live control object only
when Run identity/owner/thread/operation/timestamp matches an authorized SQL row.
Lists, batches and replay visibility filter resident IDs through scoped SQL;
missing, deleted or revoked rows cannot reappear from cache. Scoped store errors
propagate, rather than falling back to memory; required scope is checked even
for empty batches. Unbound legacy providers retain native cache precedence.

#65 RED reproduced resident cross-space disclosure on both metadata dialects.
#66 found an import-time config.paths/authz/runtime cycle during native test
collection; moving path workspace imports to call time removed that cycle.
#67 passed 9 checks in 43.47s: two real SQL/cache mains, two complete HTTP mains
and five native hydration/precedence/pagination regressions. Cached identity,
latest error-status precedence, actual policy withdrawal, durable deletion and
controlled durable-read failure are covered. Changed source bytes match its
archive, and #65–#67 dedicated resources were independently checked empty.

This does not establish native normal-run admission, worker lease/generation
identity, event/SSE delivery or frontend cache isolation. Those remain required
M3/M4–M11 work; no tenant runtime is activated.

## Event SQL reads (partial M3)

DbRunEventStore reads now combine event owner/workspace with the live private
ThreadMeta parent before limits, paging, identity matching and aggregation.
This covers thread/Run messages, events, counts, last AI positions and message
positions; the inherited AI-to-Run lookup uses the same filtered pages.
Branch history may carry inherited/synthetic Run IDs, so it is authorized by
the event and private parent without requiring an invented execution record.
The optional workspace_required constructor flag guards reads, including empty
position queries. Writes and factory/background wiring are not yet integrated.

#68 RED disclosed another space on both databases; #69 passed 9 checks in
44.47s: two SQL event mains, two existing HTTP mains and five native event
read regressions. Actual SQL withdrawal hides rows/counts/positions, foreign
and NULL stamps are excluded before paging, and branch-style history remains.
Source bytes match its archive; dedicated #68/#69 resources are empty.
HTTP Run/message/event admission, writer scope, SSE, physical recovery and full
client flows still gate M3/M4–M11 and tenant activation.

## Private Run, message and event HTTP reads (partial M3)

Seven thread-scoped read routes now bind private workspace identity before
native permission/owner checks: Run list/page/detail, thread messages/page,
Run messages and Run events. The wrapper revalidates membership and the entry
incarnation before returning. Specific Run subresources additionally require
a scoped durable Run matching the path thread. Message duration enrichment
passes the actual actor to scoped RunManager reads; unbound legacy calls keep
their old signature and internal-owner semantics.

#70 RED found the missing HTTP binding. #71 passed 6 checks in 40.62s: real
JWT/SQL HTTP mains on SQLite/PostgreSQL and four native permission/page/history
regressions. The mains read actual structured SQL event content and feedback
from personal/team conversations, refuse foreign Run IDs, foreign space and
peer access, and reject owner-admission incarnation changes before response.
Source bytes match its archive; both dedicated resource inventories are empty.
SSE, global Run routes, token/artifact/feedback coverage, event writers, full
client flows and M4–M11 remain requirements; this does not activate tenants.

## Private SSE observers (partial M3)

GET thread Run /join and /stream bind private entry identity and wrap the native
StreamingResponse. Before headers and each produced chunk, the wrapper checks
JWT expiry, native hot-reloaded runs:read permission and one read-only SQL
predicate for the original workspace, private thread incarnation, Run and
account token-version/principal attributes. No writer transaction spans network
streaming. The principal snapshot clears its password hash and stores no JWT.

Authority changes committed before the next delivery check stop further chunks.
The connection closes without synthesizing native END or cancelling the Run;
its consumer and bridge generator are drained. Reconnect preserves native
Last-Event-ID behavior and repeats admission. Creator cancellation intent stays
ahead of possibly blocking subscription teardown, and teardown still drains.

#72 RED found missing join scope; #73 passed seven main/native checks. The
subsequent slow-close check #74 reproduced delayed creator cancellation. #75
passed eight checks in 41.02s: SQLite/PostgreSQL JWT/SQL/native MemoryStreamBridge
HTTP mains plus six native disconnect/teardown regressions. Controlled SQL
policy/incarnation/token-version changes and real native RBAC config reload
stop the second frame; a pre-ASGI policy change returns 404 before content;
old-token reconnect returns 401. Observed running records and SQL status remain
running, and the active observer counter returns to zero. All source bytes
match its archive; #72–#75 dedicated resources were independently checked empty.

This is deterministic native-bridge observation acceptance, not a real Agent
execution or atomic packet recall. Redis/cross-process, slow-client/load, timed
expiry and full account reset/OAuth scenarios still need M6/M11 evidence.
Creating streams/POST cancellation, signed producers and full frontend lifecycle
remain M4 and remaining M3–M11 work; tenant activation stays closed.

## Global Run locator reads (partial M3)

GET /api/runs/{run_id}/messages and /feedback bind the native authenticated
workspace before resolving the durable Run. In scoped mode the actual actor is
explicit. After discovery of thread_id, the private resource helper captures its
entry incarnation, rechecks the Run/thread association, materializes only that
actor's messages or feedback, then revalidates live scope and original parent
identity before returning. Native unbound calls preserve their original keyword
signatures, envelope/list shape and cursor trimming.

Jenkins #76 RED found missing scope in both metadata dialects; #77 passed 27
checks in 43.96s: actual SQLite/PostgreSQL JWT/SQL HTTP mains and the affected
native global-Run API regressions. Both personal/team payloads are correct,
foreign space and peer IDs return 404, and a real SQL incarnation change after
message/feedback materialization refuses the response. Current runtime/test bytes
match the successful archive. #76/#77 dedicated containers and networks were
independently empty. Existing Starlette TestClient/httpx deprecation remains.

This covers the two global HTTP reads, not FeedbackRepository mutation fencing
or full thread feedback APIs. Token/workspace-change/artifact/PUT/history,
frontend switching, event writes/Run producers and M4-M11 remain requirements;
tenant activation stays closed.

## Native usage and file-change reads (partial M3)

GET /api/threads/{thread_id}/token-usage and
/api/threads/{thread_id}/runs/{run_id}/workspace-changes now bind the same
private workspace/entry-incarnation wrapper before native owner checks. Existing
SQL aggregation, checkpoint context usage, native Run matching and SQL event
filtering remain authoritative. No new usage engine or file-diff generator.
Both views recheck live scope and captured parent identity after materialization.

#78 RED found missing scope. #79 reached/passed the new two-space usage/change
assertions and eleven native regressions, but its subsequent deletion check had
an outdated fixed personal-event count: the fixture now has one message and one
workspace-change event. Final revision changes only that expectation to exactly
two events (other personal child tables still one; deleted-space children zero).
#80 passed all 13 checks in 45.12s: SQLite/PostgreSQL JWT/SQL HTTP mains and eleven
native token/context/file-change regressions. Personal/team totals are distinct,
include_active keeps the native shape, each diff belongs to its space, summary
and no-diff options work, and foreign space/peer/mismatched Run or changed entry
nonce refuses the response. Real SQL nonce changes after event/context reads
are also rejected. Runtime/test bytes match the final archive; #78-#80 resources
were independently checked empty. Existing TestClient/httpx warning remains.

Feedback repository/HTTP mutation fences, remaining artifact/PUT/history and
frontend flows, event writers/producers/factories and M4-M11 are still required.
This does not enable tenant mode or prove full usage accounting/quota admission.

## Feedback SQL and HTTP (partial M3)

FeedbackRepository derives private scope from its original actor/thread/Run
relations; no second feedback identity or tenant ownership backfill is guessed.
Reads apply compatible native Run, private parent and live space in SQL before
limit, count or grouping. NULL/unattributed, mismatched-parent and peer rows are
not claimed. Required instances check shape/actor even for empty run-ID batches.
Legacy all-owner aggregate defaults and unbound method signatures are retained.

Scoped create/upsert/delete/delete_by_run require the captured entry incarnation
and lock workspace → actor → thread → Run → feedback in their short transaction.
ID-only delete discovers a read-only locator in a separate session, then rechecks
the exact relation after locking. Generic scoped bulk deletion is refused;
canonical thread deletion uses its existing captured SQL receipt. All six native
feedback routes bind scope before owner admission; scoped reads pass the actor
and matching Run, writes pass the original admission nonce into the repository.

#81 RED reproduced cross-space disclosure and missing HTTP binding on both
metadata dialects. #82 passed 38 checks in 57.61s: real SQLite/PostgreSQL SQL and
JWT/HTTP mains, native feedback and global-feedback compatibility. Actual policy
withdrawal before update/delete preserves the row, and parent replacement before
create leaves zero new rows; owner-admission replacement also refuses writes.
Paging excludes invalid rows before limit; stats/grouping omit peers and invalid
Run parents. Archive/source bytes match; #81/#82 exact resources are empty.
The existing TestClient/httpx warning is unchanged.

These results do not prove all multiprocess/crash/cancellation or credential-reset
and role/OAuth boundaries. Remaining files/artifact/PUT/history, frontend, producer
and scope-required factory integration and M4–M11 still gate tenant activation.

## Terminal Run artifact archives (partial M3)

Native archive manifest GET and download POST bind private workspace/entry
identity before owner admission. Matching terminal Run and SQL delivery events
remain authoritative; client-supplied file lists cannot expand delivery. Native
archive generation and reservation/cancellation behavior are retained.
The download response rebinds its captured context and checks live policy plus
original parent before headers. An explicit owned-file close callback is drained
on normal send, ASGI refusal/cancellation, or decorator post-materialization
refusal. Reservation-release/response-construction failure also retains file
ownership for cleanup. Unrelated background actions are not executed on refusal.

#83 RED found absent scope and close support; #84 passed 9 checks in 47.55s.
Actual SQLite/PostgreSQL JWT/SQL/file mains verify distinct personal/team ZIP
bytes, verified delivery selection, manifest count, peer/foreign/Run mismatch and
owner-replacement denial. Actual policy changes after building or before ASGI
return 404 and the held native temporary file is closed. A cancellation unit
also checks file close and context restoration; native selection, busy conflict,
wrong-thread and repeated-builder-cancel regressions remain passing. Current
source bytes match the archive; #83/#84 exact resources independently empty.
Personal retention fixture now preserves exactly three events: message,
workspace change, delivery. Other personal child tables remain exactly one.

Single-artifact entry identity/PUT, frontend, normal producers/factories and
M4-M11 remain pending. This before-header proof is not continuous credential/
role/physical transport or cross-process/crash/load acceptance. No activation.

## Single-artifact entry identity (partial M3)

GET artifact now captures the private entry incarnation before native owner
admission while retaining query workspace locators. The existing identity helper
rechecks that same nonce before any file-response preparation, and the wrapper
still checks before ASGI headers. It cannot adopt a conversation replaced during
owner admission. Native preview, download, Range and ETag logic is unchanged.

#85 RED reproduced a real SQL nonce change in native owner admission returning
200 file bytes in both metadata dialects. #86 passed six checks in 47.62s: both
JWT/SQL HTTP mains plus four native text/Range/ETag regressions. The interrupted
old request returns 404 and the next fresh request still reads the correct
bytes. Archive/source bytes match, and #85/#86 exact resources are empty.

PUT host/remote publication and filesystem races, frontend switching, normal
producers/factories and M4-M11 remain. This entry identity fix is not continuous
credential/role/physical-transport revocation; tenant activation stays closed.

## Mounted artifact editing (partial M3)

PUT artifact binds the original private entry before owner admission. Mounted
host writes retain native artifact_write reservation and validate live SQL
workspace/actor/thread plus original nonce under publish_under_live_lock. Only
bounded file IO is inside this lock; no remote sandbox API call is held there.
The POSIX publisher walks absolute directory components using O_DIRECTORY and
O_NOFOLLOW, pins the parent descriptor, opens a regular single-link file without
following links, bounds and validates UTF-8 bytes, and checks the requested digest
and file identity at final publication. A unique owned temp file is flushed and
atomically replaced relative to that same directory; cleanup only unlinks a temp
that was actually created. Successful publication invalidates the native digest
cache. Unbound native remote sync/rollback/cancellation remains unchanged.

Current scoped admission refuses non-mounted providers or native remote executor
hosts with 503 before acquisition/mutation. These paths still require the M4/M5
scoped worker/provider protocol; this is an unfinished integration gate, not removal
of the remote requirement. Unsupported file-descriptor platforms also fail closed.
No local Docker/pytest, real sandbox execution or production NAS proof is implied.

#87 RED found missing entry scope. #88 passed eight native cases but its HTTP
fixture omitted the actual LocalSandboxProvider binding for artifacts and tried
to load absent production config.yaml. Final revision adds only that fixture
binding, matching uploads. #89 passed ten checks in 51.07s: actual SQLite/PostgreSQL
JWT/SQL/file mains and eight native editor cases. Correct personal/team bytes,
digest/size, stale 412, peer/foreign/entry denial, policy/nonce withdrawal before
final publication and changed-revision preservation are verified. An actual parent
directory replacement with a symlink is refused without changing either original
or outside bytes or leaving outside temporary files. Unsupported remote acquisition
is not called. Source/archive bytes match; #87-#89 exact resources are empty.

This proves controlled pre-publication withdrawal and path replacement, not
uncooperative concurrent writers, distributed filesystem/crash/cancellation or
physical STOP. Rename acknowledgement failures return unconfirmed 503 without
backend retry/rollback; durable unknown-outcome reconciliation/admission fencing
still needs M11 proof. A revocation committed after an already authorized write is
not retroactive rollback. Full credential/role checks, sandbox/NAS isolation,
remote producers/factories, frontend and complete M0-M11 remain; activation closed.

## Frontend Request preservation (partial M3)

The public fetch wrapper now forwards the original Request (or URL input),
keeps Request method/body/headers/AbortSignal and RequestInit override semantics,
and derives CSRF from the actual request method. It never mutates caller headers.
Reducing a Request to only its URL had silently removed an explicit workspace
selector and prevented cancellation; preserving the object fixes that contract.

Shanghai job deerflow-tenant-frontend #2 reproduced both failures. #1 was a
non-root extraction setup failure, not business RED. #3/#4 traced a happy-dom
Request reconstruction limitation: the wrapper's outgoing Headers already had
the correct workspace and CSRF, but the test double discarded the worker Headers
instance. The fixture now normalizes that standard iterable before reconstructing
the outgoing Request, preserving all original header/body/signal assertions.
#5 passed all sixteen checks but needed formatting; #6 SUCCESS passed the same
16 (two new + fourteen native) in 3.74s, modified-file Prettier and full frontend
pnpm check (ESLint + tsc). Full build time 338.094s mainly reflects static checking.
The runtime/test bytes match its successful archive. #1-#6 and probes have empty
owned inventories; a private frozen-lock dependency cache remains for reuse.

This proves explicit Request forwarding and existing static/login compatibility,
not automatic workspace selection or switch cancellation. Tab-local immutable
scope, SDK stream/retry/reconnect binding, query/cache/provider reset, native UI
selector and actual authenticated two-tab browser acceptance remain M3/M7/M11.
No local frontend runtime/test or deployment ran; tenant activation stays closed.


M4 execution transport preparation: optional `ecs_executor.scope` submission
signatures support explicit version 2 carrying the immutable four-field
WorkspaceContext plus the existing user/thread/incarnation/Run and argument
binding. The receiver must supply a separately resolved expected workspace
context; cross-space/actor/version mismatch and legacy downgrade are refused.
Callers without this expectation refuse scoped signatures. Matching claims do
not establish current membership. No request selector or model argument can be
used as the expected authority. This primitive is not yet wired into native
Run/MCP/Scheduler/worker admission; tenant startup remains closed. Management
status/cancel, persisted parent-child binding, live revocation/publication and
unknown-work reservations remain M4 requirements. The bounded Shanghai #1/#2/#3
receipt is recorded under execution_scope_v2; full M4 is not complete.


M4 durable Run identity preparation (0039): native short-operation admission
persists the trusted WorkspaceContext and locked parent incarnation into the
existing Run row, and RunManager hydrates the same identity after a selection
change. Malformed or owner/space-conflicting snapshots are refused. Historical
rows keep absent snapshots; current membership cannot invent their execution
authority. Resident idempotency hits recheck scoped SQL, including live policy
versions; legacy create/put cannot retarget workspace rows. There is no new
public authority endpoint. Ordinary Agent Run admission remains refused pending
RunContext/worker/lease/journal integration. M4 parent and startup stay closed.


M4 ordinary native Run main: the framework's trusted scoped SQL reject admission
now records normal Runs; interrupt/rollback and legacy upsert remain refused.
Pending handoff/adoption/start recheck live membership and original parent
incarnation while applying the existing owner/cancel CAS. Local and durable
idempotency recovery also require the current parent generation. The host
copies the record's identity into RunContext; the worker checks the native
principal, strips caller workspace claims from context/configurable, runs in
its original space, and restores its caller's selection. Deterministic actual
LangGraph execution is verified with both SQL dialects, not a canned authorized
response. The public tenant startup gate remains closed; full HTTP/internal
admission, MCP/Scheduler/remote protocol, leases/recovery and live publication/
revocation integration remain required. Next scope native MCP/B records and
wire version-2 submission signing/verification so scoped work never degrades
to legacy execution authority. No API activation or deployment is implied.


M4 native MCP preparation (0040): scoped TaskSubmitRequest and durable
TaskReference carry original WorkspaceContext. The hidden native runtime owner
key supplies the executing source worker, not user/model arguments. Submission
requires a running uncancelled original Run and current source owner/lease,
member and private parent generation; create rechecks after remote IO without
holding locks across IO. The task's dedicated snapshot is independent of remote
driver_data. User get/list/run projection filter before limits. Background poll
uses the persisted identity after source Run completion and caller selection
changes; results require live scope and the original native claim fence at
commit. Mandatory mode never polls unattributed legacy work.

Scoped cancel/notification are still withheld from legacy queues, and there is
no new public activation. The ECS submit interceptor now emits v2 from original
runtime and refuses identity downgrade; receivers without independent tenant
authorization refuse it. B receiver/management, HTTP/native credential bindings,
physical execution/publication, Scheduler/continuation/notifications/revocation
and unknown Stop remain M4 requirements. Remote IO in metadata tests is a fixture;
it is not evidence of actual B service authorization or cancellation/Stop.

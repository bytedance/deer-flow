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

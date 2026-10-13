# Workspace HTTP control plane (implementation in progress)

The first M2 adapters are verified in an isolated ASGI composition with the
production AuthMiddleware, CSRFMiddleware, JWT implementation, SQL user
repository and RBAC provider. They are now registered by the shipped Gateway;
workspace admission is resolved once at native database bootstrap. The default
service is inactive. No tenant deployment or public registration has been performed.
Full resource isolation is not complete. The project CRUD integration below
is verified separately. Private project document upload/list/content/trash now has
real file evidence; shared data, thread files and background entrypoints still
need integration.

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
archive/restore and delete combine private project ownership, selected workspace
and live account/membership/policy versions in SQL. Filtering happens before
materializing the list, not after returning another space's rows. Missing headers
select only the personal space. Client ownership/workspace fields are rejected.

Writes lock workspace, native actor and then project; SQLite obtains its write
lock first. They recheck current versions before mutation. Scoped deletion refuses
incompatible document/thread children instead of cascading into another space.
Persistent HTTP mutations drain before request cancellation completes. A repository
created with workspace_required=True refuses calls without explicit or trusted
task-local scope; Gateway derives this requirement from its startup snapshot.

Current projects remain native-owner private. Explicit shared project/document
ACLs, upload/download paths and frontend switching are still required M3 work.
The project thread-list endpoint returns 503 in workspace mode until thread-store
filtering is integrated. It retains existing behavior in legacy mode. PAT handling
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
Reads and counts filter workspace, native owner, live account/member/policy and
matching parent project in SQL. Unscoped rows are not exposed in scoped mode.

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

Thread promotion/attachment currently return 503 under a bound workspace.
Conversion publication, trash recovery/purge and retention inventory also
refuse scoped or required-but-missing calls until integrated. These temporary
refusals are tracked work, not an accepted substitute for the full requirement.
Explicit shared ACLs, threads/runs, frontend switching/cache, background scope,
quota accounting and release evidence remain pending; activation stays blocked.

Jenkins #20 observed the actual missing row workspace on SQLite/PostgreSQL.
#21 ran the same actual JWT/RBAC/CSRF production-router main: personal/team
uploads, team-file physical bytes, list/count, header/query downloads, mismatched
selectors/parents, permission change between response preparation and send,
wrong-space trash and post-trash refusal. Two affected legacy roundtrip/dedup
checks passed as well (4 passed in 22.68s). Exact source hashes and archived
log names are in the progress JSON. No NAS or deployed tenant acceptance is implied.

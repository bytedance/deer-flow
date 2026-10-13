# Workspace HTTP control plane (implementation in progress)

The first M2 adapters are verified in an isolated ASGI composition with the
production AuthMiddleware, CSRFMiddleware, JWT implementation, SQL user
repository and RBAC provider. They are not yet registered/initialized by the
shipped Gateway. No tenant deployment or public registration has been performed.
Do not treat this document as a claim that existing resource APIs are scoped.

## Implemented adapter contracts

| Method/path | Authentication and behavior |
| --- | --- |
| GET /api/workspaces | Browser session plus native workspaces:read. SQL returns only active memberships, active spaces and an active verified account. |
| GET /api/workspaces/current | Same permission. X-Deerflow-Workspace selects an opaque canonical UUID, then the server checks live membership. Without the header, only the actor's personal space can be selected. |
| POST /api/workspaces | Browser session plus native workspaces:write; strict name/idempotency_key body. The same native team provisioner creates owner membership and quota transactionally. |
| POST /api/admin/workspaces | Browser session, native workspaces:write and native platform administrator role. Strict owner_user_id, kind, name and idempotency_key body; owner must be active and verified. Uses the same personal/team provisioner and grants the operator no membership or content bypass. |

Missing authentication is 401; missing native permission/role is 403; unknown
or unauthorized selected space/resource is 404; onboarding/idempotency conflicts
are 409; extra client fields are 422. The full Gateway must retain its existing
CSRF/Origin middleware when registering these routers. Middleware-less API
composition is not supported: the management dependency requires the native
session source and matching authenticated AuthContext.

A missing app.state.workspace_service returns 503. Full Gateway initialization,
tenant-mode startup checks and resource/background isolation coverage remain
pending; do not assign this state from an API request or tenant configuration.

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
than using the browser management dependency. Member-management routes,
reauthenticated ownership transfer and revoke effects remain pending.

## Evidence

`backend/tests/test_workspace_http.py` runs one actual JWT/RBAC/CSRF/native-SQL
main on each database. It proves operator-created personal access, no platform
admin bypass, actor-field rejection, same-user personal/team resource isolation,
foreign member rejection, native permission denial despite owner membership,
and stale policy context rejection. Its project proof endpoint exercises the
helper against an actual SQL row; it is not a claim about all production
project/file routes. Exact Jenkins artifacts and source hashes are retained in
[implementation progress](tenant-workspaces-progress.json).

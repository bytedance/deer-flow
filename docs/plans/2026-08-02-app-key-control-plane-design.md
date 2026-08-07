# App Key Control Plane Design

**Status:** Implemented MVP

**Related issues:** [#4551](https://github.com/bytedance/deer-flow/issues/4551), [#4310](https://github.com/bytedance/deer-flow/issues/4310)

## Summary

This design adds a database-backed App Key control plane for external
applications that need to invoke a narrowly scoped DeerFlow agent without
receiving a browser session or platform-administrator credential. A platform
administrator creates an App Profile, grants explicit capabilities, generates
one or more one-time-visible credentials, and may revoke or disable them.

The MVP is deliberately **DB-first and cache-free**. Each App Key request
resolves the credential and Profile from the shared database. A committed
revocation is therefore visible to every Gateway worker on its next request,
without Redis, process-local cache invalidation, or Pub/Sub coordination.

## Context and design lineage

Issue #4310 established the useful core of the proposal: dedicated App Keys,
least-privilege capability allowlists, exact-route exposure, and an identity
that is separate from browser SSO. The review discussion in #4551 correctly
notes that the historical proposal assumed implementation layers that do not
exist on the current OSS baseline. This is consequently a **greenfield
implementation**, not a migration of a pre-existing App-Key stack.

The implementation follows the repository conventions called out in that
review: management routes use `require_admin_user()`; ORM rows live in
`deerflow.persistence` and ship with an Alembic revision; persistence uses the
existing asynchronous session factory; and runtime allowlists are enforced both
before a run starts and during lead-agent assembly.

## Goals and non-goals

### Goals

1. Let a platform administrator create and operate application credentials.
2. Store only a SHA-256 credential digest; return plaintext only when generated.
3. Make disabling a profile or revoking a credential effective on the next
   request at every Gateway worker.
4. Permit only a small, explicit Gateway surface for App Key callers.
5. Enforce default-deny Agent, model, skill, tool-group, and concrete-tool
   capabilities for discovery and execution.
6. Keep an external application's raw user identifier out of DeerFlow's
   internal owner model.

### Non-goals

- This is not a multi-tenant platform or organization-management system.
  Platform administrators own every App Profile in this MVP.
- It is not a browser SSO replacement, a Custom Agent CRUD credential, or a
  general-purpose API token.
- It does not introduce policy bundles, Vault integration, ontology domains, or
  a new RBAC engine.
- It does not claim process or database isolation between applications.
- It deliberately does not add Redis or any other cache.

## Actors and trust boundaries

| Actor | Trust level | Capability |
| --- | --- | --- |
| Platform administrator | Trusted operator | Operates profiles and credentials |
| External application | Credential holder | Calls only the App-Key API allowlist |
| External end user | Untrusted transport input | Receives a derived internal identity only |
| Gateway worker | Enforcement point | Resolves credentials and capabilities |
| Database | Shared authority | Holds policies, hashes, and audit events |

An App Key is sent in `X-DeerFlow-App-Key`. `X-DeerFlow-User-Id` is optional
and never becomes an internal DeerFlow principal. The Gateway derives a stable,
app-scoped opaque owner id from `(app_id, external_user_id)` before the value
reaches owner-scoped persistence.

## Core decisions

### Admin-only management

Every control-plane route uses `require_admin_user()`. The current general
permission list is not a role system and is broad for authenticated users;
adding an `app_keys:manage` item there would grant key management to everyone.
Admin gating matches established security-sensitive management surfaces.

### Database as credential authority

Credentials are generated with `secrets.token_urlsafe(32)` and stored as
`sha256(app_key)`. Database disclosure therefore exposes digests, not reusable
credentials. The generation response contains plaintext once; later reads show
only a prefix and digest for safe identification and revocation.

Direct database lookup costs one small indexed read. It is intentional: a local
cache leaves other workers with stale authorization, and Redis plus
invalidation/PubSub adds availability and correctness failure modes. The MVP
optimizes first for next-request revocation consistency, not lookup throughput.

### Derived external identity

The identity is `app-user-` plus a bounded SHA-256 digest of
`app_id:external_user_id`. Including the app id prevents two applications that
both report `alice` from sharing threads, owner-scoped data, or history. The raw
external id is trusted metadata for attribution only; it is never accepted as a
DeerFlow UUID or an internal-owner header. An absent external id maps
consistently to a per-application identity.

This design uses Profiles as integration policies, not tenants. Tenant tables,
delegated administrators, and organization boundaries are explicitly deferred.

### Exact external API boundary

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/models` | Discover permitted models |
| `GET` | `/api/skills` | Discover permitted skills |
| `GET` | `/api/agents` | Discover permitted agents |
| `POST` | `/api/runs/stream` | Start a permitted streaming run |
| `POST` | `/api/runs/wait` | Start a permitted synchronous run |

Matching uses an exact method/path tuple, never a prefix. A valid App Key cannot
inherit access to similarly named detail, management, artifact, thread, MCP,
user, or configuration endpoints. A supplied invalid key is fail-closed with
`401`; a valid key at a non-allowlisted endpoint is `403` and cannot fall back
to a browser cookie.

The two POST routes bypass double-submit CSRF only if the App Key header is
present on those exact routes. Their real authentication remains the
header-based App Key validation inside `AuthMiddleware`. A cross-site browser
form cannot forge this custom header without a permitted CORS preflight, while a
non-browser integration has no CSRF cookie to send.

### Default-deny capabilities

Capabilities are normalized rows, not a JSON blob:

- `agents`
- `models`
- `skills`
- `tool_groups`
- `tools`

Empty is deny. Discovery endpoints remove ungranted Agents, models, and skills.
`start_run` validates the requested Agent and model before creating a run, so a
denied request cannot silently fall back to the global default model. During
lead-agent assembly, skills and tools are intersected with the Profile again.
The repetition is defense in depth: discovery controls visibility, pre-run
validation controls requests, and assembly controls what binds to the model.

Tool groups select configured groups; a non-empty concrete `tools` allowlist
further narrows those groups. An empty `tools` list does not create a redundant
second grant requirement.

### Audit trail

Profile creation/update, credential generation, and credential revocation append
an `app_key_audits` row with actor, action, profile/key references, JSON detail,
and timestamp. Audit rows never contain plaintext credentials. A query/reporting
API is deferred because the MVP needs durable evidence, not a new audit UI.

## Data model

```text
app_profiles (id, name, description, created_by, disabled, timestamps)
  1 ├── * app_credentials (key_hash, key_prefix, app_id, lifecycle timestamps)
  1 ├── * app_capabilities (app_id, capability, value)
  1 └── * app_key_audits (actor, action, profile/key references, detail, timestamp)
```

`key_hash` identifies a credential and is indexed with `revoked_at` for active
lookups. Capability rows use `(app_id, capability, value)` as their primary key,
preventing duplicate grants. Alembic revision `0011_app_key_control_plane`
creates these tables and guards legacy bootstrap databases where `create_all`
already created them.

## Request flow

```text
external request
  -> exact-route CSRF exemption for header-authenticated run calls only
  -> AuthMiddleware hashes X-DeerFlow-App-Key
  -> AppKeyRepository direct database lookup
  -> revoked, expired, missing, or disabled? deny
  -> derive app-scoped user identity and attach Profile
  -> exact route check
  -> discovery filter or pre-run capability validation
  -> lead-agent assembly intersects capabilities
  -> trusted app attribution in run metadata
```

Normal session and trusted internal authentication are unchanged when no App Key
header is supplied. A supplied but invalid App Key does not fall back to a valid
cookie, preventing credential confusion.

## Control-plane API and UI

| Endpoint | Action |
| --- | --- |
| `GET /api/v1/app-keys/profiles` | List Profiles and credential metadata |
| `POST /api/v1/app-keys/profiles` | Create a Profile and capabilities |
| `GET /api/v1/app-keys/profiles/{app_id}` | Read a Profile |
| `PATCH /api/v1/app-keys/profiles/{app_id}` | Edit or disable/enable a Profile |
| `POST /api/v1/app-keys/profiles/{app_id}/credentials` | Generate a one-time-visible key |
| `DELETE /api/v1/app-keys/credentials/{key_hash}` | Revoke a credential |

The Workspace **App Keys** page provides profile creation, inline scope editing,
key generation, one-time secret display, revocation, and enable/disable. It never
reads or displays plaintext after the initial generation response.

## Failure semantics and operations

| Condition | Result |
| --- | --- |
| Missing App Key | Existing session/internal auth flow applies |
| Invalid, revoked, expired, or disabled App Key | `401 Invalid App Key` |
| Valid key on a non-allowlisted route | `403` |
| Allowed route but denied capability | `403` before run creation |
| Database unavailable during lookup | Authentication fails closed |
| Duplicate Profile | Control plane returns a conflict |

Revocation updates a timestamp rather than deleting the row, preserving audit
history. Profile disable is the broad emergency switch; revocation is the narrow
credential-lifecycle operation. Recovery is by enabling a profile or issuing a
new credential, never by recovering plaintext from a digest.

## Testing and rollout

Focused regression coverage verifies credential hash lookup, revocation, partial
capability updates, the exact five-route allowlist, app-scoped derived identity,
the App-Key CSRF boundary, pre-run Agent/model rejection, and bootstrap schema
parity. Roll out with one least-privilege non-production Profile first. Verify
allowed discovery, denied discovery, permitted run, denied run, and revocation
from separate Gateway workers before considering a cache. Monitor direct lookup
latency; a future cache requires explicit shared invalidation or versioning.

## Deferred work

1. Tenant ownership and delegated App-Key administration.
2. Credential-expiration UI and audit reporting.
3. Per-profile rate limiting and quotas.
4. Integration with the repository's pluggable authorization provider when its
   production contract is stable.
5. Shared caching only with a documented revocation-consistency guarantee.
6. Server-derived opaque thread-key mapping if product requirements prohibit raw
   client correlation keys from becoming thread identifiers.

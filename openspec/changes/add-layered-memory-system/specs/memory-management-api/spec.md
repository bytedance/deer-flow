## ADDED Requirements

### Requirement: Backward-compatible legacy memory routes

The existing memory routes SHALL continue to function unchanged for callers that omit a `layer` parameter:

| Route | Backward-compatible behavior |
|---|---|
| `GET /api/memory` | SHALL behave as `?layer=user` and SHALL return the legacy `MemoryResponse` shape (`{version, lastUpdated, user, history, facts}`) |
| `POST /api/memory/reload` | SHALL reload the user-layer cache and return the legacy shape |
| `DELETE /api/memory` | SHALL clear ALL user-layer records for the current `(tenant_id, user_id)` and return the legacy shape with empty arrays |
| `POST /api/memory/facts` | SHALL be equivalent to `POST /api/memory/user/records` with `kind="fact"` |
| `DELETE /api/memory/facts/{fact_id}` | SHALL be equivalent to `DELETE /api/memory/user/records/{fact_id}` |
| `PATCH /api/memory/facts/{fact_id}` | SHALL be equivalent to `PATCH /api/memory/user/records/{fact_id}` |
| `GET /api/memory/export` / `POST /api/memory/import` | SHALL operate on the user-layer only and SHALL preserve the legacy JSON shape |
| `GET /api/memory/config` / `GET /api/memory/status` | UNCHANGED |

The legacy response model SHALL remain frozen — adding new required fields would break the existing `TestGatewayConformance` contract used by `DeerFlowClient`.

#### Scenario: Existing client receives legacy shape

- **WHEN** an existing client invokes `GET /api/memory` without query parameters
- **THEN** the response SHALL match the existing `MemoryResponse` Pydantic model byte-for-byte (apart from `lastUpdated`)

#### Scenario: Legacy fact creation maps to user records

- **WHEN** `POST /api/memory/facts` receives `{"content":"x","category":"preference","confidence":0.8}`
- **THEN** a User-layer record SHALL be created with `kind="preference"` and the response SHALL include the new record in the legacy `facts[]` array

### Requirement: Layered REST API for three-layer access

The gateway SHALL expose a uniform layered API at `/api/memory/{layer}/records` where `{layer}` ∈ `{session, user, domain}`:

- `GET /api/memory/{layer}/records?{scope_params}&{filters}` — list records in scope
- `POST /api/memory/{layer}/records` — create a record (body validates against `MemoryRecord` minus `id`/`created_at`)
- `GET /api/memory/{layer}/records/{record_id}` — fetch one record
- `PATCH /api/memory/{layer}/records/{record_id}` — partial update of `content`/`confidence`/`tags`/`valid_from`/`valid_to`/`decay_policy`
- `DELETE /api/memory/{layer}/records/{record_id}` — delete one record
- `POST /api/memory/{layer}/forget` — bulk delete by filter (admin-gated, see permissions below)

Required scope query parameters per layer:

- `session`: `thread_id` REQUIRED; `agent_name` OPTIONAL
- `user`: `agent_name` OPTIONAL (defaults to current agent or `default`)
- `domain`: `domain` REQUIRED; `entity_id` OPTIONAL

`tenant_id` and `user_id` SHALL always be resolved from the authenticated request context — never accepted from query/body.

#### Scenario: Domain list requires domain param

- **WHEN** a client issues `GET /api/memory/domain/records` without a `domain` query parameter
- **THEN** the response SHALL be HTTP 422 with a clear validation error

#### Scenario: Session list scoped to thread

- **WHEN** a client issues `GET /api/memory/session/records?thread_id=thr_abc`
- **THEN** the response SHALL contain only records whose `scope.thread_id="thr_abc"` and current `(tenant_id, user_id)`

#### Scenario: Tenant_id from body is ignored

- **WHEN** a client sends `POST /api/memory/user/records` with body containing `"scope":{"tenant_id":"other"}`
- **THEN** the persisted record's `scope.tenant_id` SHALL be the authenticated request's tenant, not `"other"`

### Requirement: Permission model

Layered access SHALL be authorized as follows:

- **Session layer**: a user MAY read/write/delete only records in their own `(tenant_id, user_id, thread_id)`.
- **User layer**: a user MAY read/write/delete only records in their own `(tenant_id, user_id)`. `tenant_admin` MAY read user-layer records of users in their tenant for audit purposes only (no write).
- **Domain layer**: any authenticated user in `tenant_id` MAY read records of that tenant. ONLY `tenant_admin` (or `superadmin`) MAY create/update/delete domain records via REST. The `record_domain_memory` tool, called from within an agent run, MAY also write Domain records on behalf of the SOUL (see tool spec).
- **Bulk forget** (`POST /api/memory/{layer}/forget`): requires `tenant_admin` for `domain` layer; user-self for `user`/`session` layers.

#### Scenario: Non-admin cannot delete domain record

- **WHEN** a regular user issues `DELETE /api/memory/domain/records/{id}`
- **THEN** the response SHALL be HTTP 403 with body indicating insufficient role

#### Scenario: User cannot read another user's records

- **WHEN** user A issues `GET /api/memory/user/records?user_id=B` (or otherwise tries to widen scope)
- **THEN** the resolved scope SHALL be A's own (the `user_id` query parameter SHALL be ignored), and the response SHALL contain only A's records

#### Scenario: Tenant admin can read user-layer for audit

- **WHEN** a tenant_admin issues `GET /api/memory/user/records?as_user_id=B`
- **THEN** the response SHALL contain B's records — write/delete on the same path SHALL still be 403

### Requirement: Error envelope

All layered routes SHALL return errors as `{"detail": "<message>", "code": "<stable_code>"}` where `<stable_code>` is one of `MEMORY_NOT_FOUND` (404), `MEMORY_FORBIDDEN` (403), `MEMORY_VALIDATION` (422), `MEMORY_STORAGE` (500), `MEMORY_EMBEDDING_UNAVAILABLE` (503). The `code` field SHALL remain stable across releases so the frontend can switch on it for localised messages.

#### Scenario: Missing record returns 404 with stable code

- **WHEN** `GET /api/memory/user/records/missing_id` is requested
- **THEN** the response status SHALL be 404 and body SHALL include `"code":"MEMORY_NOT_FOUND"`

#### Scenario: Embedding outage surfaces 503 not 500

- **WHEN** ChromaDB is unreachable and a Domain `read` is requested
- **THEN** the response status SHALL be 503 and body SHALL include `"code":"MEMORY_EMBEDDING_UNAVAILABLE"`

## ADDED Requirements

### Requirement: IntegrationSystem configuration model

The system SHALL define an `IntegrationSystemConfig` Pydantic model in `deerflow/integrations/config.py` representing a tenant's external system connection. Each entry SHALL contain:

- `system_key: str` — unique identifier (e.g. `"ins_prod"`, `"sms_prod"`)
- `system_type: str` — adapter type discriminator (`"ins"` | `"sms"` | `"crm"` | `"erp"` | `"custom"`)
- `display_name: str` — human-readable name (e.g. `"InS Production"`)
- `description: str` — system description (default: `""`)
- `connector_ref: str | None` — reference to an existing tenant connector for transport (default: `None`)
- `transport_type: str` — transport protocol (`"http"` | `"rpc"` | `"db"` | `"file"` | `"sdk"`, default: `"http"`)
- `base_url: str` — system base URL
- `base_path: str` — API base path within the system (default: `""`)
- `auth_type: str` — authentication method (`"bearer"` | `"api_key"` | `"ins_base"`)
- `secret_ref: str | None` — secret reference (`"$ENV_VAR"` or `"tenant://secrets/xxx"`)
- `timeout_seconds: float` — request timeout (default: `15.0`)
- `max_retries: int` — retry count on transient failures (default: `2`)
- `retry_policy: RetryPolicy` — retry configuration (default: `RetryPolicy()`)
- `priority: int` — system priority for ordering (default: `100`)
- `enabled: bool` — whether the system is active (default: `true`)
- `capabilities: list[str]` — capability keys this system can provide (default: `[]`)
- `extra_config: dict[str, Any]` — adapter-specific configuration (default: `{}`)

Where `RetryPolicy` is:

```python
class RetryPolicy(BaseModel):
    max_retries: int = 2
    retry_on_status: list[int] = [502, 503, 504]
```

#### Scenario: Parse Ins system configuration

- **WHEN** `config.yaml` contains:

  ```yaml
  integrations:
    systems:
      ins_prod:
        system_type: ins
        display_name: "InS Production"
        connector_ref: ins_http_main
        transport_type: http
        base_url: http://ins.example.com
        base_path: /openapi
        auth_type: bearer
        secret_ref: "$INS_TOKEN"
        timeout_seconds: 30
        max_retries: 2
        capabilities:
          - asset.catalog
          - asset.context
          - monitoring.trend
          - monitoring.waveform
          - monitoring.orbit
          - monitoring.alarm_history
  ```

- **THEN** `IntegrationSystemConfig` parses it with all fields
- **THEN** `system_key="ins_prod"`, `system_type="ins"`, `connector_ref="ins_http_main"`

#### Scenario: Parse Sms system configuration

- **WHEN** `config.yaml` contains Sms entry with `auth_type: api_key`
- **THEN** parsed with `system_key="sms_prod"`, `system_type="sms"`
- **THEN** `extra_config` may include `{"auth_header": "X-API-Key"}`

#### Scenario: Secret reference resolution

- **WHEN** `secret_ref` is `"$INS_TOKEN"`
- **THEN** at runtime, `resolve_secret()` reads `os.environ["INS_TOKEN"]`
- **THEN** if env var is not set, raises `IntegrationConfigError("Secret not found: INS_TOKEN")`

#### Scenario: Connector reference

- **WHEN** `connector_ref` is `"ins_http_main"`
- **THEN** the system uses the existing tenant connector record for HTTP transport configuration
- **THEN** `connector_ref` is resolved via the existing `tenant_connectors` lookup at adapter initialization time

#### Scenario: Disabled system

- **WHEN** `enabled: false`
- **THEN** system is parsed but `IntegrationRegistry` does not instantiate an adapter for it

### Requirement: CapabilityRoute configuration model

The system SHALL define a `CapabilityRouteConfig` Pydantic model representing how a business capability maps to external systems:

- `capability_key: str` — capability identifier (e.g. `"monitoring.trend"`, `"health.assessment"`)
- `primary_system_key: str` — the authoritative system for this capability
- `enrich_system_keys: list[str]` — supplementary systems (default: `[]`)
- `fallback_system_keys: list[str]` — fallback systems tried in order on primary failure (default: `[]`)
- `enabled: bool` — whether this route is active (default: `true`)
- `timeout_seconds: float` — route-level timeout override (default: `20.0`)
- `merge_policy: str` — multi-system aggregation strategy (default: `"primary_plus_enrich"`)
- `partial_failure_policy: str` — how to handle enrich failures (default: `"return_partial"`)

Routes can be declared in two forms:

**Simple form** — single system:

```yaml
routes:
  monitoring.trend: ins_prod
```

**Full form** — primary + enrich + fallback:

```yaml
routes:
  asset.overview:
    primary: ins_prod
    enrich: [sms_prod, erp_prod]
    fallback: []
    merge_policy: primary_plus_enrich
    partial_failure_policy: return_partial
```

The parser SHALL accept both forms, normalizing simple form to `CapabilityRouteConfig(capability_key=key, primary_system_key=value)`.

Supported `merge_policy` values:

- `"primary_plus_enrich"` — merge enrich data into primary result
- `"primary_only"` — ignore enrich data
- `"concatenate"` — concatenate results from all systems

Supported `partial_failure_policy` values:

- `"return_partial"` — return primary data + successful enrich, record failures in `partial_failures`
- `"fail_all"` — if any enrich fails, raise `IntegrationError`
- `"ignore_failures"` — silently drop failed enrich data

#### Scenario: Parse simple route

- **WHEN** `routes: {"monitoring.trend": "ins_prod"}`
- **THEN** parsed as `CapabilityRouteConfig(capability_key="monitoring.trend", primary_system_key="ins_prod")`

#### Scenario: Parse full route

- **WHEN** `routes: {"asset.overview": {"primary": "ins_prod", "enrich": ["sms_prod", "erp_prod"], "merge_policy": "primary_plus_enrich"}}`
- **THEN** parsed with `primary_system_key="ins_prod"`, `enrich_system_keys=["sms_prod", "erp_prod"]`, `merge_policy="primary_plus_enrich"`

#### Scenario: Route references non-existent system

- **WHEN** a route referenced a `system_key` not in `systems`
- **THEN** validation fails with `"Route references unknown system: {key}"`

#### Scenario: Route validation — enrich and fallback do not overlap

- **WHEN** `enrich_system_keys` and `fallback_system_keys` contain the same system_key
- **THEN** validation fails with `"enrich and fallback cannot overlap: {key}"`

### Requirement: EntityLink configuration model

The system SHALL define an `EntityLinkConfig` Pydantic model representing cross-system entity ID mappings:

- `tenant_id: str` — the tenant this mapping belongs to
- `entity_type: str` — entity category (`"asset"`, `"measurement_point"`, `"customer"`, `"work_order"`, `"inventory_item"`)
- `canonical_id: str` — platform-level unified ID
- `display_name: str | None` — human-readable name (default: `None`)
- `links: list[EntityLinkEntry]` — per-system mappings
- `confidence: float` — overall mapping reliability (0.0 to 1.0, default: `1.0`)
- `status: str` — mapping status (`"active"`, `"inactive"`, default: `"active"`)
- `metadata: dict[str, Any]` — additional context (default: `{}`)

Where `EntityLinkEntry` is:

```python
class EntityLinkEntry(BaseModel):
    system_key: str
    remote_id: str
    remote_code: str | None = None    # human-readable code in that system
    is_primary: bool = False          # whether this system owns the canonical_id
    confidence: float = 1.0
```

#### Scenario: Parse entity link

- **WHEN** `entity_links` contains:

  ```yaml
  - entity_type: asset
    canonical_id: "asset:tenant-a:pump-001"
    display_name: "1# 给水泵"
    links:
      - system_key: ins_prod
        remote_id: "INS-10001"
        remote_code: "PUMP-001"
        is_primary: true
        confidence: 1.0
      - system_key: sms_prod
        remote_id: "SMS-90088"
        remote_code: "DEVICE-001"
        is_primary: false
        confidence: 0.92
  ```

- **THEN** parsed correctly with all fields

#### Scenario: Confidence validation

- **WHEN** `confidence` is `1.5` (out of range)
- **THEN** validation fails with `"confidence must be between 0.0 and 1.0"`

#### Scenario: EntityLinkResolver lookup

- **WHEN** `EntityLinkResolver.resolve("asset", "asset:tenant-a:pump-001", "sms_prod")` is called
- **THEN** returns `EntityLinkEntry` with `remote_id` for that system
- **THEN** if no mapping exists, raises `EntityLinkNotFound`

#### Scenario: EntityLinkResolver by remote_id

- **WHEN** `EntityLinkResolver.resolve_by_remote("asset", "ins_prod", "INS-10001")` is called
- **THEN** returns the `EntityLinkConfig` containing that remote mapping

### Requirement: Integrations top-level config section

The system SHALL support a top-level `integrations` section in `config.yaml`. The section SHALL be optional — when absent, the integration layer is inert.

The `integrations` section SHALL contain:

- `enabled: bool` (default: `true`) — global kill switch
- `systems: dict[str, IntegrationSystemConfig]` — system connections
- `routes: dict[str, CapabilityRouteConfig]` — capability routing
- `entity_links: list[EntityLinkConfig]` — cross-system ID mappings

`AppConfig` SHALL include an `integrations: IntegrationsConfig | None` field (default: `None`).

#### Scenario: Config with integrations

- **WHEN** `config.yaml` contains a valid `integrations` section
- **THEN** `AppConfig.from_file()` parses them into `config.integrations`
- **THEN** `config.integrations.systems["ins_prod"]` is a valid `IntegrationSystemConfig`

#### Scenario: Config without integrations

- **WHEN** `config.yaml` does not contain an `integrations` section
- **THEN** `config.integrations` defaults to `None`
- **THEN** no error is raised, integration layer is inert

#### Scenario: Global kill switch

- **WHEN** `integrations.enabled: false`
- **THEN** `IntegrationRegistry` does not initialize any adapter
- **THEN** all integration tools return "integrations disabled" message

### Requirement: Integration management API

The system SHALL provide REST endpoints in `app/gateway/routers/`:

**Integration Systems** (`tenant_integration_systems.py`):

- `POST /api/tenants/{tenant_id}/integration-systems` — create system (admin only)
- `GET /api/tenants/{tenant_id}/integration-systems` — list systems with health status. Supports query params: `system_type`, `enabled`, `capability`
- `GET /api/tenants/{tenant_id}/integration-systems/{system_key}` — get single system
- `PUT /api/tenants/{tenant_id}/integration-systems/{system_key}` — update system (admin only)
- `DELETE /api/tenants/{tenant_id}/integration-systems/{system_key}` — delete system (admin only). Returns 409 if referenced by any CapabilityRoute
- `PUT /api/tenants/{tenant_id}/integration-systems/{system_key}/enabled` — enable/disable system (admin only)
- `POST /api/tenants/{tenant_id}/integration-systems/{system_key}/connectivity-check` — test connectivity, returns `HealthStatus`

**Capability Routes** (`tenant_capability_routes.py`):

- `GET /api/tenants/{tenant_id}/capability-routes` — list all routes
- `PUT /api/tenants/{tenant_id}/capability-routes/{capability_key}` — create/update single route (admin only)
- `PUT /api/tenants/{tenant_id}/capability-routes` — batch create/update routes (admin only)

**Entity Links** (`tenant_entity_links.py`):

- `GET /api/tenants/{tenant_id}/entity-links` — list entity links. Supports query params: `entity_type`, `canonical_id`, `system_key`, `remote_id`, `status`
- `POST /api/tenants/{tenant_id}/entity-links` — create entity link (admin only)
- `GET /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}` — get single entity link
- `PUT /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}` — update entity link (admin only)
- `DELETE /api/tenants/{tenant_id}/entity-links/{entity_type}/{canonical_id}` — delete entity link (admin only)

Phase 1 SHALL read from `config.yaml` only. Phase 2 SHALL support per-tenant dynamic configuration via these APIs.

All endpoints SHALL use the platform standard response envelope:

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": { "tenant_id": "..." }
}
```

#### Scenario: List integration systems

- **WHEN** admin calls `GET /api/tenants/default/integration-systems`
- **THEN** response includes all configured systems with `system_key`, `system_type`, `display_name`, `enabled`, `healthy`

#### Scenario: Filter systems by type

- **WHEN** admin calls `GET /api/tenants/default/integration-systems?system_type=ins`
- **THEN** response includes only systems with `system_type: "ins"`

#### Scenario: Connectivity check

- **WHEN** admin calls `POST /api/tenants/default/integration-systems/ins_prod/connectivity-check`
- **THEN** triggers immediate connectivity test and returns `HealthStatus` with `latency_ms`

#### Scenario: Delete system referenced by route

- **WHEN** admin calls `DELETE /api/tenants/default/integration-systems/ins_prod`
- **THEN** and `ins_prod` is referenced by a `CapabilityRoute`
- **THEN** returns HTTP 409 with error code `"SYSTEM_IN_USE"`

#### Scenario: Batch route update

- **WHEN** admin calls `PUT /api/tenants/default/capability-routes` with a list of routes
- **THEN** all routes are created or updated atomically

#### Scenario: Route validation

- **WHEN** admin creates a route with `primary_system_key: "nonexistent"`
- **THEN** returns HTTP 422 with error code `"CAPABILITY_ROUTE_INVALID_SYSTEM"`

#### Scenario: Entity link constraint

- **WHEN** admin creates an entity link where `system_key + remote_id` already maps to a different active canonical entity
- **THEN** returns HTTP 409 with error code `"ENTITY_LINK_CONFLICT"`

### Requirement: Relationship with existing tenant connectors

The `IntegrationSystemConfig.connector_ref` SHALL reference an existing record in the `tenant_connectors` table. The existing `/api/tenants/{tenant_id}/connectors` API SHALL remain unchanged and serve as the low-level HTTP transport configuration layer.

The relationship is:

- `connector` — low-level transport (URL, method, auth header, timeout)
- `integration system` — external system instance (references connector, declares capabilities)
- `capability route` — capability-to-system routing
- `entity link` — cross-system object alignment

#### Scenario: System references existing connector

- **WHEN** an integration system has `connector_ref: "ins_http_main"`
- **THEN** the adapter reads HTTP transport config (base URL, auth headers) from the connector record
- **THEN** the connector must exist at adapter initialization time

#### Scenario: Connector does not exist

- **WHEN** `connector_ref` points to a non-existent connector
- **THEN** adapter initialization logs a warning and falls back to `base_url` from the system config

### Requirement: Tenant-scoped access control

All integration management endpoints SHALL enforce tenant-scoped authorization. A `tenant_admin` user SHALL only be able to manage integration systems, capability routes, and entity links belonging to their own tenant.

The authorization check SHALL verify that the authenticated user's `tenant_id` matches the `{tenant_id}` path parameter. A `platform_admin` user MAY operate on any tenant.

#### Scenario: tenant_admin manages own tenant

- **WHEN** a `tenant_admin` user with `tenant_id="factory-A"` calls `PUT /api/tenants/factory-A/integration-systems/sms_prod`
- **THEN** the request is authorized and processed

#### Scenario: tenant_admin blocked from other tenant

- **WHEN** a `tenant_admin` user with `tenant_id="factory-A"` calls `PUT /api/tenants/factory-B/integration-systems/sms_prod`
- **THEN** returns HTTP 403 with error code `"TENANT_MISMATCH"`
- **THEN** the request is logged as an unauthorized access attempt

#### Scenario: platform_admin manages any tenant

- **WHEN** a `platform_admin` user calls `PUT /api/tenants/factory-B/integration-systems/sms_prod`
- **THEN** the request is authorized regardless of the user's own tenant affiliation

### Requirement: Configuration change audit logging

All write operations on integration management endpoints (create, update, delete, enable/disable) SHALL produce a structured audit log entry. The audit log SHALL be written at `INFO` level and SHALL include:

- `tenant_id` — which tenant was affected
- `operation` — the HTTP method and path (e.g. `"PUT /integration-systems/sms_prod"`)
- `actor` — the authenticated user's `user_id` and `role`
- `changes` — a diff summary of what was modified (field names, old/new values)
- `timestamp` — ISO 8601 timestamp

Read operations (GET, list, filter) SHALL NOT produce audit logs. Connectivity checks SHALL produce a `DEBUG`-level log but NOT an audit entry.

#### Scenario: Audit log on system creation

- **WHEN** admin creates a new integration system via `POST /api/tenants/default/integration-systems`
- **THEN** an audit log entry is written: `{"tenant_id": "default", "operation": "POST /integration-systems", "actor": {"user_id": "42", "role": "tenant_admin"}, "changes": {"system_key": "sms_prod", "system_type": "sms", "enabled": true}, "timestamp": "2026-05-27T10:00:00Z"}`

#### Scenario: Audit log on route update

- **WHEN** admin updates a capability route via `PUT /api/tenants/default/capability-routes/monitoring.trend`
- **THEN** an audit log entry includes the old and new `primary_system_key` values

#### Scenario: Audit log on system disable

- **WHEN** admin disables a system via `PUT /api/tenants/default/integration-systems/ins_prod/enabled` with `{"enabled": false}`
- **THEN** an audit log entry is written with `"changes": {"enabled": {"old": true, "new": false}}`

#### Scenario: No audit log on read operations

- **WHEN** admin calls `GET /api/tenants/default/integration-systems`
- **THEN** no audit log entry is produced

### Requirement: Integration API rate limiting

All integration management write endpoints SHALL enforce per-tenant rate limiting to prevent configuration thrashing and accidental bulk changes.

The rate limit SHALL be:

- Write operations (POST/PUT/DELETE): 10 requests per minute per tenant
- Connectivity checks: 5 requests per minute per tenant per system
- Read operations (GET): no rate limit (standard API gateway limits apply)

When the rate limit is exceeded, the endpoint SHALL return HTTP 429 with `Retry-After` header indicating seconds until the next allowed request.

#### Scenario: Rate limit on write operations

- **WHEN** a tenant admin makes 11 `PUT` requests to `/api/tenants/default/capability-routes/*` within 60 seconds
- **THEN** the 11th request returns HTTP 429 with `Retry-After: 30`
- **THEN** the response body includes `"error_code": "RATE_LIMITED", "message": "Too many configuration changes, please wait"`

#### Scenario: Rate limit on connectivity checks

- **WHEN** a tenant admin triggers 6 connectivity checks for `ins_prod` within 60 seconds
- **THEN** the 6th request returns HTTP 429

#### Scenario: Rate limit does not affect reads

- **WHEN** a tenant admin makes 50 `GET` requests within 60 seconds
- **THEN** all requests succeed (no rate limit applied)

### Requirement: Integration capability degradation strategy

When an integration system becomes unhealthy (health check fails consecutively), the system SHALL automatically degrade the affected capabilities rather than failing every request.

The degradation strategy SHALL be:

1. After 3 consecutive health check failures, mark the system as `degraded`
2. For `degraded` systems, the `CapabilityRouter` SHALL:
   - Skip the degraded system in fallback chains (do not waste time on known-bad systems)
   - Still attempt the degraded system if it is the `primary` (with a shorter timeout of 5 seconds)
   - Include `"system_degraded"` in `ServiceResult.partial_failures` when the degraded system fails
3. On health check recovery, reset the degradation state and restore normal routing

The degradation state SHALL be visible in the `GET /api/tenants/{tenant_id}/integration-systems` response via a `degraded: true` field.

#### Scenario: System auto-degrades after failures

- **WHEN** `sms_prod` health check fails 3 consecutive times
- **THEN** the registry marks `sms_prod` as `degraded`
- **THEN** subsequent `CapabilityRouter` calls skip `sms_prod` in fallback chains
- **THEN** `GET /api/tenants/default/integration-systems` shows `"degraded": true` for `sms_prod`

#### Scenario: Primary system still attempted when degraded

- **WHEN** `ins_prod` is the primary for `monitoring.trend` and is marked `degraded`
- **THEN** `CapabilityRouter` still attempts `ins_prod` with a 5-second timeout
- **THEN** if `ins_prod` responds, the result is returned normally
- **THEN** if `ins_prod` times out, fallback systems are tried

#### Scenario: Degradation recovers on health check success

- **WHEN** `sms_prod` was degraded but its next health check succeeds
- **THEN** the `degraded` flag is reset to `false`
- **THEN** normal routing resumes immediately
- **THEN** an `INFO` log is written: `"sms_prod recovered from degraded state"`

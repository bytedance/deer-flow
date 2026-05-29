## ADDED Requirements

### Requirement: IntegrationAdapter Protocol

The system SHALL define an `IntegrationAdapter` protocol in `deerflow/integrations/adapters/base.py` that all adapter implementations MUST satisfy:

```python
class IntegrationAdapter(Protocol):
    @property
    def system_key(self) -> str: ...

    @property
    def system_type(self) -> str: ...

    async def call(self, capability_key: str, params: dict[str, Any],
                   auth_context: AuthContext | None) -> Any: ...

    async def health_check(self) -> HealthStatus: ...

    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...
```

Where:

- `AuthContext` is a frozen dataclass: `user_id: str`, `org_id: int | None`, `token: str | None`, `tenant_id: str`
- `HealthStatus` is a frozen dataclass: `healthy: bool`, `latency_ms: float | None`, `message: str`, `checked_at: str`
- `call()` returns a canonical model instance (type depends on `capability_key`)

All dataclasses SHALL use `@dataclass(frozen=True)` to enforce immutability.

#### Scenario: Adapter implements protocol

- **WHEN** a class implements all properties and methods of `IntegrationAdapter`
- **THEN** `isinstance(adapter, IntegrationAdapter)` returns `True` via structural subtyping

#### Scenario: Adapter call returns canonical model

- **WHEN** `adapter.call("monitoring.trend", params, ctx)` is invoked
- **THEN** the return value is a `TrendSeries` instance (not a raw dict)

### Requirement: IntegrationRegistry

The system SHALL provide `IntegrationRegistry` in `deerflow/integrations/registry.py` as a singleton accessed via `get_integration_registry()`. The registry SHALL manage the lifecycle of all adapters:

- `register(adapter: IntegrationAdapter) -> None` — register an adapter
- `get(system_key: str) -> IntegrationAdapter | None` — retrieve by system key
- `get_for_type(system_type: str) -> list[IntegrationAdapter]` — find adapters by system type
- `list_all() -> list[IntegrationAdapter]` — list all registered adapters
- `async initialize_all() -> None` — call `initialize()` on all adapters (parallel, with error isolation)
- `async shutdown_all() -> None` — call `shutdown()` in reverse registration order
- `async health_check_all() -> dict[str, HealthStatus]` — run health checks on all adapters (parallel)

The registry SHALL be populated during Gateway lifespan startup. It SHALL use the `IntegrationsConfig` to determine which adapters to instantiate, based on the `system_type` of each enabled system.

#### Scenario: Registry instantiates adapters from config

- **WHEN** Gateway starts and config has `ins_prod` (enabled, `system_type: ins`) and `sms_prod` (enabled, `system_type: sms`)
- **THEN** registry creates `InsAdapter` and `SmsAdapter`
- **THEN** `get("ins_prod")` and `get("sms_prod")` return the respective adapters

#### Scenario: Disabled system not instantiated

- **WHEN** config has `test_system` with `enabled: false`
- **THEN** registry does NOT create an adapter for it
- **THEN** `get("test_system")` returns `None`

#### Scenario: Initialization error isolation

- **WHEN** `sms_adapter.initialize()` raises an exception
- **THEN** registry logs the error with system_key and exception details
- **THEN** `ins_adapter` is still initialized successfully
- **THEN** `health_check_all()` shows sms as `healthy=False`

#### Scenario: Adapter factory registration

- **WHEN** the system starts
- **THEN** adapter factories are registered: `{"ins": InsAdapter, "sms": SmsAdapter}`
- **THEN** future CRM/ERP adapters register their factories in the same way

### Requirement: Health check scheduling

The system SHALL perform periodic health checks on all registered adapters. Health checks SHALL run as a background asyncio task started during Gateway lifespan, after `initialize_all()`.

Each adapter's check interval SHALL default to 60 seconds, configurable via `extra_config.health_check_interval_seconds`. Failed checks SHALL use exponential backoff (double interval on consecutive failure, capped at 300 seconds). Recovery from failure SHALL reset the interval to the configured value.

#### Scenario: Periodic check at configured interval

- **WHEN** Ins adapter has `extra_config: {"health_check_interval_seconds": 60}`
- **THEN** `adapter.health_check()` is called approximately every 60 seconds

#### Scenario: Exponential backoff

- **WHEN** Sms adapter's health check fails 3 times consecutively (interval: 60s)
- **THEN** the 4th check is scheduled at `min(60 * 2, 300) = 120` seconds

#### Scenario: Recovery resets interval

- **WHEN** Sms adapter recovers after backoff
- **THEN** the next check is at the original `60` second interval

#### Scenario: Shutdown cancels scheduler

- **WHEN** Gateway shuts down
- **THEN** the health check background task is cancelled before `shutdown_all()` is called

### Requirement: CapabilityRouter

The system SHALL provide `CapabilityRouter` in `deerflow/integrations/routing.py`. The router SHALL:

1. Accept a capability request (`capability_key` + `params` + `tenant_id` + `auth_context`)
2. Look up the `CapabilityRouteConfig` for the given capability
3. Call the primary adapter via `adapter.call(capability_key, params, auth_context)`
4. On primary failure, try fallback adapters in order
5. On success, if `enrich_system_keys` exist, fan out enrich calls in parallel
6. Merge enrich data into the primary result
7. Return a `ServiceResult` with provenance metadata

```python
@dataclass(frozen=True)
class ServiceResult:
    data: Any
    source_system: str
    connector_key: str
    fetched_at: str
    partial_failures: list[str]
```

#### Scenario: Single-system route

- **WHEN** `capability_key="monitoring.trend"`, route has `primary_system_key="ins_prod"`, no enrich
- **THEN** router calls `InsAdapter.call("monitoring.trend", params, ctx)`
- **THEN** returns `ServiceResult(data=TrendSeries(...), source_system="ins_prod", partial_failures=[])`

#### Scenario: Multi-system enrich

- **WHEN** `capability_key="asset.overview"`, route has `primary="ins_prod"`, `enrich=["sms_prod"]`
- **THEN** router calls `InsAdapter.call(...)` for primary data
- **THEN** in parallel, calls `SmsAdapter.call(...)` for enrich data
- **THEN** merges enrich data into primary result
- **THEN** returns `ServiceResult` with both sources' data

#### Scenario: Primary failure with fallback

- **WHEN** primary adapter raises `AdapterError`
- **THEN** router tries `fallback_system_keys` in order
- **THEN** first successful fallback becomes the result
- **THEN** `source_system` reflects the fallback system that succeeded

#### Scenario: All systems fail

- **WHEN** primary and all fallback adapters raise errors
- **THEN** router raises `IntegrationError("所有系统均不可用: {capability_key}")`

#### Scenario: Enrich partial failure

- **WHEN** primary succeeds but one enrich adapter fails
- **THEN** result includes primary data + successful enrich data
- **THEN** `partial_failures` lists the failed enrich system: `["sms_prod: ConnectionRefused"]`

#### Scenario: Route not found

- **WHEN** no `CapabilityRouteConfig` exists for the given `capability_key`
- **THEN** router raises `RouteNotFoundError("No route for capability: {key}")`

### Requirement: AuthContext propagation

The system SHALL provide an `AuthContext` frozen dataclass that carries the authenticated user's identity from the App layer through Service → Router → Adapter. The `AuthContext` SHALL contain:

- `user_id: str` — the effective user ID
- `org_id: int | None` — the organization ID (for Ins org-based queries)
- `token: str | None` — the authentication token
- `tenant_id: str` — the resolved tenant ID

The App layer (routers, middleware) SHALL construct `AuthContext` from the request and pass it to the tools. Tools SHALL include it when calling services. Services SHALL pass it to the router. The router SHALL pass it to adapters.

Adapters SHALL NOT log or expose the `token` value in error messages or server logs.

#### Scenario: AuthContext from authenticated request

- **WHEN** an authenticated user (user_id="42", org_id=100, tenant_id="factory-A") calls a tool
- **THEN** `AuthContext(user_id="42", org_id=100, tenant_id="factory-A", token="eyJ...")` is constructed
- **THEN** passed through Service → Router → Adapter chain

#### Scenario: Token not in error messages

- **WHEN** an adapter's downstream call fails with 401
- **THEN** the error message is `"authentication failed"` — the token value is NOT included
- **THEN** the server log records the failure without the token

#### Scenario: No-auth mode

- **WHEN** the system is running with `auth.enabled: false`
- **THEN** `AuthContext` is constructed with `user_id="default"`, `org_id=None`, `token=None`, `tenant_id="default"`

### Requirement: Unified error model

The system SHALL define a unified error hierarchy in `deerflow/integrations/errors.py` for all integration-related exceptions. All adapters, services, and tools SHALL use these error types instead of system-specific exceptions.

**Error types:**

1. `IntegrationError` — base class for all integration errors
2. `IntegrationConfigError` — configuration parsing or validation errors (e.g. missing field, invalid value)
3. `IntegrationAuthError` — authentication/authorization failures (e.g. invalid token, expired credentials)
4. `IntegrationTimeoutError` — request timeout exceeded
5. `IntegrationUnavailableError` — system unreachable or health check failed
6. `IntegrationDataShapeError` — response structure mismatch (e.g. expected dict, got list)
7. `EntityLinkNotFound` — cross-system entity mapping does not exist
8. `CapabilityRouteNotFoundError` — no route configured for the requested capability

All errors SHALL include:

- `message: str` — human-readable error description
- `system_key: str | None` — which system caused the error (if applicable)
- `capability_key: str | None` — which capability was being accessed (if applicable)

```python
class IntegrationError(Exception):
    def __init__(self, message: str, system_key: str | None = None,
                 capability_key: str | None = None):
        super().__init__(message)
        self.system_key = system_key
        self.capability_key = capability_key

class IntegrationConfigError(IntegrationError): ...
class IntegrationAuthError(IntegrationError): ...
class IntegrationTimeoutError(IntegrationError): ...
class IntegrationUnavailableError(IntegrationError): ...
class IntegrationDataShapeError(IntegrationError): ...
class EntityLinkNotFound(IntegrationError): ...
class CapabilityRouteNotFoundError(IntegrationError): ...
```

#### Scenario: Adapter raises IntegrationAuthError

- **WHEN** `InsAdapter.call()` receives HTTP 401 from Ins system
- **THEN** adapter raises `IntegrationAuthError(message="Ins authentication failed", system_key="ins_prod", capability_key="monitoring.trend")`
- **THEN** the error does NOT include the actual token value

#### Scenario: Router raises IntegrationTimeoutError

- **WHEN** primary adapter call exceeds `route.timeout_seconds`
- **THEN** router raises `IntegrationTimeoutError(message="Capability request timed out after 30s", system_key="ins_prod", capability_key="monitoring.trend")`

#### Scenario: Adapter raises IntegrationDataShapeError

- **WHEN** Sms API returns a list instead of expected dict for health assessment
- **THEN** adapter raises `IntegrationDataShapeError(message="Expected dict, got list", system_key="sms_prod", capability_key="health.assessment")`

#### Scenario: Router raises CapabilityRouteNotFoundError

- **WHEN** `router.route(capability_key="maintenance.work_order", ...)` is called
- **THEN** and no route exists for `maintenance.work_order`
- **THEN** router raises `CapabilityRouteNotFoundError(message="No route for capability: maintenance.work_order", capability_key="maintenance.work_order")`

#### Scenario: EntityLinkResolver raises EntityLinkNotFound

- **WHEN** `resolver.resolve(entity_type="asset", canonical_id="asset:001", system_key="erp_prod")` is called
- **THEN** and no mapping exists for `asset:001` in `erp_prod`
- **THEN** resolver raises `EntityLinkNotFound(message="Entity link not found: asset:001 -> erp_prod", system_key="erp_prod")`

#### Scenario: Tool catches IntegrationError

- **WHEN** a tool calls a service method that raises any `IntegrationError` subclass
- **THEN** tool catches the error and returns a user-friendly message
- **THEN** tool does NOT re-raise the error to the Agent

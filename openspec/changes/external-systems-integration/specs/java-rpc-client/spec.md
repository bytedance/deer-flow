## MODIFIED Requirements

### Requirement: Per-service auth_headers injection in RpcServiceConfig

The system SHALL extend `RpcServiceConfig` in `deerflow/config/rpc_config.py` with an optional `auth_headers` field. This field SHALL allow per-service custom authentication headers to be injected into every RPC call made to that service.

The `auth_headers` field SHALL be a dict mapping header names to header values or environment variable references:

```python
class RpcServiceConfig(BaseModel):
    # ... existing fields ...
    auth_headers: dict[str, str] | None = Field(
        default=None,
        description="Per-service authentication headers. Values starting with $ are resolved as environment variables.",
    )
```

When the `RpcClient` makes a call to a service that has `auth_headers` configured, the client SHALL merge these headers into the request. Service-level `auth_headers` SHALL take precedence over any global default headers but SHALL NOT override `Content-Type` or `Accept`.

Environment variable references (`$ENV_VAR_NAME`) SHALL be resolved at call time (not at config load time) so that rotated secrets are picked up without restart. If the referenced environment variable is not set, the header SHALL be omitted and a `WARNING` logged.

#### Scenario: Service with static auth header

- **WHEN** `RpcServiceConfig` has `auth_headers: {"X-API-Key": "static-key-123"}`
- **THEN** every `RpcClient.call()` to that service includes `X-API-Key: static-key-123` in the request headers
- **THEN** the header is merged with the default headers (`Content-Type`, `Accept`)

#### Scenario: Service with environment variable reference

- **WHEN** `RpcServiceConfig` has `auth_headers: {"X-API-Key": "$SMS_API_KEY"}`
- **THEN** at call time, `RpcClient` resolves `$SMS_API_KEY` from the environment
- **THEN** the resolved value is included as the header value
- **THEN** if `SMS_API_KEY` is not set, the header is omitted and a `WARNING` is logged

#### Scenario: Auth header does not override Content-Type

- **WHEN** `auth_headers` includes `{"Content-Type": "text/plain"}`
- **THEN** `RpcClient` ignores this override attempt
- **THEN** `Content-Type: application/json` is preserved in the request
- **THEN** a `WARNING` is logged: `"auth_headers cannot override Content-Type"`

#### Scenario: Auth header takes precedence over global defaults

- **WHEN** `RpcClient` has a global default `Authorization: Bearer global-token`
- **THEN** and a service has `auth_headers: {"Authorization": "Bearer service-token"}`
- **THEN** calls to that service use `Authorization: Bearer service-token`
- **THEN** calls to other services use `Authorization: Bearer global-token`

#### Scenario: No auth_headers configured

- **WHEN** `RpcServiceConfig` has `auth_headers: null` (default)
- **THEN** `RpcClient` makes calls with only the default headers
- **THEN** behavior is identical to the current implementation

### Requirement: Per-service response_unwrapper configuration

The system SHALL extend `RpcServiceConfig` with an optional `response_unwrapper` field. This field SHALL specify a custom response unwrapping strategy for services that do not follow the standard Java `ResultT`/`AjaxResult` response format.

Currently, `RpcClient.call()` assumes all responses follow the the Java microservice convention:

```json
{"code": 200, "msg": "success", "data": {...}}
```

The `response_unwrapper` field SHALL support these values:

- `"java_standard"` (default) — unwrap `{code, msg, data}` format, raise on non-200 code
- `"passthrough"` — return the raw response body without unwrapping (for non-Java services)
- `"http_status_only"` — consider HTTP 2xx as success, return the response body directly
- A dotted Python import path (e.g. `"deerflow.integrations.adapters.sms:unwrap_sms_response"`) — call a custom unwrapping function

```python
class RpcServiceConfig(BaseModel):
    # ... existing fields ...
    response_unwrapper: str = Field(
        default="java_standard",
        description="Response unwrapping strategy: 'java_standard', 'passthrough', 'http_status_only', or a dotted import path.",
    )
```

The `RpcClient.call()` method SHALL consult the service's `response_unwrapper` before processing the response.

#### Scenario: Java standard unwrapping (default)

- **WHEN** `response_unwrapper` is `"java_standard"` (default)
- **THEN** `RpcClient.call()` unwraps `{code: 200, data: {...}}` → returns `{...}`
- **THEN** on `{code: 500, msg: "error"}` → raises `RpcError`
- **THEN** behavior is identical to the current implementation

#### Scenario: Passthrough unwrapping

- **WHEN** `response_unwrapper` is `"passthrough"`
- **THEN** `RpcClient.call()` returns the raw JSON response body without any unwrapping
- **THEN** no code/msg checking is performed
- **THEN** the caller is responsible for handling the response format

#### Scenario: HTTP status only unwrapping

- **WHEN** `response_unwrapper` is `"http_status_only"`
- **THEN** `RpcClient.call()` checks HTTP status code only
- **THEN** on HTTP 2xx → returns the response body as-is
- **THEN** on HTTP 4xx/5xx → raises `RpcError` with the status code and response body

#### Scenario: Custom unwrapping function

- **WHEN** `response_unwrapper` is `"deerflow.integrations.adapters.sms:unwrap_sms_response"`
- **THEN** `RpcClient.call()` imports the function via `resolve_variable`
- **THEN** passes the raw response body to the function
- **THEN** returns the function's return value
- **THEN** if the import fails, raises `RpcError` with a clear message

#### Scenario: Existing services unaffected

- **WHEN** existing `ins-base-rpc` and `ins-bus-rpc` services have no `response_unwrapper` configured
- **THEN** they use the default `"java_standard"` unwrapping
- **THEN** behavior is identical to the current implementation

### Requirement: Sms RPC service configuration

The `config.yaml` `rpc.services` list SHALL support a new Sms service entry. When Sms uses a standard HTTP API (not Nacos-discovered Java microservice), the service configuration SHALL use `base_url` with `response_unwrapper: "http_status_only"` and `auth_headers` for API key authentication.

Example configuration:

```yaml
rpc:
  services:
    # ... existing ins-base-rpc, ins-bus-rpc ...
    - name: "sms-api"
      base_url: "http://sms-api:8080"
      timeout: 15.0
      response_unwrapper: "http_status_only"
      auth_headers:
        X-API-Key: "$SMS_API_KEY"
      endpoints:
        - method: "get_anomaly_stats"
          path: "/api/v1/anomaly/stats"
          http_method: "POST"
        - method: "get_health_assessment"
          path: "/api/v1/health/assessment"
          http_method: "POST"
        - method: "get_fault_trend"
          path: "/api/v1/fault/trend"
          http_method: "POST"
```

#### Scenario: Sms service configured in config.yaml

- **WHEN** `config.yaml` includes an `sms-api` service in `rpc.services`
- **THEN** `RpcConfig` parses the service with `response_unwrapper: "http_status_only"`
- **THEN** `RpcConfig` parses the service with `auth_headers: {"X-API-Key": "$SMS_API_KEY"}`
- **THEN** `get_rpc_config().services` includes the Sms service entry

#### Scenario: RpcClient calls Sms service

- **WHEN** `RpcClient.call("sms-api", "get_anomaly_stats", body={...})` is invoked
- **THEN** the request includes `X-API-Key: <resolved SMS_API_KEY>` header
- **THEN** the response is unwrapped using `"http_status_only"` strategy
- **THEN** on HTTP 200 → returns the response body
- **THEN** on HTTP 500 → raises `RpcError`

#### Scenario: Sms service not configured

- **WHEN** `config.yaml` does not include an `sms-api` service
- **THEN** `RpcClient.call("sms-api", ...)` raises `RpcError` with message `"Service 'sms-api' not configured"`
- **THEN** the SmsDataProvider falls back to direct httpx calls (as per its spec)

### Requirement: RpcClient health check endpoint support

The `RpcClient` SHALL support a lightweight health check method that verifies service connectivity without invoking a business endpoint. This SHALL be used by the `ProviderRegistry` health check scheduler.

```python
async def health_check(self, service_name: str, path: str = "/health", timeout: float = 5.0) -> HealthStatus:
    """Check if a service is reachable and responding.

    Returns HealthStatus(healthy=True/False, latency_ms=..., message=...).
    Does NOT raise exceptions — all errors are captured in HealthStatus.
    """
```

The method SHALL:

1. Resolve the service URL via Nacos discovery or `base_url`
2. Send a GET request to the health path
3. Measure response time
4. Return `HealthStatus` with the result

#### Scenario: Healthy service

- **WHEN** `RpcClient.health_check("ins-base-rpc", "/ins-base-rpc/health")` is called
- **THEN** the service responds with HTTP 200 within timeout
- **THEN** returns `HealthStatus(healthy=True, latency_ms=45, message="OK")`

#### Scenario: Unreachable service

- **WHEN** `RpcClient.health_check("sms-api", "/api/health")` is called
- **THEN** the service is unreachable (connection refused)
- **THEN** returns `HealthStatus(healthy=False, latency_ms=None, message="connection refused")`

#### Scenario: Slow service

- **WHEN** `RpcClient.health_check("ins-bus-rpc", timeout=5.0)` is called
- **THEN** the service does not respond within 5 seconds
- **THEN** returns `HealthStatus(healthy=False, latency_ms=None, message="timeout after 5.0s")`

#### Scenario: Non-2xx health endpoint

- **WHEN** `RpcClient.health_check("sms-api")` is called
- **THEN** the service returns HTTP 503
- **THEN** returns `HealthStatus(healthy=False, latency_ms=120, message="service unavailable (503)")`

### Requirement: RpcClient backward compatibility

All modifications to `RpcClient`, `RpcServiceConfig`, and `RpcConfig` SHALL be backward compatible. Existing code that uses `RpcClient.call()` for `ins-base-rpc` and `ins-bus-rpc` SHALL continue to work without any changes.

The `auth_headers` and `response_unwrapper` fields SHALL have safe defaults (`None` and `"java_standard"` respectively) that preserve current behavior. No existing method signatures SHALL change.

#### Scenario: Existing MachineServiceClient calls

- **WHEN** `MachineServiceClient.get_machine_detail_info()` is called
- **THEN** it uses `RpcClient.call("ins-bus-rpc", ...)` with the existing API
- **THEN** the call succeeds with the same behavior as before this change
- **THEN** no `auth_headers` or `response_unwrapper` logic is triggered (defaults apply)

#### Scenario: Existing InsBaseAuthServiceClient calls

- **WHEN** `InsBaseAuthServiceClient.login()` is called
- **THEN** it uses `RpcClient.call("ins-base-rpc", ...)` with the existing API
- **THEN** the call succeeds with the same behavior as before this change

#### Scenario: New Sms calls alongside existing calls

- **WHEN** both `MachineServiceClient` and `SmsDataProvider` are active
- **THEN** `MachineServiceClient` uses `ins-bus-rpc` with `"java_standard"` unwrapping
- **THEN** `SmsDataProvider` uses `sms-api` with `"http_status_only"` unwrapping and `auth_headers`
- **THEN** both work independently without interference

## ADDED Requirements

### Requirement: SmsAdapter implements IntegrationAdapter

The system SHALL provide `SmsAdapter` in `deerflow/integrations/adapters/sms/adapter.py` that implements `IntegrationAdapter`. The adapter SHALL use an independent `httpx.AsyncClient` for communication with the Sms system (NOT `RpcClient`, since Sms may not be a Java microservice).

The adapter SHALL declare support for these capability keys:

- `health.assessment` — health score and recommendations
- `health.anomaly_statistics` — anomaly statistics and trends
- `health.risk_ranking` — risk ranking across equipment

#### Scenario: Adapter initialization with API key

- **WHEN** `SmsAdapter.initialize()` is called with config containing `base_url` and `secret_ref: "$SMS_API_KEY"`
- **THEN** it creates an `httpx.AsyncClient` with `base_url` as the base
- **THEN** it reads the API key from the `SMS_API_KEY` environment variable
- **THEN** the API key is stored internally (not logged)

#### Scenario: Missing API key

- **WHEN** `SMS_API_KEY` environment variable is not set
- **THEN** adapter logs a warning: `"SmsAdapter: API key not configured (env: SMS_API_KEY)"`
- **THEN** `health_check()` returns `HealthStatus(healthy=False, message="API key not configured")`
- **THEN** `call()` invocations raise `AdapterError("sms_prod", capability_key, "auth_not_configured")`

### Requirement: SmsAdapter health.assessment capability

`SmsAdapter.call("health.assessment", params, ctx)` SHALL query the Sms health assessment API and transform the response into `HealthAssessment`.

Accepts `HealthAssessmentQuery` as `params`:

- `asset_id: str` — target equipment (required)
- `window: str` — assessment window (default: `"7d"`)

The response SHALL be transformed into:

```python
HealthAssessment(
    asset_id=query.asset_id,
    assessment_time=raw["assessment_time"],
    overall_score=raw["overall_score"],
    level=raw["level"],
    summary=raw["summary"],
    dimensions=raw["dimensions"],
    risk_items=tuple(RiskItem(**r) for r in raw["risk_items"]),
    recommendations=tuple(raw["recommendations"]),
    source_metadata=raw.get("extra", {}),
    provenance=Provenance(
        source_system="sms_prod",
        capability_key="health.assessment",
        fetched_at=datetime.utcnow().isoformat(),
        partial_failures=(),
    ),
)
```

#### Scenario: Fetch health assessment

- **WHEN** `call("health.assessment", HealthAssessmentQuery(asset_id="asset:001"), ctx)`
- **THEN** adapter queries Sms API, transforms to `HealthAssessment`
- **THEN** `dimensions` includes per-dimension scores (e.g. vibration, temperature, process_stability)
- **THEN** `risk_items` includes structured risk entries with `code`, `severity`, `message`
- **THEN** `summary` is a human-readable description

#### Scenario: Equipment not found

- **WHEN** Sms API returns 404 for the asset_id
- **THEN** adapter raises `AdapterError("sms_prod", "health.assessment", "equipment_not_found")`

### Requirement: SmsAdapter health.anomaly_statistics capability

`SmsAdapter.call("health.anomaly_statistics", params, ctx)` SHALL query the Sms anomaly statistics API and transform the response into `AnomalyStats`.

Parameters:

- `asset_id: str | None` — target equipment (None = global)
- `time_range: str` — e.g. `"7d"`, `"30d"`, `"90d"` (default: `"30d"`)
- `anomaly_types: list[str] | None` — filter by specific anomaly types

#### Scenario: Fetch anomaly statistics

- **WHEN** `call("health.anomaly_statistics", {"asset_id": "asset:001", "time_range": "30d"}, ctx)`
- **THEN** adapter queries Sms API, transforms to `AnomalyStats`
- **THEN** `total_count`, `by_type`, `trend`, `top_equipment` are populated

#### Scenario: Global anomaly statistics

- **WHEN** `call("health.anomaly_statistics", {"time_range": "7d"}, ctx)` (no asset_id)
- **THEN** returns statistics across all equipment
- **THEN** `top_equipment` lists the 5 most anomalous equipment

#### Scenario: Empty result

- **WHEN** the Sms API returns no anomalies for the given range
- **THEN** `total_count` = 0, `by_type` = `{}`, `top_equipment` = `()`

### Requirement: SmsAdapter health.risk_ranking capability

`SmsAdapter.call("health.risk_ranking", params, ctx)` SHALL query the Sms risk ranking API and transform the response into `RiskRanking`.

Parameters:

- `period: str` — ranking period, e.g. `"7d"`, `"30d"` (default: `"7d"`)
- `limit: int` — max results (default: 20)

#### Scenario: Fetch risk ranking

- **WHEN** `call("health.risk_ranking", {"period": "7d", "limit": 10}, ctx)`
- **THEN** returns `RiskRanking` with top 10 equipment by risk score
- **THEN** each `EquipmentRisk` includes `asset_id`, `risk_score`, `level`, `top_risk_items`

### Requirement: SmsAdapter health check

`SmsAdapter.health_check()` SHALL call the configured health check endpoint.

#### Scenario: Healthy Sms system

- **WHEN** Sms health endpoint returns HTTP 200
- **THEN** returns `HealthStatus(healthy=True, latency_ms=80, message="OK")`

#### Scenario: Sms system unreachable

- **WHEN** Sms health endpoint is unreachable
- **THEN** returns `HealthStatus(healthy=False, latency_ms=None, message="connection refused")`

#### Scenario: Sms returns non-2xx

- **WHEN** Sms health endpoint returns HTTP 503
- **THEN** returns `HealthStatus(healthy=False, message="service unavailable (503)")`

### Requirement: SmsAdapter API key authentication

The `SmsAdapter` SHALL include the API key in every request to the Sms system. The key SHALL be sent as a header specified by `extra_config.auth_header` (default: `"X-API-Key"`).

The adapter SHALL NOT log or expose the API key value in error messages, server logs, or canonical model `source_metadata`.

#### Scenario: API key in request header

- **WHEN** adapter makes any API call to Sms
- **THEN** the request includes the configured header (e.g. `X-API-Key: <value>`)

#### Scenario: API key not in error log

- **WHEN** an Sms API call fails with 401
- **THEN** the error log records `"Sms authentication failed"` without the API key value

### Requirement: SmsAdapter error handling

All SmsAdapter errors SHALL be wrapped in `AdapterError` with structured error codes:

- HTTP 401/403 → `"auth_failed"`
- HTTP 404 → `"equipment_not_found"`
- HTTP 5xx → `"server_error"`
- Connection refused → `"connection_failed"`
- Timeout → `"timeout"`

#### Scenario: Map HTTP error to AdapterError

- **WHEN** Sms API returns HTTP 500
- **THEN** adapter raises `AdapterError("sms_prod", capability_key, "server_error")`

### Requirement: SmsAdapter transform module

The system SHALL provide `transform.py` (or `mapper.py`) in `deerflow/integrations/adapters/sms/` containing pure functions that convert Sms API responses to canonical models.

Transform functions SHALL:

- Accept raw Sms API response dicts
- Return canonical model instances (`HealthAssessment`, `AnomalyStats`, `RiskRanking`)
- Map Sms-specific field names to canonical field names
- Populate `source_metadata` with unmapped Sms fields
- Populate `provenance` with adapter metadata

#### Scenario: Transform HealthAssessment

- **WHEN** `transform_to_health_assessment(sms_response, query)` is called
- **THEN** Sms `score` → `HealthAssessment.overall_score`
- **THEN** Sms dimension scores → `HealthAssessment.dimensions` dict
- **THEN** Sms risk entries → `HealthAssessment.risk_items` tuple of `RiskItem`
- **THEN** Sms recommendations → `HealthAssessment.recommendations` tuple

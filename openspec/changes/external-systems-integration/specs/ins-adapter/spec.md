## ADDED Requirements

### Requirement: InsAdapter implements IntegrationAdapter

The system SHALL provide `InsAdapter` in `deerflow/integrations/adapters/ins/adapter.py` that implements `IntegrationAdapter`. The adapter SHALL internally delegate to existing `MachineServiceClient` via `client_bridge.py` and extend with realtime monitoring endpoints.

The adapter SHALL declare support for these capability keys:

- `asset.catalog` — equipment list and detail info
- `asset.context` — single equipment context with points, children, related assets
- `monitoring.trend` — trend time series data
- `monitoring.waveform` — waveform/spectrum data
- `monitoring.orbit` — shaft orbit/trajectory data
- `monitoring.alarm_history` — alarm event history

The adapter SHALL NOT modify or replace the existing `MachineServiceClient` or `InsBaseAuthServiceClient` classes.

#### Scenario: Adapter initialization

- **WHEN** `InsAdapter.initialize()` is called with a valid `RpcClient`
- **THEN** it creates internal `MachineServiceClient(rpc_client)` reference via `client_bridge.py`
- **THEN** `system_key` returns `"ins_prod"` (from config)
- **THEN** `system_type` returns `"ins"`

#### Scenario: Existing clients remain functional

- **WHEN** `InsAdapter` is active and another module creates its own `MachineServiceClient()`
- **THEN** both work independently without interference

### Requirement: InsAdapter client bridge

The system SHALL provide `client_bridge.py` in `deerflow/integrations/adapters/ins/` that wraps or reuses the existing `InsApiClient` from `docker/sandbox/features-tool/ins/client.py`. This bridge SHALL:

- Reuse existing authentication and token management logic
- Reuse existing series routing logic (2k/6k/8k/9k endpoints)
- Reuse existing response flattening logic
- NOT duplicate or rewrite the underlying client

The bridge SHALL be a temporary migration artifact. Phase 2+ may internalize the client logic directly into the adapter.

#### Scenario: Bridge reuses InsApiClient

- **WHEN** `InsAdapter` makes a waveform request
- **THEN** `client_bridge.py` calls the existing `InsApiClient.get_waveform()` method
- **THEN** authentication, series routing, and response parsing use existing logic

#### Scenario: Bridge does not modify existing client

- **WHEN** `client_bridge.py` is loaded
- **THEN** the original `InsApiClient` class remains unchanged
- **THEN** existing sandbox tools continue to work

### Requirement: InsAdapter asset.catalog capability

`InsAdapter.call("asset.catalog", params, ctx)` SHALL delegate to `MachineServiceClient.get_machine_detail_info()`, transforming the response into canonical `Asset` models.

Accepts `AssetCatalogQuery` as `params`:

- `name: str | None` — fuzzy name filter
- `kind: str | None` — type filter
- `area: str | None` — area filter
- `limit: int` — pagination limit (default: 100)
- `offset: int` — pagination offset (default: 0)

#### Scenario: Fetch equipment list

- **WHEN** `call("asset.catalog", AssetCatalogQuery(name="泵", limit=5), ctx)`
- **THEN** adapter calls `MachineServiceClient.get_machine_detail_info(user_id=ctx.user_id, org_id=ctx.org_id, machine_name="泵", page_size=5)`
- **THEN** transforms response to `tuple[Asset, ...]`
- **THEN** each `Asset` includes `id`, `name`, `display_name`, `kind`, `subtype`, `area`, `location`, `status`, `tags`

#### Scenario: Fetch by IDs

- **WHEN** `call("asset.catalog", {"equipment_ids": ["1", "2", "3"]}, ctx)`
- **THEN** adapter calls `MachineServiceClient.get_machine_info_by_ids(["1", "2", "3"])`
- **THEN** returns 3 `Asset` instances

#### Scenario: Connection error

- **WHEN** `MachineServiceClient` raises `RpcConnectionError`
- **THEN** adapter raises `AdapterError("ins_prod", "asset.catalog", "connection_failed")`

### Requirement: InsAdapter asset.context capability

`InsAdapter.call("asset.context", params, ctx)` SHALL fetch a single equipment's full context including children, measurement points, and related assets, returning an `AssetContext`.

Accepts `AssetContextQuery` as `params`:

- `asset_id: str` — target equipment (required)
- `include_children: bool` — include sub-equipment (default: `true`)
- `include_points: bool` — include measurement points (default: `true`)
- `include_related: bool` — include related assets (default: `false`)

#### Scenario: Fetch full equipment context

- **WHEN** `call("asset.context", AssetContextQuery(asset_id="asset:001"), ctx)`
- **THEN** adapter fetches the asset, its children, measurement points
- **THEN** returns `AssetContext(asset=..., children=(...), points=(...), related_assets=())`
- **THEN** each `MeasurementPoint` includes `id`, `asset_id`, `name`, `point_type`, `unit`, `endpoint_series`, `alarm_thresholds`

#### Scenario: Equipment not found

- **WHEN** Ins API returns no data for the asset_id
- **THEN** adapter raises `AdapterError("ins_prod", "asset.context", "equipment_not_found")`

### Requirement: InsAdapter monitoring.trend capability

`InsAdapter.call("monitoring.trend", params, ctx)` SHALL query Ins realtime data endpoints and transform the response into `TrendSeries`.

Accepts `TrendQuery` as `params`:

- `asset_id: str` — target equipment
- `point_id: str | None` — specific measurement point
- `metric_key: str | None` — which metric ("vibration_level", "temperature", "speed")
- `time_range: TimeRange | None` — explicit start/end (default: last 24h)
- `aggregation: str` — "hourly", "daily", "raw" (default: "hourly")

The adapter SHALL use the KPI Feature Map (extracted from `_ins_provider.py`) to determine which Ins endpoints and measurement points to query.

#### Scenario: Fetch vibration trend

- **WHEN** `call("monitoring.trend", TrendQuery(asset_id="asset:001", metric_key="vibration_level", aggregation="hourly"), ctx)`
- **THEN** adapter queries Ins trend endpoint for vibration data
- **THEN** returns `TrendSeries` with `series_id`, `asset_id`, `point_id`, `metric_key`, `display_name="振动水平"`, `unit="mm/s"`, populated `samples`, `statistics`, `time_range`

#### Scenario: Equipment not found

- **WHEN** Ins API returns no data for the asset_id
- **THEN** adapter raises `AdapterError("ins_prod", "monitoring.trend", "equipment_not_found")`

### Requirement: InsAdapter monitoring.waveform capability

`InsAdapter.call("monitoring.waveform", params, ctx)` SHALL query Ins waveform/spectrum endpoints and transform the response into `WaveformPayload`.

Accepts `WaveformQuery` as `params`:

- `asset_id: str` — target equipment
- `point_id: str` — specific measurement point
- `captured_at: str | None` — historical capture time (default: latest)

#### Scenario: Fetch latest waveform

- **WHEN** `call("monitoring.waveform", WaveformQuery(asset_id="asset:001", point_id="point:001"), ctx)`
- **THEN** returns `WaveformPayload` with `wave_x`, `wave_y`, `spec_x`, `spec_y`, `sample_rate`, `speed_rpm`, `unit`

### Requirement: InsAdapter monitoring.orbit capability

`InsAdapter.call("monitoring.orbit", params, ctx)` SHALL query Ins orbit/trajectory endpoints and transform the response into `OrbitPayload`.

Accepts `OrbitQuery` as `params`:

- `asset_id: str` — target equipment
- `bearing_id: str` — specific bearing (e.g. "bearing:DE")
- `captured_at: str | None` — historical capture time (default: latest)

#### Scenario: Fetch latest orbit

- **WHEN** `call("monitoring.orbit", OrbitQuery(asset_id="asset:001", bearing_id="bearing:DE"), ctx)`
- **THEN** returns `OrbitPayload` with `probe_ids`, `points`, `points_1x`, `points_2x`, `speed_rpm`

#### Scenario: Bearing not found

- **WHEN** Ins API returns no data for the bearing_id
- **THEN** adapter raises `AdapterError("ins_prod", "monitoring.orbit", "bearing_not_found")`

### Requirement: InsAdapter monitoring.alarm_history capability

`InsAdapter.call("monitoring.alarm_history", params, ctx)` SHALL query Ins alarm endpoints and transform the response into `tuple[AlarmEvent, ...]`.

Accepts `AlarmHistoryQuery` as `params`:

- `asset_id: str | None` — target equipment (None = all)
- `limit: int` — max results (default: 50)
- `time_range: TimeRange | None` — explicit start/end
- `severity_min: str | None` — filter by minimum severity

#### Scenario: Fetch alarm history

- **WHEN** `call("monitoring.alarm_history", AlarmHistoryQuery(asset_id="asset:001", limit=20), ctx)`
- **THEN** returns `tuple[AlarmEvent, ...]` sorted by `started_at` descending
- **THEN** each `AlarmEvent` includes `id`, `asset_id`, `point_id`, `event_type`, `severity`, `title`, `message`, `started_at`, `ended_at`, `duration_seconds`

### Requirement: InsAdapter health check

`InsAdapter.health_check()` SHALL verify connectivity to both `ins-base-rpc` and `ins-bus-rpc` services.

#### Scenario: Both services healthy

- **WHEN** both `ins-base-rpc` and `ins-bus-rpc` respond within timeout
- **THEN** returns `HealthStatus(healthy=True, latency_ms=150, message="OK")`

#### Scenario: One service unreachable

- **WHEN** `ins-bus-rpc` is unreachable but `ins-base-rpc` responds
- **THEN** returns `HealthStatus(healthy=False, latency_ms=None, message="ins-bus-rpc: connection refused")`

### Requirement: InsAdapter auth token propagation

When `AuthContext.token` is non-null, `InsAdapter` SHALL propagate it to downstream Ins API calls. The adapter SHALL NOT log the token value.

#### Scenario: Token propagated to RPC call

- **WHEN** `auth_context.token = "eyJhbG..."` and adapter makes an Ins API call
- **THEN** the token is included in the downstream request

#### Scenario: Token redacted in error log

- **WHEN** an authenticated call fails
- **THEN** the log entry shows `"token": "[REDACTED]"` — not the actual token value

### Requirement: KPI Feature Map extraction

The `_KPI_FEATURE_MAP` and `_select_points_for_kpi` logic from `_ins_provider.py` SHALL be extracted to `deerflow/integrations/adapters/ins/kpi_map.py` as a pure data + pure logic module.

The sandbox `_ins_provider.py` SHALL retain its own copy as a fallback during the transition period.

#### Scenario: Platform layer has KPI Feature Map

- **WHEN** `deerflow/integrations/adapters/ins/kpi_map.py` is imported
- **THEN** `KPI_FEATURE_MAP` dict is available with the same structure as `_ins_provider._KPI_FEATURE_MAP`
- **THEN** `select_points_for_kpi()` function is available

#### Scenario: Sandbox retains fallback

- **WHEN** `_ins_provider.py` is loaded in the sandbox
- **THEN** its local `_KPI_FEATURE_MAP` is still available
- **THEN** the features-tool path works independently

### Requirement: InsAdapter transform module

The system SHALL provide `transform.py` (or `mapper.py`) in `deerflow/integrations/adapters/ins/` containing pure functions that convert Ins API responses to canonical models.

Transform functions SHALL:

- Accept raw Ins API response dicts
- Return canonical model instances
- Map Ins-specific field names to canonical field names
- Map Ins-specific enums to canonical enums
- Populate `source_metadata` with unmapped Ins fields
- Populate `provenance` with adapter metadata

#### Scenario: Transform Asset

- **WHEN** `transform_to_asset(ins_response)` is called
- **THEN** Ins `machineId` → `Asset.id` (prefixed with `"asset:"`)
- **THEN** Ins `machineName` → `Asset.name`
- **THEN** Ins `displayName` → `Asset.display_name`
- **THEN** Ins `machineType` → `Asset.kind` (mapped to platform enum)
- **THEN** unmapped fields stored in `source_metadata`

#### Scenario: Transform TrendSeries

- **WHEN** `transform_to_trend_series(ins_response, query)` is called
- **THEN** Ins time series data → `TrendSeries.samples`
- **THEN** statistics computed from samples → `TrendSeries.statistics`
- **THEN** `series_id` constructed from `asset_id` + `metric_key`

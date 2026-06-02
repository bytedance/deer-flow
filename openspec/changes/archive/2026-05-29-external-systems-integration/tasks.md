## Phase 1: Three-Layer Architecture + InsAdapter + Reasoning Tools (2 weeks)

### 1.1 Configuration & Data Models

- [x] 1.1.1 Create `deerflow/integrations/` package with `__init__.py`
- [x] 1.1.2 Create `deerflow/integrations/config.py` with Pydantic models: `IntegrationSystemConfig`, `CapabilityRouteConfig`, `EntityLinkConfig`, `IntegrationsConfig`
- [x] 1.1.3 Add `integrations: IntegrationsConfig | None` field to `AppConfig` in `deerflow/config/app_config.py` (default: `None`)
- [x] 1.1.4 Add `integrations` section to `config.example.yaml` with Ins and Sms example entries (including `connector_ref`, `transport_type`, `merge_policy`, `partial_failure_policy`)
- [x] 1.1.5 Implement secret reference resolution (`$ENV_VAR` → `os.environ` lookup) in `IntegrationSystemConfig.resolve_secret()`
- [x] 1.1.6 Implement CapabilityRoute parser accepting both simple form (`"ins_prod"`) and full form (`{primary, enrich, fallback, merge_policy, partial_failure_policy}`)
- [x] 1.1.7 Implement connector_ref resolution — resolve existing tenant connector record at adapter initialization time
- [x] 1.1.8 Write unit tests for config models (validation, defaults, secret resolution, route parsing, connector_ref)

### 1.2 Canonical Models

- [x] 1.2.1 Create `deerflow/integrations/models/` package
- [x] 1.2.2 Define asset models in `models/asset.py`: `Asset`, `AssetContext`, `MeasurementPoint` (frozen dataclasses with `source_metadata` and `provenance` fields)
- [x] 1.2.3 Define monitoring models in `models/monitoring.py`: `TrendSeries`, `TrendPoint`, `TrendStatistics`, `TimeRange`, `WaveformPayload`, `OrbitPayload`, `AlarmEvent`
- [x] 1.2.4 Define assessment models in `models/assessment.py`: `HealthAssessment`, `RiskItem`, `AnomalyStats`, `RiskRanking`, `EquipmentRisk`
- [x] 1.2.5 Define composite model in `models/overview.py`: `AssetOverview` (aggregates `Asset`, `AssetContext`, `HealthAssessment`, `AlarmEvent` tuple)
- [x] 1.2.6 Define provenance model in `models/provenance.py`: `Provenance`, `PartialFailure`
- [x] 1.2.7 Define query objects in `models/queries.py`: `AssetCatalogQuery`, `AssetContextQuery`, `AssetOverviewQuery`, `TrendQuery`, `WaveformQuery`, `OrbitQuery`, `AlarmHistoryQuery`, `HealthAssessmentQuery`
- [x] 1.2.7 Define unified error hierarchy in `deerflow/integrations/errors.py`: `IntegrationError`, `IntegrationConfigError`, `IntegrationAuthError`, `IntegrationTimeoutError`, `IntegrationUnavailableError`, `IntegrationDataShapeError`, `EntityLinkNotFound`, `CapabilityRouteNotFoundError`
- [x] 1.2.8 Write unit tests for model immutability, provenance fields, and query object defaults

### 1.3 Adapter Protocol & Registry

- [x] 1.3.1 Define `IntegrationAdapter` Protocol in `deerflow/integrations/adapters/base.py` with `system_key`, `system_type`, `call()`, `health_check()`, `initialize()`, `shutdown()`
- [x] 1.3.2 Define `AuthContext` and `HealthStatus` frozen dataclasses
- [x] 1.3.3 Define `ServiceResult` frozen dataclass in `deerflow/integrations/routing.py`
- [x] 1.3.4 Implement `IntegrationRegistry` in `deerflow/integrations/registry.py` — singleton via `get_integration_registry()`
- [x] 1.3.5 Implement `initialize_all()` — parallel with error isolation per adapter
- [x] 1.3.6 Implement `shutdown_all()` — reverse registration order
- [x] 1.3.7 Implement `health_check_all()` — parallel health checks
- [x] 1.3.8 Implement health check scheduler — background asyncio task, exponential backoff on failure, recovery reset
- [x] 1.3.9 Wire registry into Gateway lifespan: `initialize_all()` on startup, cancel scheduler + `shutdown_all()` on shutdown
- [x] 1.3.10 Implement adapter factory registration: `{"ins": InsAdapter, "sms": SmsAdapter}`
- [x] 1.3.11 Write unit tests for IntegrationRegistry (register, get, concept lookup, error isolation, lifecycle)
- [x] 1.3.12 Write unit tests for health check scheduler (interval, backoff, recovery)

### 1.4 CapabilityRouter

- [x] 1.4.1 Implement `CapabilityRouter` in `deerflow/integrations/routing.py` — accepts `IntegrationRegistry` + route config
- [x] 1.4.2 Implement primary adapter dispatch via `adapter.call(capability_key, query, auth_context)`
- [x] 1.4.3 Implement fallback chain — on primary failure, try `fallback_system_keys` in order
- [x] 1.4.4 Implement enrich fanout — `asyncio.gather` parallel calls to `enrich_system_keys` adapters
- [x] 1.4.5 Implement enrich data merge according to `merge_policy` (`primary_plus_enrich`, `primary_only`, `concatenate`)
- [x] 1.4.6 Implement partial failure handling according to `partial_failure_policy` (`return_partial`, `fail_all`, `ignore_failures`)
- [x] 1.4.7 Implement `EntityLinkResolver` in `deerflow/integrations/entity_link.py` — resolve canonical_id → remote_id per system, including `resolve_by_remote()`
- [x] 1.4.8 Write unit tests for CapabilityRouter (single-source, enrich, fallback, all-failed, route-not-found, merge_policy, partial_failure_policy)
- [x] 1.4.9 Write unit tests for EntityLinkResolver (resolve, not-found, confidence filtering, resolve_by_remote)

### 1.5 InsAdapter

- [x] 1.5.1 Implement `InsAdapter` in `deerflow/integrations/adapters/ins/adapter.py` — `system_type="ins"`, capability keys: `asset.catalog`, `asset.context`, `monitoring.trend`, `monitoring.waveform`, `monitoring.orbit`, `monitoring.alarm_history`
- [x] 1.5.2 Implement `client_bridge.py` — wrap/reuse existing `InsApiClient`, reuse auth, series routing (2k/6k/8k/9k), response flattening
- [x] 1.5.3 Implement `asset.catalog` — delegate to `MachineServiceClient.get_machine_detail_info()`, transform to `tuple[Asset, ...]`
- [x] 1.5.4 Implement `asset.context` — fetch single equipment context with children, measurement points, related assets, transform to `AssetContext`
- [x] 1.5.5 Implement `monitoring.trend` — query Ins trend endpoints, transform to `TrendSeries` (with `series_id`, `statistics`, `time_range`)
- [x] 1.5.6 Implement `monitoring.waveform` — query Ins waveform endpoints, transform to `WaveformPayload` (with `wave_x`, `wave_y`, `spec_x`, `spec_y`, `speed_rpm`)
- [x] 1.5.7 Implement `monitoring.orbit` — query Ins orbit endpoints, transform to `OrbitPayload` (with `probe_ids`, `points`, `points_1x`, `points_2x`)
- [x] 1.5.8 Implement `monitoring.alarm_history` — query Ins alarm endpoints, transform to `tuple[AlarmEvent, ...]` (with `event_type`, `ended_at`, `duration_seconds`)
- [x] 1.5.9 Implement `health_check()` — verify both `ins-base-rpc` and `ins-bus-rpc` connectivity
- [x] 1.5.10 Implement `AuthContext` propagation to downstream RPC calls
- [x] 1.5.11 Implement token redaction in error logs
- [x] 1.5.12 Extract `_KPI_FEATURE_MAP` and `_select_points_for_kpi` to `deerflow/integrations/adapters/ins/kpi_map.py`
- [x] 1.5.13 Create Ins → canonical model transform functions in `deerflow/integrations/adapters/ins/transform.py` (or `mapper.py`) — pure functions populating `source_metadata` and `provenance`
- [x] 1.5.14 Write unit tests for InsAdapter (all 6 capabilities, health check, auth propagation, transform)

### 1.6 SmsAdapter

- [x] 1.6.1 Implement `SmsAdapter` in `deerflow/integrations/adapters/sms/adapter.py` — `system_type="sms"`, capability keys: `health.assessment`, `health.anomaly_statistics`, `health.risk_ranking`
- [x] 1.6.2 Implement `initialize()` — create `httpx.AsyncClient` with `base_url`, read API key from `secret_ref`
- [x] 1.6.3 Implement `health.assessment` — query Sms API, transform to `HealthAssessment` (with `summary`, `dimensions`, `risk_items`)
- [x] 1.6.4 Implement `health.anomaly_statistics` — query Sms API, transform to `AnomalyStats`
- [x] 1.6.5 Implement `health.risk_ranking` — query Sms API, transform to `RiskRanking`
- [x] 1.6.6 Implement `health_check()` — call Sms health endpoint, return `HealthStatus`
- [x] 1.6.7 Implement API key authentication (`X-API-Key` header) + redaction from logs
- [x] 1.6.8 Implement error handling — map HTTP errors to `AdapterError` with error codes
- [x] 1.6.9 Create Sms → canonical model transform functions in `deerflow/integrations/adapters/sms/transform.py` (or `mapper.py`) — pure functions populating `source_metadata` and `provenance`
- [x] 1.6.10 Write unit tests for SmsAdapter (all 3 capabilities, health check, auth, error handling, transform)

### 1.7 RpcClient Extensions

- [x] 1.7.1 Add `auth_headers: dict[str, str] | None` field to `RpcServiceConfig` in `deerflow/config/rpc_config.py`
- [x] 1.7.2 Add `response_unwrapper: str` field to `RpcServiceConfig` (default: `"java_standard"`)
- [x] 1.7.3 Implement env var resolution for `auth_headers` values starting with `$` at call time
- [x] 1.7.4 Implement `response_unwrapper` dispatch — support `"java_standard"`, `"passthrough"`, `"http_status_only"`, dotted import path
- [x] 1.7.5 Add `RpcClient.health_check()` method — lightweight connectivity check returning `HealthStatus`
- [x] 1.7.6 Guard against `auth_headers` overriding `Content-Type` or `Accept`
- [x] 1.7.7 Write unit tests for `auth_headers`, `response_unwrapper`, `health_check()`

### 1.8 Service Layer

- [x] 1.8.1 Implement `AssetService` in `deerflow/integrations/services/asset_service.py` — `get_catalog()`, `get_context()`, `get_overview()`
- [x] 1.8.2 Implement `get_overview()` orchestration — multi-call composition: `asset.context` + `health.assessment` + `monitoring.alarm_history` → `AssetOverview`
- [x] 1.8.3 Implement `MonitoringService` in `deerflow/integrations/services/monitoring_service.py` — `get_trend()`, `get_waveform()`, `get_orbit()`, `get_alarm_history()`
- [x] 1.8.4 Implement `AssessmentService` in `deerflow/integrations/services/assessment_service.py` — `get_health_assessment()`, `get_anomaly_statistics()`, `get_risk_ranking()`
- [x] 1.8.5 Each service method delegates to `CapabilityRouter.route()` and returns `ServiceResult`
- [x] 1.8.6 Write unit tests for all service methods (mocking CapabilityRouter), including `get_overview` composite orchestration and partial failure handling

### 1.9 Integration Tools & Agent Integration

- [x] 1.9.1 Define asset tools in `deerflow/integrations/tools/asset_tools.py`: `asset_get_catalog`, `equipment_get_context`, `equipment_get_overview`
- [x] 1.9.2 Define monitoring tools in `deerflow/integrations/tools/monitoring_tools.py`: `monitoring_get_trend`, `monitoring_get_waveform`, `monitoring_get_alarm_history`
- [x] 1.9.3 Define assessment tools in `deerflow/integrations/tools/assessment_tools.py`: `health_get_assessment`, `anomaly_get_stats`, `fault_get_trend`
- [x] 1.9.4 Each tool wraps service method, formats canonical model as Chinese text, includes provenance
- [x] 1.9.5 Implement error handling in tools — map `RouteNotFoundError`, `IntegrationError`, `AdapterError` to user-friendly messages
- [x] 1.9.6 Implement "integrations disabled" case — tools return `"集成层未启用，请联系管理员"`
- [x] 1.9.7 Add `data_tools` field support to Agent config loading
- [x] 1.9.8 Implement selective tool injection in `get_available_tools()` — filter by Agent's `data_tools`
- [x] 1.9.9 Add `{data_sources_section}` placeholder to `SYSTEM_PROMPT_TEMPLATE` in `deerflow/agents/lead_agent/prompt.py`
- [x] 1.9.10 Wire prompt section generation scoped by `data_tools` into `apply_prompt_template()`
- [x] 1.9.11 Write unit tests for tools (happy path, error handling, output formatting, provenance)
- [x] 1.9.12 Write unit tests for tool injection (with/without data_tools, wildcard, dedup)
- [x] 1.9.13 Write unit tests for prompt scoping (scoped, wildcard, no data_tools)

### 1.10 Capability System & Management API

- [x] 1.10.1 Add `INTEGRATION_SYSTEM = "integration_system"` to `CapabilityType` enum in `app/gateway/routers/capabilities.py`
- [x] 1.10.2 Implement `_collect_integration_systems()` collector — iterate registry, build `CapabilitySummary`
- [x] 1.10.3 Wire collector into `list_capabilities` endpoint
- [x] 1.10.4 Create `app/gateway/routers/integrations.py` with REST endpoints
- [x] 1.10.5 Implement `GET /api/tenants/{tenant_id}/integration-systems`
- [x] 1.10.6 Implement `GET /api/tenants/{tenant_id}/capability-routes`
- [x] 1.10.7 Implement `GET /api/tenants/{tenant_id}/entity-links`
- [x] 1.10.8 Implement `POST /api/tenants/{tenant_id}/integration-systems/{system_key}/health-check`
- [x] 1.10.9 Register router in Gateway app
- [x] 1.10.10 Implement tenant-scoped access control — verify `tenant_admin` can only operate on own tenant, `platform_admin` can operate on any tenant
- [x] 1.10.11 Implement structured audit logging for all write operations (POST/PUT/DELETE) on integration management endpoints
- [x] 1.10.12 Implement per-tenant rate limiting on write endpoints (10 req/min) and connectivity checks (5 req/min per system)
- [x] 1.10.13 Implement degradation strategy — auto-mark system as `degraded` after 3 consecutive health check failures, skip in fallback chains, shorter timeout for degraded primaries
- [x] 1.10.14 Write unit tests for capability collector and API endpoints
- [x] 1.10.15 Write unit tests for tenant-scoped access control, audit logging, rate limiting, and degradation

### 1.11 Pilot Agent Configuration

- [x] 1.11.1 Add `data_tools` to `monitoring-analysis` Agent `config.yaml` as pilot, including `equipment_get_overview`
- [x] 1.11.2 Write integration test: `monitoring-analysis` Agent receives integration tools (including `equipment_get_overview`) + `<data_sources>` prompt section
- [x] 1.11.3 Write integration test: `ai-report--daily` Agent (no `data_tools`) remains unchanged
- [x] 1.11.4 Write end-to-end test: `monitoring_get_trend` with InsAdapter → `TrendSeries` → formatted output
- [x] 1.11.5 Write end-to-end test: `equipment_get_overview` — composite orchestration with Ins + Sms → `AssetOverview`
- [x] 1.11.6 Write end-to-end test: enrich scenario — primary from Ins + enrich from Sms → merged result
- [x] 1.11.7 Write end-to-end test: `/api/capabilities?type=integration_system` returns Ins and Sms entries

## Phase 2: Pipeline Script Subprocess Migration (1 week, subsequent sprint)

### 2.1 CLI Subprocess Bridge

- [x] 2.1.1 Implement `deerflow/integrations/cli.py` as CLI entry point — accept `--capability` and `--params` arguments
- [x] 2.1.2 CLI instantiates service layer, routes through `CapabilityRouter`, outputs canonical model JSON to stdout
- [x] 2.1.3 CLI handles errors: outputs error JSON to stdout, exits with non-zero code
- [x] 2.1.4 Write unit tests for CLI (success path, error path, argument parsing)

### 2.2 Report Script Migration

- [x] 2.2.1 Add `USE_PLATFORM` environment variable support to `query_daily.py`
- [x] 2.2.2 Add `USE_PLATFORM` environment variable support to `query_weekly.py`
- [x] 2.2.3 Add `USE_PLATFORM` environment variable support to `query_monthly.py`
- [x] 2.2.4 When `USE_PLATFORM=true`, scripts call `subprocess.run(["python", "-m", "deerflow.integrations.cli", ...])` and parse JSON output
- [x] 2.2.5 Implement fallback: when CLI subprocess fails, log warning and retry with existing `_ins_provider.py` path
- [x] 2.2.6 Add `provider` field support to report template DSL `data_steps` — validator accepts `"platform"`, `"ins"`, `"demo"`, `"http"`
- [x] 2.2.7 Implement `USE_PLATFORM` env injection in `data_runner.py` when `provider: "platform"` is set
- [x] 2.2.8 Add deprecation warning log when `_ins_provider.py` makes direct features-tool calls
- [x] 2.2.9 Write unit tests for script platform mode (USE_PLATFORM=true, fallback, output format parity)
- [x] 2.2.10 Write unit tests for DSL `provider` field validation and `data_runner.py` env injection

### 2.3 Regression Verification

- [x] 2.3.1 Run daily report generation with `USE_PLATFORM=true` — verify output JSON matches features-tool path schema
- [x] 2.3.2 Run weekly report generation with `USE_PLATFORM=true` — verify output parity
- [x] 2.3.3 Run monthly report generation with `USE_PLATFORM=true` — verify output parity
- [x] 2.3.4 Run custom report with `provider: "platform"` in DSL `data_steps` — verify end-to-end
- [x] 2.3.5 Verify existing features-tool path works when `USE_PLATFORM` is not set

## Phase 3: Cleanup + CRM/ERP Extension (1 week, subsequent sprint)

### 3.1 Remove Direct Features-Tool Dependency

- [x] 3.1.1 Confirm all report scripts work with `USE_PLATFORM=true` in production-like environment
- [x] 3.1.2 Remove features-tool import from `_ins_provider.py` (retain `_KPI_FEATURE_MAP` local copy)
- [x] 3.1.3 Remove deprecation warning (no longer needed)
- [x] 3.1.4 Update `_ins_provider.py` docstring to note platform migration

### 3.2 CRM Adapter (see `specs/crm-erp-extension/spec.md`)

- [x] 3.2.1 Define CRM canonical models: `CustomerProfile`, `Contract`, `ServiceObject` (per spec)
- [x] 3.2.2 Implement `CrmAdapter` following same pattern as `InsAdapter`/`SmsAdapter`
- [x] 3.2.3 Add CRM capability routes to config (`customer.get_profile`, `contract.get_detail`, etc.)
- [x] 3.2.4 Add CRM tools: `customer_get_profile`, `contract_get_detail`, `service_object_get_detail`
- [x] 3.2.5 Extend `EntityLink` entity types for CRM (`customer`, `contract`, `service_object`)

### 3.3 ERP Adapter (see `specs/crm-erp-extension/spec.md`)

- [x] 3.3.1 Define ERP canonical models: `WorkOrder`, `SparePart`, `InventoryItem`, `SparePartUsage` (per spec)
- [x] 3.3.2 Implement `ErpAdapter` following same pattern
- [x] 3.3.3 Add ERP capability routes to config (`maintenance.get_work_orders`, `inventory.get_parts`, etc.)
- [x] 3.3.4 Add ERP tools: `maintenance_get_work_orders`, `maintenance_get_work_order_detail`, `inventory_get_parts`, `inventory_check_availability`
- [x] 3.3.5 Extend `EntityLink` entity types for ERP (`work_order`, `spare_part`, `inventory_item`)

### 3.4 Documentation

- [x] 3.4.1 Update `config.example.yaml` with complete `integrations` section including comments
- [x] 3.4.2 Create `docs/INTEGRATIONS.md` — architecture overview, adding a new adapter, configuration guide
- [x] 3.4.3 Update `CLAUDE.md` — add integrations module to project structure
- [x] 3.4.4 Update `backend/CLAUDE.md` — add `deerflow/integrations/` to module listing

### 3.5 Integration Testing

- [x] 3.5.1 Write end-to-end test: configure Ins + Sms, verify adapters initialize, verify health checks run
- [x] 3.5.2 Write end-to-end test: `monitoring_get_trend` with InsAdapter — verify `TrendSeries` + formatted output
- [x] 3.5.3 Write end-to-end test: `health_get_assessment` with SmsAdapter — verify `HealthAssessment` + formatted output
- [x] 3.5.4 Write end-to-end test: enrich scenario — primary Ins + enrich Sms → merged `ServiceResult`
- [x] 3.5.5 Write end-to-end test: Sms failing — verify partial result with `partial_failures` populated
- [x] 3.5.6 Write end-to-end test: system prompt injection — verify `<data_sources>` block scoped by `data_tools`
- [x] 3.5.7 Write end-to-end test: `/api/capabilities?type=integration_system` returns Ins and Sms entries
- [x] 3.5.8 Write end-to-end test: report query script with `USE_PLATFORM=true` routes through service layer CLI bridge
- [x] 3.5.9 Write end-to-end test: tenant-scoped access control — `tenant_admin` blocked from other tenant's config
- [x] 3.5.10 Write end-to-end test: degradation — system auto-degrades after 3 failures, recovers on health check success

## Rollback Strategy

- `integrations.enabled: false` in `config.yaml` → all integration tools disabled, no prompt injection, zero impact on existing Agents
- `USE_PLATFORM=false` (or unset) → report scripts use existing features-tool path
- Pipeline scripts' `_ins_provider.py` retained as fallback throughout Phase 2

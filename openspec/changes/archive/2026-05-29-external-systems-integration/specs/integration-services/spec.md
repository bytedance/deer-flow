## ADDED Requirements

### Requirement: Service layer architecture

The system SHALL provide service classes in `deerflow/integrations/services/` that offer business-oriented interfaces on top of the adapter layer. Services SHALL:

1. Accept Query Objects as parameters (not scattered parameters)
2. Call `CapabilityRouter.route()` internally to dispatch to the correct adapter
3. Return canonical models wrapped in `ServiceResult`
4. Handle entity link resolution (canonical_id → remote_id)
5. Merge enrich data from secondary systems

Services SHALL NOT directly reference any adapter class. They SHALL only depend on `CapabilityRouter`, canonical models, and query objects.

**Composite capabilities**: Some business capabilities (e.g. `asset.overview`) require data from multiple adapter calls with different `capability_key` values. In these cases, the service method SHALL orchestrate multiple `CapabilityRouter.route()` calls and assemble the composite model. The `CapabilityRouter` handles single-capability routing; the service handles cross-capability composition.

```python
class MonitoringService:
    def __init__(self, router: CapabilityRouter):
        self._router = router

    async def get_trend(self, tenant_id: str, query: TrendQuery,
                        auth_context: AuthContext | None = None
                        ) -> ServiceResult:
        return await self._router.route(
            capability_key="monitoring.trend",
            params=query,
            tenant_id=tenant_id,
            auth_context=auth_context,
        )
```

### Requirement: AssetService

`AssetService` in `deerflow/integrations/services/asset_service.py` SHALL provide:

- `get_catalog(tenant_id, query: AssetCatalogQuery, auth_context)` → `ServiceResult` containing `tuple[Asset, ...]`
- `get_context(tenant_id, query: AssetContextQuery, auth_context)` → `ServiceResult` containing `AssetContext`
- `get_overview(tenant_id, query: AssetOverviewQuery, auth_context)` → `ServiceResult` containing `AssetOverview`

`get_overview` SHALL orchestrate multiple capability calls to assemble a composite `AssetOverview`:

1. Call `asset.context` via `CapabilityRouter` for the asset's full context
2. If `query.include_health`, call `health.assessment` via `CapabilityRouter` (may route to a different system)
3. If `query.include_recent_alarms`, call `monitoring.alarm_history` via `CapabilityRouter` with `limit=query.alarm_limit`
4. Assemble results into `AssetOverview(asset=context.asset, context=context, health=health, recent_alarms=alarms)`

If any enrich call (health or alarms) fails, the failed component is set to its empty value (`None` or `()`) and the failure is recorded in `provenance.partial_failures`. The primary `asset.context` call MUST succeed.

#### Scenario: Get equipment catalog

- **WHEN** `get_catalog(tenant_id="default", query=AssetCatalogQuery(name="泵"))` is called
- **THEN** routes to `asset.catalog` capability
- **THEN** returns `ServiceResult` with `tuple[Asset, ...]`

#### Scenario: Get equipment context

- **WHEN** `get_context(tenant_id="default", query=AssetContextQuery(asset_id="asset:001"))` is called
- **THEN** routes to `asset.context` capability
- **THEN** returns `ServiceResult` with `AssetContext` containing the asset, its children, measurement points, and related assets

#### Scenario: Get equipment overview with all data

- **WHEN** `get_overview(tenant_id="default", query=AssetOverviewQuery(asset_id="asset:001"))` is called
- **THEN** routes `asset.context` to `ins_prod` → `AssetContext`
- **THEN** routes `health.assessment` to `sms_prod` → `HealthAssessment`
- **THEN** routes `monitoring.alarm_history` to `ins_prod` → `tuple[AlarmEvent, ...]` (last 5)
- **THEN** returns `ServiceResult` with `AssetOverview(asset=..., context=..., health=..., recent_alarms=...)`
- **THEN** `provenance.source_system="ins_prod"` (primary), enrich systems recorded

#### Scenario: Get equipment overview with Sms unavailable

- **WHEN** `get_overview` is called but `sms_prod` health check fails
- **THEN** `AssetContext` and alarm history are still fetched from Ins
- **THEN** `AssetOverview.health` is `None`
- **THEN** `provenance.partial_failures` contains `PartialFailure(system="sms_prod", reason="unavailable")`
- **THEN** the `ServiceResult` is returned successfully (not an error)

### Requirement: MonitoringService

`MonitoringService` in `deerflow/integrations/services/monitoring_service.py` SHALL provide:

- `get_trend(tenant_id, query: TrendQuery, auth_context)` → `ServiceResult` containing `TrendSeries`
- `get_waveform(tenant_id, query: WaveformQuery, auth_context)` → `ServiceResult` containing `WaveformPayload`
- `get_orbit(tenant_id, query: OrbitQuery, auth_context)` → `ServiceResult` containing `OrbitPayload`
- `get_alarm_history(tenant_id, query: AlarmHistoryQuery, auth_context)` → `ServiceResult` containing `tuple[AlarmEvent, ...]`

#### Scenario: Get trend data

- **WHEN** `get_trend(tenant_id="default", query=TrendQuery(asset_id="asset:001", metric_key="vibration_level"))` is called
- **THEN** routes to `monitoring.trend` capability
- **THEN** returns `ServiceResult` with `TrendSeries`

#### Scenario: Get waveform data

- **WHEN** `get_waveform(tenant_id="default", query=WaveformQuery(asset_id="asset:001", point_id="point:001"))` is called
- **THEN** routes to `monitoring.waveform` capability
- **THEN** returns `ServiceResult` with `WaveformPayload`

#### Scenario: Get orbit data

- **WHEN** `get_orbit(tenant_id="default", query=OrbitQuery(asset_id="asset:001", bearing_id="bearing:DE"))` is called
- **THEN** routes to `monitoring.orbit` capability
- **THEN** returns `ServiceResult` with `OrbitPayload`

#### Scenario: Get alarm history

- **WHEN** `get_alarm_history(tenant_id="default", query=AlarmHistoryQuery(asset_id="asset:001", limit=20))` is called
- **THEN** routes to `monitoring.alarm_history` capability
- **THEN** returns `ServiceResult` with `tuple[AlarmEvent, ...]`

### Requirement: AssessmentService

`AssessmentService` in `deerflow/integrations/services/assessment_service.py` SHALL provide:

- `get_health_assessment(tenant_id, query: HealthAssessmentQuery, auth_context)` → `ServiceResult` containing `HealthAssessment`
- `get_anomaly_statistics(tenant_id, params: dict, auth_context)` → `ServiceResult` containing `AnomalyStats`
- `get_risk_ranking(tenant_id, params: dict, auth_context)` → `ServiceResult` containing `RiskRanking`

#### Scenario: Get health assessment

- **WHEN** `get_health_assessment(tenant_id="default", query=HealthAssessmentQuery(asset_id="asset:001"))` is called
- **THEN** routes to `health.assessment` capability
- **THEN** returns `ServiceResult` with `HealthAssessment`

#### Scenario: Get anomaly statistics

- **WHEN** `get_anomaly_statistics(tenant_id="default", params={"asset_id": "asset:001", "time_range": "30d"})` is called
- **THEN** routes to `health.anomaly_statistics` capability
- **THEN** returns `ServiceResult` with `AnomalyStats`

#### Scenario: Get risk ranking

- **WHEN** `get_risk_ranking(tenant_id="default", params={"period": "7d", "limit": 10})` is called
- **THEN** routes to `health.risk_ranking` capability
- **THEN** returns `ServiceResult` with `RiskRanking`

## ADDED Requirements

### Requirement: Canonical data models

The system SHALL define frozen dataclasses in `deerflow/integrations/models/` as the platform's unified data models. All adapters SHALL transform system-specific responses into these models. Services SHALL return these models. Tools SHALL format these models for Agent consumption.

All models SHALL use `@dataclass(frozen=True)` to enforce immutability. All models SHALL include a `source_metadata: dict[str, Any]` field for adapter-specific raw fields that do not belong in the canonical contract. All models SHALL include a `provenance: Provenance` field for data lineage tracking.

External system fields SHALL NOT be promoted to canonical model core fields. System-specific data SHALL be stored in `source_metadata` or `provenance.adapter_debug`.

**Asset models** (`deerflow/integrations/models/asset.py`):

```python
@dataclass(frozen=True)
class Asset:
    id: str                        # platform unified ID, e.g. "asset:241212010001718"
    name: str                      # short code, e.g. "P-101A"
    display_name: str              # human-readable, e.g. "P-101A 原料泵"
    kind: str                      # platform enum: "pump", "rotating_machine", "static_equipment"
    subtype: str | None            # e.g. "centrifugal_pump"
    area: str | None               # e.g. "常减压装置"
    location: str | None           # e.g. "2#泵区"
    status: str                    # "active", "stopped", "maintenance"
    tags: tuple[str, ...]          # e.g. ("rotating", "critical")
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class MeasurementPoint:
    id: str                        # platform unified ID, e.g. "point:703030976116162560"
    asset_id: str                  # reference to parent Asset.id
    name: str                      # e.g. "驱动端水平振动"
    point_type: str                # e.g. "vibration", "temperature", "speed"
    unit: str                      # e.g. "mm/s", "°C"
    endpoint_series: str | None    # e.g. "2k", "6k", "8k", "9k"
    position_type: str | None      # Ins-specific position code
    alarm_thresholds: dict[str, float]  # e.g. {"B": 3.0, "C": 4.5, "D": 6.0}
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class AssetContext:
    asset: Asset
    children: tuple[Asset, ...]
    points: tuple[MeasurementPoint, ...]
    related_assets: tuple[Asset, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance
```

**Monitoring models** (`deerflow/integrations/models/monitoring.py`):

```python
@dataclass(frozen=True)
class TrendSeries:
    series_id: str                 # e.g. "trend:asset:241212010001718:pp_value"
    asset_id: str
    point_id: str
    metric_key: str                # e.g. "vibration_level", "temperature"
    display_name: str              # e.g. "振动水平"
    unit: str                      # e.g. "mm/s"
    aggregation: str               # e.g. "hourly", "daily", "raw"
    time_range: TimeRange
    samples: tuple[TrendPoint, ...]
    statistics: TrendStatistics | None
    anomalies: tuple[dict[str, Any], ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class TimeRange:
    start: str                     # ISO 8601
    end: str                       # ISO 8601

@dataclass(frozen=True)
class TrendPoint:
    ts: str                        # ISO 8601
    value: float
    quality: str | None            # "good", "suspect", "bad"

@dataclass(frozen=True)
class TrendStatistics:
    min: float
    max: float
    avg: float
    stddev: float | None

@dataclass(frozen=True)
class WaveformPayload:
    asset_id: str
    point_id: str
    sample_rate: float             # Hz
    captured_at: str               # ISO 8601
    wave_x: tuple[float, ...]      # time axis
    wave_y: tuple[float, ...]      # amplitude axis
    spec_x: tuple[float, ...]      # frequency axis
    spec_y: tuple[float, ...]      # spectrum amplitude
    speed_rpm: float | None        # rotational speed at capture time
    unit: str                      # e.g. "mm/s"
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class OrbitPayload:
    asset_id: str
    bearing_id: str                # e.g. "bearing:DE"
    captured_at: str               # ISO 8601
    probe_ids: tuple[str, ...]     # e.g. ("point:x", "point:y")
    points: tuple[tuple[float, float], ...]      # raw orbit coordinates
    points_1x: tuple[tuple[float, float], ...]   # 1X filtered
    points_2x: tuple[tuple[float, float], ...]   # 2X filtered
    speed_rpm: float | None
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class AlarmEvent:
    id: str                        # e.g. "alarm:ins_prod:10001"
    asset_id: str
    point_id: str | None
    event_type: str                # e.g. "alarm", "trip", "alert"
    severity: str                  # "critical", "high", "warning", "info"
    title: str                     # e.g. "主报警"
    message: str                   # e.g. "驱动端振动超阈值"
    started_at: str                # ISO 8601
    ended_at: str | None           # ISO 8601, None if still active
    duration_seconds: float | None
    source_metadata: dict[str, Any]
    provenance: Provenance
```

**Assessment models** (`deerflow/integrations/models/assessment.py`):

```python
@dataclass(frozen=True)
class HealthAssessment:
    asset_id: str
    assessment_time: str           # ISO 8601
    overall_score: float           # 0-100
    level: str                     # e.g. "medium_risk", or "优"/"良"/"中"/"差"
    summary: str                   # human-readable summary
    dimensions: dict[str, float]   # e.g. {"vibration": 74.0, "temperature": 88.0}
    risk_items: tuple[RiskItem, ...]
    recommendations: tuple[str, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class RiskItem:
    code: str                      # e.g. "vibration_uptrend"
    severity: str                  # "critical", "high", "medium", "low"
    message: str                   # e.g. "驱动端振动近 7 日持续升高"

@dataclass(frozen=True)
class AnomalyStats:
    asset_id: str | None           # None = global
    period: str
    total_count: int
    by_type: dict[str, int]
    trend: tuple[dict[str, Any], ...]
    top_equipment: tuple[dict[str, Any], ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class RiskRanking:
    period: str
    rankings: tuple[EquipmentRisk, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class EquipmentRisk:
    asset_id: str
    risk_score: float
    level: str
    top_risk_items: tuple[str, ...]
```

**Composite models** (`deerflow/integrations/models/overview.py`):

```python
@dataclass(frozen=True)
class AssetOverview:
    asset: Asset
    context: AssetContext
    health: HealthAssessment | None
    recent_alarms: tuple[AlarmEvent, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance
```

`AssetOverview` is a composite model assembled by the `CapabilityRouter` from multiple system responses (primary + enrich). The `health` field is `None` when the Sms enrich source is unavailable or not configured. `recent_alarms` contains the latest alarm events from Ins (typically last 5).

**Cross-system models** (`deerflow/integrations/models/provenance.py`):

```python
@dataclass(frozen=True)
class Provenance:
    source_system: str             # e.g. "ins_prod"
    capability_key: str            # e.g. "monitoring.trend"
    fetched_at: str                # ISO 8601
    partial_failures: tuple[PartialFailure, ...]

@dataclass(frozen=True)
class PartialFailure:
    system: str
    reason: str
```

For aggregation scenarios, `Provenance` carries both primary and enrich system info:

- Single-source: `source_system="ins_prod"`, `partial_failures=()`
- Aggregation: `source_system="ins_prod"` (primary), `partial_failures` lists failed enrich systems

**Query objects** (`deerflow/integrations/models/queries.py`):

```python
@dataclass(frozen=True)
class AssetOverviewQuery:
    asset_id: str
    include_health: bool = True
    include_recent_alarms: bool = True
    alarm_limit: int = 5

@dataclass(frozen=True)
class AssetCatalogQuery:
    name: str | None = None
    kind: str | None = None
    area: str | None = None
    limit: int = 100
    offset: int = 0

@dataclass(frozen=True)
class AssetContextQuery:
    asset_id: str
    include_children: bool = True
    include_points: bool = True
    include_related: bool = False

@dataclass(frozen=True)
class TrendQuery:
    asset_id: str
    point_id: str | None = None
    metric_key: str | None = None
    time_range: TimeRange | None = None
    aggregation: str = "hourly"

@dataclass(frozen=True)
class WaveformQuery:
    asset_id: str
    point_id: str
    captured_at: str | None = None  # ISO 8601, None = latest

@dataclass(frozen=True)
class OrbitQuery:
    asset_id: str
    bearing_id: str
    captured_at: str | None = None  # ISO 8601, None = latest

@dataclass(frozen=True)
class AlarmHistoryQuery:
    asset_id: str | None = None
    limit: int = 50
    time_range: TimeRange | None = None
    severity_min: str | None = None  # "info", "warning", "high", "critical"

@dataclass(frozen=True)
class HealthAssessmentQuery:
    asset_id: str
    window: str = "7d"             # e.g. "7d", "30d"
```

#### Scenario: Model immutability

- **WHEN** a `TrendSeries` instance is created
- **THEN** attempting to modify any field raises `FrozenInstanceError`

#### Scenario: Model provenance

- **WHEN** any canonical model is created
- **THEN** `provenance.source_system` identifies which adapter produced it
- **THEN** `provenance.fetched_at` is a valid ISO 8601 timestamp
- **THEN** `provenance.capability_key` identifies which capability produced it

#### Scenario: source_metadata isolates system-specific fields

- **WHEN** `InsAdapter` transforms an Ins API response to `AlarmEvent`
- **THEN** Ins-specific fields like `raw_event_type` are stored in `source_metadata`
- **THEN** canonical fields (`id`, `severity`, `message`) use platform-standard values

#### Scenario: AssetContext aggregation

- **WHEN** `AssetContext` is returned for equipment "P-101A"
- **THEN** `asset` contains the primary `Asset` record
- **THEN** `children` contains sub-equipment (e.g. motor, gearbox)
- **THEN** `points` contains all `MeasurementPoint` records for this asset
- **THEN** `related_assets` contains peer or parent equipment (if requested)

#### Scenario: Query object usage

- **WHEN** `MonitoringService.get_trend(tenant_id, TrendQuery(asset_id="asset:001", metric_key="vibration_level", aggregation="hourly"))` is called
- **THEN** the service passes the `TrendQuery` to the adapter (not scattered parameters)
- **THEN** the adapter uses query fields to construct the system-specific request

#### Scenario: Provenance with enrich partial failure

- **WHEN** `asset.overview` route has primary=`ins_prod`, enrich=`[sms_prod, erp_prod]`
- **WHEN** `sms_prod` enrich succeeds but `erp_prod` enrich fails with timeout
- **THEN** returned `Provenance` has `source_system="ins_prod"`
- **THEN** `partial_failures` contains `PartialFailure(system="erp_prod", reason="timeout")`

#### Scenario: AssetOverview aggregation

- **WHEN** `asset.overview` route has primary=`ins_prod`, enrich=`[sms_prod]`
- **THEN** `AssetOverview` is assembled from Ins `AssetContext` (primary) and Sms `HealthAssessment` (enrich)
- **THEN** `overview.asset` contains the canonical `Asset` record
- **THEN** `overview.context` contains children, measurement points, related assets
- **THEN** `overview.health` contains the Sms health assessment (or `None` if Sms enrich failed)
- **THEN** `overview.recent_alarms` contains latest alarm events from Ins
- **THEN** `provenance.source_system` reflects the primary system (`"ins_prod"`)
- **THEN** `provenance.partial_failures` lists any failed enrich systems

#### Scenario: TrendStatistics populated

- **WHEN** a `TrendSeries` is returned with sufficient data points
- **THEN** `statistics` is a `TrendStatistics` with `min`, `max`, `avg` computed from `samples`
- **THEN** `statistics.stddev` is computed if at least 2 samples exist, else `None`

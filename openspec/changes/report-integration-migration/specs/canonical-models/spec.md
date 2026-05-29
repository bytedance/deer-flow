# Canonical Models - Batch Query Support

## MODIFIED Requirements

### Requirement: Canonical query objects support batch parameters

The system SHALL extend existing query objects in `deerflow/integrations/models/queries.py` to support multi-equipment batch queries. This benefits not only reports but also dashboards and analysis agents.

`TrendQuery` SHALL add two optional fields:

```python
@dataclass(frozen=True)
class TrendQuery:
    tenant_id: str
    asset_id: str | None = None              # single equipment (backward compatible)
    measurement_point_id: str | None = None   # single point (backward compatible)
    equipment_ids: tuple[str, ...] = ()       # multi-equipment batch (NEW)
    eq_type: str = "all"                      # equipment type filter (NEW)
    start_time: datetime | None = None
    end_time: datetime | None = None
    aggregation: str = "avg"
    sample_interval: str = "1h"
```

`AlarmHistoryQuery` SHALL add the same optional batch fields:

```python
@dataclass(frozen=True)
class AlarmHistoryQuery:
    tenant_id: str
    asset_id: str | None = None
    equipment_ids: tuple[str, ...] = ()       # multi-equipment batch (NEW)
    eq_type: str = "all"                      # equipment type filter (NEW)
    start_time: datetime | None = None
    end_time: datetime | None = None
    severity: str | None = None
    limit: int = 1000
```

When `equipment_ids` is non-empty, the adapter SHALL fetch data for all specified equipment in a single call, returning a combined result. When empty, behavior is identical to the existing single-`asset_id` path (backward compatible).

#### Scenario: Backward compatible single-equipment query

- **WHEN** `TrendQuery(tenant_id="default", asset_id="E1", start_time=..., end_time=...)` is used
- **THEN** behavior is identical to the current implementation
- **THEN** `equipment_ids` defaults to `()` and is ignored

#### Scenario: Batch multi-equipment trend query

- **WHEN** `TrendQuery(tenant_id="default", equipment_ids=("E1", "E2", "E3"), eq_type="rotating_machinery", start_time=..., end_time=...)` is used
- **THEN** the adapter fetches trend data for all three equipment in a single call
- **THEN** the returned `TrendSeries` contains data points from all equipment, distinguishable by `source_metadata`

#### Scenario: Empty equipment_ids ignored

- **WHEN** `TrendQuery(tenant_id="default", asset_id="E1", equipment_ids=(), start_time=..., end_time=...)` is used
- **THEN** the adapter uses `asset_id` as before
- **THEN** the result is identical to omitting `equipment_ids` entirely

#### Scenario: Both asset_id and equipment_ids provided

- **WHEN** `TrendQuery(tenant_id="default", asset_id="E1", equipment_ids=("E2", "E3"), start_time=..., end_time=...)` is used
- **THEN** `equipment_ids` takes precedence over `asset_id`
- **THEN** the adapter fetches data for E2 and E3 only

# InS KPI Aggregator Module

## ADDED Requirements

### Requirement: KPI aggregator pure function module

The system SHALL provide `kpi_aggregator.py` in `deerflow/integrations/adapters/ins/` containing pure functions that aggregate raw InS trend rows into KPI scalar values. The module SHALL be extracted from the legacy `_ins_provider.py` with identical logic.

The aggregator SHALL support these derivation methods:

- `mean` — arithmetic mean of non-null values
- `max` — maximum of non-null values
- `runtime_rate` — fraction of speed > 0 samples
- `downtime_count` — count of speed > 0 → 0 falling edges
- `alarm_count` — count of values exceeding the point's alarm threshold (tier B/C/D)
- `thickness_loss` — difference between first and last thickness reading

All aggregation functions SHALL be pure (no side effects, no I/O). All SHALL accept a list of trend rows and return a single scalar or None.

#### Scenario: Mean aggregation

- **WHEN** `aggregate_trend_to_kpi(rows, "vibration_level", point_meta=None)` is called with 10 rows containing `pp_value` values [1.0, 2.0, 3.0, ..., 10.0]
- **THEN** the function returns `5.5` (arithmetic mean)

#### Scenario: Runtime rate aggregation

- **WHEN** `aggregate_trend_to_kpi(rows, "runtime_rate", point_meta=None)` is called with 100 speed rows where 80 have speed > 0
- **THEN** the function returns `0.8`

#### Scenario: Alarm count with threshold

- **WHEN** `aggregate_trend_to_kpi(rows, "alarm_count", point_meta={"alarm_thresholds": {"pp_value": {"C": 4.5}}})` is called with 10 rows where 3 exceed 4.5
- **THEN** the function returns `3`

#### Scenario: Empty input

- **WHEN** `aggregate_trend_to_kpi([], "vibration_level", point_meta=None)` is called
- **THEN** the function returns `None`

### Requirement: Hourly runtime rate bucketing

The system SHALL provide `hourly_runtime_rate(rows)` in `kpi_aggregator.py` that buckets speed > 0 ratios into 24 hourly slots (0–23). Each bucket's value is the fraction of speed > 0 samples in that hour. Empty hours return 0.0.

#### Scenario: Full day data

- **WHEN** `hourly_runtime_rate(rows)` is called with speed rows spanning 24 hours
- **THEN** the function returns a list of 24 floats, each between 0.0 and 1.0

#### Scenario: Partial day data

- **WHEN** `hourly_runtime_rate(rows)` is called with speed rows only for hours 8–17
- **THEN** hours 0–7 and 18–23 return 0.0
- **THEN** hours 8–17 return the actual speed > 0 fraction

### Requirement: Point selection for KPI

The system SHALL provide `select_points_for_kpi(components, kpi_key, eq_type)` in `kpi_aggregator.py` that walks the slim component tree and returns points matching the KPI's `_KPI_FEATURE_MAP` entry. Selection SHALL filter by `position_type`, `endpoint_series`, and optional `name_keywords`.

The function SHALL use `kpi_map.py` as the single source of truth for `_KPI_FEATURE_MAP`.

#### Scenario: Select vibration points for pump

- **WHEN** `select_points_for_kpi(components, "vibration_velocity_rms", eq_type="pump")` is called
- **THEN** returns points with `position_type` in range(23, 31) and `endpoint_series == "2k"`

#### Scenario: Select rotating machinery points

- **WHEN** `select_points_for_kpi(components, "vibration_level", eq_type="rotating_machinery")` is called
- **THEN** returns points with `position_type` in range(81, 84) and `endpoint_series == "8k"`

### Requirement: Multi-equipment KPI aggregation

The system SHALL provide `aggregate_equipment_kpis(trend_data, equipment_ids, kpi_keys, eq_type)` in `kpi_aggregator.py` that aggregates KPIs from pre-fetched trend data for multiple equipment.

The function SHALL:

1. Accept trend data already fetched by the caller (the function itself is pure — no I/O)
2. Select matching points per KPI from the provided component metadata
3. Aggregate per-point then per-equipment
4. Return per-equipment KPI dicts and union speed rows for hourly calculation

#### Scenario: Three equipment daily KPI

- **WHEN** `aggregate_equipment_kpis(trend_data, ["E1", "E2", "E3"], ["runtime_rate", "alarm_count"], "rotating_machinery")` is called
- **THEN** returns a dict with per-equipment KPI values and a list of union speed rows
- **THEN** each equipment's `runtime_rate` is independently calculated
- **THEN** `alarm_count` is summed across equipment

### Requirement: Helper functions ported from legacy provider

The system SHALL port the following helper functions from `_ins_provider.py` to `kpi_aggregator.py`:

- `_row_value(row, feature)` — extract a numeric value from a trend row
- `_row_first_value(row, feature)` — extract the first non-null value
- `_row_time_ms(row)` — extract timestamp in milliseconds
- `_resolve_alarm_threshold(point_meta, feature)` — resolve B/C/D alarm tier for a point

All helpers SHALL maintain identical behavior to the legacy implementation.

#### Scenario: Row value extraction

- **WHEN** `_row_value({"pp_value": 3.14, "rms_value": 1.5}, "pp_value")` is called
- **THEN** returns `3.14`

#### Scenario: Alarm threshold resolution

- **WHEN** `_resolve_alarm_threshold({"alarm_thresholds": {"pp_value": {"B": 2.0, "C": 4.5, "D": 7.0}}}, "pp_value")` is called
- **THEN** returns `{"B": 2.0, "C": 4.5, "D": 7.0}`

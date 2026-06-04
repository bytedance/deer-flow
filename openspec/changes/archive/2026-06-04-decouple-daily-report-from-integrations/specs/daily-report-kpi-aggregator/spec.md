## ADDED Requirements

### Requirement: Self-contained KPI aggregation module

`_kpi_aggregator.py` SHALL be a standalone module in `skills/custom/daily-report/scripts/` containing pure functions for computing KPI scalars and hourly runtime rates from pre-fetched trend rows. It SHALL NOT import from `deerflow.integrations` or perform any I/O.

The module SHALL export:

- `aggregate_trend_to_kpi(rows, kpi_key, point_meta=None)` → `float | int | None`
- `hourly_runtime_rate(rows)` → `list[float]` (24 elements)
- `aggregate_equipment_kpis(trend_data_by_equipment, kpi_keys, point_metadata)` → `tuple[dict, list]`
- `compute_hourly_runtime_rate(union_speed_rows)` → `list[float]`

#### Scenario: Runtime rate computation

- **WHEN** `aggregate_trend_to_kpi(rows, "runtime_rate")` is called with trend rows containing `speed` values
- **THEN** it returns a float between 0.0 and 1.0 representing the fraction of samples where speed > 0

#### Scenario: Downtime count computation

- **WHEN** `aggregate_trend_to_kpi(rows, "downtime_count")` is called with trend rows where speed drops from >0 to 0 three times
- **THEN** it returns `3`

#### Scenario: Mean derivation

- **WHEN** `aggregate_trend_to_kpi(rows, "vibration_level")` is called with rows containing `pp_value` feature
- **THEN** it returns the arithmetic mean of all non-null `pp_value` values, rounded to 4 decimal places

#### Scenario: Alarm count with threshold

- **WHEN** `aggregate_trend_to_kpi(rows, "alarm_count", point_meta={"alarm_thresholds": {"pp_value": {"C": 7.1}}})` is called
- **THEN** it returns the count of rows where `pp_value` exceeds 7.1

#### Scenario: Hourly runtime rate produces 24 buckets

- **WHEN** `hourly_runtime_rate(rows)` is called with timestamped speed rows
- **THEN** it returns a list of exactly 24 floats, each representing the runtime rate for that hour (0.0 if no data)

#### Scenario: Unknown KPI key raises ValueError

- **WHEN** `aggregate_trend_to_kpi(rows, "nonexistent_kpi")` is called
- **THEN** `ValueError` is raised with a message indicating the KPI key is unmappable

### Requirement: KPI feature map is self-contained

The module SHALL contain its own `KPI_FEATURE_MAP` dictionary mapping KPI keys to their feature names, derivation methods, and optional config (value_scale, alarm_tier, feature_aliases). This map SHALL cover all KPI keys used by daily reports:

- `runtime_rate` → feature `speed`, derivation `runtime_rate`
- `downtime_count` → feature `speed`, derivation `downtime_count`
- `alarm_count` → feature `pp_value`, derivation `alarm_count`, alarm_tier `C`, feature_aliases `["v_rms"]`
- `corrosion_rate` → feature `thickness`, derivation `mean`, value_scale varies
- `thickness_loss` → feature `thickness`, derivation `thickness_loss`
- `vibration_level` → feature `pp_value`, derivation `mean`
- `bearing_temp` → feature `temperature`, derivation `mean`
- `valve_temp` → feature `temperature`, derivation `mean`
- `vibration_velocity_rms` → feature `v_rms`, derivation `mean`
- `vibration_acceleration_peak` → feature `a_peak`, derivation `mean`
- `kurtosis_index` → feature `kurtosis`, derivation `mean`

#### Scenario: All daily report KPI keys are mappable

- **WHEN** `aggregate_trend_to_kpi(rows, kpi_key)` is called for each of `runtime_rate`, `downtime_count`, `alarm_count`, `corrosion_rate`, `thickness_loss`, `vibration_level`, `bearing_temp`, `valve_temp`, `vibration_velocity_rms`, `vibration_acceleration_peak`, `kurtosis_index`
- **THEN** no `ValueError` is raised for any of them

### Requirement: Multi-equipment batch aggregation

`aggregate_equipment_kpis(trend_data_by_equipment, kpi_keys, point_metadata)` SHALL accept a dict of `{equipment_id: [trend_rows]}` and return a tuple of `(kpis_by_equipment, union_speed_rows)` where `kpis_by_equipment` is `{equipment_id: {kpi_key: value}}` and `union_speed_rows` is the concatenation of all speed rows for subsequent hourly computation.

#### Scenario: Batch aggregation across multiple equipment

- **WHEN** `aggregate_equipment_kpis({"E001": [...rows...], "E002": [...rows...]}, ["runtime_rate", "vibration_level"], {})` is called
- **THEN** the result contains KPI dicts for both E001 and E002, each with `runtime_rate` and `vibration_level` values

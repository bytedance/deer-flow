## ADDED Requirements

### Requirement: Daily report scripts directly access InS via features-tool

`_ins_client.py` SHALL provide a thin wrapper around `features-tool`'s `InsApiClient` that exposes the following interface for daily report data access:

- `fetch_trend_data(equipment_ids, start_time, end_time, eq_type)` → `dict[str, list[dict]]` — fetches trend time-series rows for one or more pieces of equipment, returning `{equipment_id: [row, ...]}`. Each row SHALL contain `time_ms`, `time`, and `values` (feature → value mapping).
- `fetch_alarm_events(equipment_ids, start_time, end_time, eq_type)` → `list[dict]` — fetches machine drop/alarm events. Returns `[{time, equipment, level, message}]`.
- `is_available()` → `bool` — returns `True` if `features-tool` is importable and the InS client can be constructed.

The wrapper SHALL handle the 2k/6k/8k/9k endpoint series routing based on `eq_type` using the same `ENDPOINT_SERIES_BY_EQ_TYPE` mapping as the integrations InS adapter.

#### Scenario: Features-tool available in sandbox

- **WHEN** `_ins_client.is_available()` is called inside the sandbox container where `/opt/features-tool` exists
- **THEN** it returns `True`

#### Scenario: Features-tool unavailable produces clear error

- **WHEN** `_ins_client.is_available()` is called outside the sandbox without `features-tool` on `sys.path`
- **THEN** it returns `False` and `_ins_client.get_availability_reason()` returns a human-readable string explaining why

#### Scenario: Fetch trend data for rotating machinery

- **WHEN** `fetch_trend_data(equipment_ids=["E001"], start_time="2026-06-01T00:00:00", end_time="2026-06-01T23:59:59", eq_type="rotating_machinery")` is called
- **THEN** each equipment's component tree is queried, 8k-series measurement points are selected, and trend rows are returned with `pp_value`, `speed`, and `value` features

#### Scenario: Fetch trend data for pump

- **WHEN** `fetch_trend_data(equipment_ids=["P001"], ..., eq_type="pump")` is called
- **THEN** 2k-series measurement points are selected and trend rows are returned with vibration features (`v_rms`, `a_peak`, `kurtosis`)

#### Scenario: Alarm fetch for rotating machinery returns real events

- **WHEN** `fetch_alarm_events(equipment_ids=["E001"], start_time="...", end_time="...", eq_type="rotating_machinery")` is called
- **THEN** it returns a list of alarm events with `time`, `equipment`, `level`, `message` fields sourced from `getMachineDrops`

#### Scenario: Alarm fetch failure returns empty list

- **WHEN** `fetch_alarm_events(...)` fails due to a network error
- **THEN** it returns `[]` and logs the error — the KPI data fetch is not affected

### Requirement: PlatformDailyProvider uses direct InS access instead of subprocess bridge

`_data_providers.py`'s `PlatformDailyProvider.fetch()` SHALL use `_ins_client` for trend/alarm data and `_kpi_aggregator` for KPI computation, instead of calling `_platform_bridge.call_capability()` / `call_action()`.

The `ProviderResult` returned SHALL have `data_source="ins"` on success. On any `_ins_client` or aggregation failure, `HttpProviderError` SHALL be raised with a descriptive message.

#### Scenario: Successful fetch via direct InS access

- **WHEN** `PlatformDailyProvider.fetch(date_str="2026-06-01", equipment_ids=["E001"], kpi_keys=["runtime_rate", "alarm_count"], eq_type="rotating_machinery")` is called
- **THEN** the result contains `kpis` (computed via `_kpi_aggregator`), `hourly_runtime_rate` (24 floats), and `alarms` (list of alarm events), with `data_source="ins"`

#### Scenario: InS unavailable raises HttpProviderError

- **WHEN** `PlatformDailyProvider.fetch(...)` is called and `_ins_client.is_available()` returns `False`
- **THEN** `HttpProviderError` is raised with the availability reason in the message

#### Scenario: Trend data empty for unknown equipment

- **WHEN** `fetch(...)` is called with an equipment ID that exists in the org tree but has no InS measurement points
- **THEN** KPIs are computed as `None` for each key and `hourly_runtime_rate` is all zeros — no error is raised

### Requirement: _platform_bridge.py is removed

The file `skills/custom/daily-report/scripts/_platform_bridge.py` SHALL be removed. All imports of `_platform_bridge` in the daily-report scripts SHALL be removed. No other module in the project imports from `_platform_bridge`.

#### Scenario: No remaining platform_bridge imports

- **WHEN** a recursive grep for `_platform_bridge` is run across the project
- **THEN** zero matches are found

### Requirement: Output JSON schema unchanged

`query_daily.py`'s output (`daily_data.json`) SHALL maintain the exact same structure as before:

```json
{
  "report_date": "2026-06-01",
  "equipment_ids": ["E001"],
  "equipment_names": {},
  "kpi_keys": ["runtime_rate", "downtime_count", "alarm_count"],
  "compare_type": "previous_day",
  "compare_date": "2026-05-31",
  "current": {
    "kpis": {"runtime_rate": 0.95, ...},
    "kpi_units": {"runtime_rate": "%", ...},
    "hourly_runtime_rate": [0.0, ...],
    "alarms": [...],
    "per_equipment": {...}
  },
  "compare": {...},
  "data_source": "ins",
  "data_notes": []
}
```

#### Scenario: Output matches previous schema

- **WHEN** `query_daily.py` completes successfully with the new direct InS access
- **THEN** the output JSON has the same keys, types, and structure as the previous subprocess-bridge-based output

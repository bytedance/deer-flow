# Report Script Platform Bridge - Full Implementation

## ADDED Requirements

### Requirement: Builtin report templates declare provider platform

All builtin report template YAML files that fetch InS data SHALL include `provider: platform` on their `data_steps` entries. The templates covered are:
- `daily-equipment/default.yaml`
- `weekly-equipment/default.yaml`
- `monthly-equipment/default.yaml`
- `trend-equipment/default.yaml`
- `diagnosis-fault/default.yaml`

#### Scenario: Daily equipment template uses platform provider

- **WHEN** the `daily-equipment` builtin template is loaded by the validator
- **THEN** its `data_steps[0].provider` equals `"platform"`
- **THEN** the template passes validation

#### Scenario: All five builtin templates declare provider platform

- **WHEN** `pytest backend/tests/test_builtin_report_templates.py` runs
- **THEN** all five templates (daily-equipment, weekly-equipment, monthly-equipment, trend-equipment, diagnosis-fault) pass validation with `provider: platform` on their InS data steps

### Requirement: Platform bridge data transformation returns real values

The `_transform_canonical_to_script_shape()` function in `query_*.py` SHALL map capability + action outputs to the script-expected structure with actual KPI values. It SHALL NOT return all-None KPI dictionaries or all-zero hourly arrays. Expected behavior:

- `kpis` dict maps each requested KPI key to its computed scalar value
- `hourly_runtime_rate` contains 24 float values from the action's `aggregate_equipment_kpis` output
- `alarms` list is populated from `monitoring.alarm_history` capability call
- `per_equipment` dict (when `include_per_equipment=True`) maps each equipment ID to its per-device KPIs

#### Scenario: Daily report transformation produces non-null KPIs

- **WHEN** `_fetch_day_via_platform()` processes capability + action output for equipment `["E1", "E2"]` with KPIs `["runtime_rate", "alarm_count"]`
- **THEN** the returned dict has `kpis.runtime_rate` as a non-None float and `kpis.alarm_count` as a non-None integer

#### Scenario: Hourly runtime rate has 24 non-zero values

- **WHEN** `_fetch_day_via_platform()` processes valid trend data
- **THEN** `hourly_runtime_rate` is a list of 24 floats, not all zeros

### Requirement: Report scripts use capability + action two-step

When `USE_PLATFORM=true` is set in the environment, `query_daily.py`, `query_weekly.py`, and `query_monthly.py` SHALL use the two-step platform bridge path:

1. Call `call_capability("monitoring.trend", {...})` for raw trend data
2. Call `call_action("aggregate_kpi", adapter="ins_prod", {...})` for KPI computation
3. The script assembles the report structure (current + compare + output JSON)

#### Scenario: Daily report two-step platform bridge

- **WHEN** `query_daily.py` is invoked with `USE_PLATFORM=true` and `--date 2026-06-01 --equipment E1,E2`
- **THEN** `call_capability("monitoring.trend", ...)` is invoked for raw data
- **THEN** `call_action("aggregate_kpi", ...)` is invoked for KPI computation
- **THEN** output JSON has the same schema as the integrations path (report_date, equipment_ids, kpi_keys, current, compare, data_source, data_notes)

#### Scenario: Platform bridge path is the only active path

- **WHEN** `USE_PLATFORM=true` is set
- **THEN** the script does NOT import or invoke `_ins_provider` or `_data_provider_impls` for InS data

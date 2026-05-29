# Report Script Platform Bridge - Two-Step Orchestration

## MODIFIED Requirements

### Requirement: Report scripts use two-step platform bridge

The system SHALL update `query_daily.py`, `query_weekly.py`, and `query_monthly.py` to use a two-step platform bridge path when `USE_PLATFORM=true` is set:

1. **Step 1 — Capability call**: Fetch raw data via `monitoring.trend` and `monitoring.alarm_history` capability keys
2. **Step 2 — Action call**: Aggregate raw data into KPIs via CLI `--action aggregate_kpi`
3. **Step 3 — Script assembly**: The script itself assembles the report structure (current + compare + output JSON)

The script SHALL NOT call any `report.*` capability key (none exist). The script SHALL NOT import `kpi_aggregator` directly (maintains subprocess isolation).

```python
# query_daily.py platform path
def fetch_day_with_provenance(date_str, equipment_ids, kpi_keys, eq_type, ...):
    if is_platform_mode():
        # Step 1: Get raw trend data (platform universal capability)
        trend_result = call_capability("monitoring.trend", {
            "equipment_ids": equipment_ids,
            "start_time": day_start, "end_time": day_end,
        })

        # Step 2: KPI aggregation (system-specific computation)
        kpi_result = call_action("aggregate_kpi", adapter="ins_prod", params={
            "trend_data": trend_result["data"],
            "kpi_keys": kpi_keys,
            "eq_type": eq_type,
        })

        # Step 3: Report structure assembly (report business logic)
        return {
            "kpis": kpi_result["data"]["kpis"],
            "hourly_runtime_rate": kpi_result["data"]["hourly_runtime_rate"],
            "alarms": alarm_result["data"],
            ...
        }
```

#### Scenario: Daily report via two-step platform bridge

- **WHEN** `query_daily.py` is invoked with `USE_PLATFORM=true` and `--date 2026-05-28 --equipment E1,E2`
- **THEN** the script calls `call_capability("monitoring.trend", {...})` for raw data
- **THEN** calls `call_action("aggregate_kpi", ...)` for KPI computation
- **THEN** the output JSON has the same schema as the legacy path (report_date, equipment_ids, kpi_keys, current, compare, data_source, data_notes)

#### Scenario: Weekly report via two-step platform bridge

- **WHEN** `query_weekly.py` is invoked with `USE_PLATFORM=true`
- **THEN** the script iterates days in the week range
- **THEN** for each day, calls `call_capability("monitoring.trend", {...})` + `call_action("aggregate_kpi", ...)`
- **THEN** the output JSON contains 7 daily entries in `current.daily[]`

#### Scenario: Monthly report via two-step platform bridge

- **WHEN** `query_monthly.py` is invoked with `USE_PLATFORM=true`
- **THEN** the script computes month-anchored week buckets
- **THEN** for each bucket, fetches and aggregates data
- **THEN** the output JSON contains weekly bucket entries in `current.weekly[]`

### Requirement: Platform bridge call_action helper

The system SHALL add `call_action()` to `_platform_bridge.py` that invokes CLI `--action` mode via subprocess.

```python
def call_action(action: str, adapter: str, params: dict) -> dict:
    """Invoke CLI action mode via subprocess."""
    cmd = [
        sys.executable, "-m", "deerflow.integrations.cli",
        "--action", action,
        "--adapter", adapter,
        "--params", json.dumps(params),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)
```

The function SHALL follow the same error handling pattern as `call_capability()` — raise `PlatformBridgeError` on subprocess failure.

#### Scenario: Successful action call

- **WHEN** `call_action("aggregate_kpi", "ins_prod", {...})` is called
- **THEN** the subprocess runs `python -m deerflow.integrations.cli --action aggregate_kpi --adapter ins_prod --params '{...}'`
- **THEN** returns the parsed JSON output

#### Scenario: Action subprocess failure

- **WHEN** the CLI subprocess exits with non-zero code
- **THEN** `call_action()` raises `PlatformBridgeError` with the stderr content

### Requirement: Compare period support via repeated two-step calls

The system SHALL update each report script's platform bridge path to fetch compare period data by repeating the two-step process with different date/period parameters.

For daily reports: `compare_type` of `previous_day` fetches the day before; `previous_week` fetches 7 days before.

For weekly reports: `previous_week` shifts week_start/week_end by 7 days; `previous_year` shifts by 365 days.

For monthly reports: `previous_month` shifts by 1 month; `previous_year_month` shifts by 12 months.

#### Scenario: Daily report with previous_day comparison

- **WHEN** `query_daily.py` is invoked with `--compare previous_day --date 2026-05-28`
- **THEN** the script runs the two-step process twice: once for 2026-05-28 and once for 2026-05-27
- **THEN** the output JSON `compare` field contains the 2026-05-27 data

### Requirement: Builtin report templates declare provider platform

The system SHALL update all builtin report template YAML files (`daily-equipment`, `weekly-equipment`, `monthly-equipment`, `trend-equipment`) to include `provider: platform` on their data_steps that fetch InS data.

The `data_runner.py` already injects `USE_PLATFORM=true` when `provider: "platform"` is set — no changes to `data_runner.py` are needed.

#### Scenario: Daily equipment template uses platform

- **WHEN** the `daily-equipment` builtin template is executed
- **THEN** its `data_steps[].provider` is set to `"platform"`
- **THEN** `data_runner.py` injects `USE_PLATFORM=true` into the subprocess environment
- **THEN** the query script routes through the two-step platform bridge

### Requirement: Platform bridge error propagation

The system SHALL propagate platform bridge errors to the report script's stdout as `{"error": "..."}` JSON, matching the existing error output convention.

When `_platform_bridge.call_capability()` or `call_action()` raises `PlatformBridgeError`, the script SHALL catch it and output the error JSON, then exit 0 (per Skill convention — errors are reported via stdout, not exit codes).

#### Scenario: CLI subprocess failure

- **WHEN** the integration CLI subprocess fails (e.g., InS connection timeout)
- **THEN** `_platform_bridge.call_capability()` or `call_action()` raises `PlatformBridgeError`
- **THEN** the report script outputs `{"error": "PlatformBridgeError: ..."}` to stdout
- **THEN** the script exits with code 0

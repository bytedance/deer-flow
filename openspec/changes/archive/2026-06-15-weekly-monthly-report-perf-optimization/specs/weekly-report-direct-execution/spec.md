## ADDED Requirements

### Requirement: Weekly report direct execution path

The weekly report Agent SHALL generate reports via `report_direct_execute` tool call in Round 2 callback, replacing the current bash-based multi-step script orchestration. The `DirectReportExecutor` SHALL orchestrate `query_weekly.py` → `weekly_kpi.py` → `export_report.py` through the stdout contract.

#### Scenario: Round 2 callback invokes report_direct_execute

- **WHEN** the Agent receives `ui_interaction` with `callback_id=weekly-report-confirm`
- **THEN** the Agent SHALL call `report_direct_execute` with `report_type="weekly"`, `scope={week_start, date_end}`, `equipment_type`, `compare_with`, `equipment_ids`, `equipment_labels`, `equipment_meta`
- **AND** the Agent SHALL NOT invoke `query_weekly.py`, `weekly_kpi.py`, `query_sms_abnormal.py`, or `export_report.py` as separate bash commands

#### Scenario: Executor orchestrates weekly pipeline

- **WHEN** `DirectReportExecutor.execute(report_type="weekly", ...)` is called
- **THEN** it SHALL run `query_weekly.py`, `weekly_kpi.py`, and `export_report.py` in sequence via `_run_subprocess`
- **AND** each script's stdout SHALL be parsed for the `output` field to locate the real data file
- **AND** the `REPORT_RUN_ID` environment variable SHALL be set for subprocess performance tracing

#### Scenario: SMS data acquired asynchronously within KPI computation

- **WHEN** `weekly_kpi.py` `compute()` is executed
- **THEN** it SHALL start SMS data fetch via `_fetch_sms_direct(payload)` in a background thread
- **AND** SMS fetch failure SHALL return None without affecting main KPI computation
- **AND** SMS results SHALL be merged into `kpi_summary` as `_sms_kpi` entries when available

### Requirement: Weekly report performance instrumentation

The weekly report scripts SHALL include `_perf.py` (copied from daily-report) and integrate `PerfTracer` at key stages.

#### Scenario: Performance traces are recorded

- **WHEN** a weekly report is generated via `report_direct_execute`
- **THEN** `<output_dir>/.perf/<trace_id>.jsonl` SHALL contain timing records for: org tree resolution, InS data fetch (per batch), KPI computation, SMS fetch, and export
- **AND** each record SHALL include `trace_id`, `step_name`, `duration_ms`, `record_count`, `timestamp`

#### Scenario: Tracer uses REPORT_RUN_ID

- **WHEN** `weekly_kpi.py` or `query_weekly.py` initializes `PerfTracer`
- **THEN** it SHALL read `trace_id` from `REPORT_RUN_ID` environment variable
- **AND** if `REPORT_RUN_ID` is empty, the tracer SHALL be a no-op (no output)

### Requirement: Weekly report InS concurrent fetching

The weekly report `_ins_client.py` SHALL use `asyncio.Semaphore` + `asyncio.gather` for rate-limited concurrent device data fetching, matching the daily report pattern.

#### Scenario: Semaphore limits concurrent InS requests

- **WHEN** `fetch_trend_data_async` is called with N equipment IDs
- **THEN** at most `INS_CONCURRENCY_LIMIT` (default 4, configurable via env var) requests SHALL be in-flight simultaneously

#### Scenario: Slim components cache is shared

- **WHEN** `fetch_trend_data_async` and `fetch_alarm_events_async` are called for the same equipment within a single script run
- **THEN** `_get_slim_components_cached` SHALL return cached results for the second call

### Requirement: Weekly report org tree passthrough

The weekly report `query_weekly.py` SHALL accept `--equipment-meta` CLI parameter and use it for equipment name resolution. Internal functions already support `equipment_meta: dict[str, dict] | None`; only CLI argument parsing and passthrough need to be added.

#### Scenario: Equipment metadata consumed from CLI parameter

- **WHEN** `query_weekly.py` is invoked with `--equipment-meta '<json>'`
- **THEN** it SHALL parse the JSON and pass it as `equipment_meta` to internal query functions
- **AND** the internal functions SHALL use it for equipment name resolution without querying the org tree API

#### Scenario: Static KPI catalog used in Round 1.5

- **WHEN** the weekly Agent generates the Round 2 KPI selection form
- **THEN** it SHALL read KPI metadata from `_report_common.get_kpi_catalog(equipment_type)` (static mapping)
- **AND** it SHALL NOT call `list_equipment.py --limit 1` to discover KPIs

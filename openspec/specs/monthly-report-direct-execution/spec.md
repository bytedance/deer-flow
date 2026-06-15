## Purpose

Monthly report direct execution path that bypasses the DSL template engine state machine. The `DirectReportExecutor` orchestrates `query_monthly.py` → `monthly_kpi.py` → `export_report.py` with performance instrumentation, date-level concurrent InS fetching, and equipment metadata passthrough.

## Requirements

### Requirement: Monthly report direct execution path

The monthly report Agent SHALL generate reports via `report_direct_execute` tool call in Round 2 callback, replacing the current bash-based multi-step script orchestration. The `DirectReportExecutor` SHALL orchestrate `query_monthly.py` → `monthly_kpi.py` → `export_report.py` through the stdout contract.

#### Scenario: Round 2 callback invokes report_direct_execute

- **WHEN** the Agent receives `ui_interaction` with `callback_id=monthly-report-confirm`
- **THEN** the Agent SHALL call `report_direct_execute` with `report_type="monthly"`, `scope={report_month}`, `equipment_type`, `compare_with`, `equipment_ids`, `equipment_labels`, `equipment_meta`
- **AND** the Agent SHALL NOT invoke `query_monthly.py`, `monthly_kpi.py`, `query_sms_abnormal.py`, or `export_report.py` as separate bash commands

#### Scenario: Executor orchestrates monthly pipeline

- **WHEN** `DirectReportExecutor.execute(report_type="monthly", ...)` is called
- **THEN** it SHALL run `query_monthly.py`, `monthly_kpi.py`, and `export_report.py` in sequence via `_run_subprocess`
- **AND** each script's stdout SHALL be parsed for the `output` field to locate the real data file
- **AND** the `REPORT_RUN_ID` environment variable SHALL be set for subprocess performance tracing

#### Scenario: SMS data acquired asynchronously within KPI computation

- **WHEN** `monthly_kpi.py` `compute()` is executed
- **THEN** it SHALL start SMS data fetch via `_fetch_sms_direct(payload)` in a background thread
- **AND** SMS fetch failure SHALL return None without affecting main KPI computation
- **AND** SMS results SHALL be merged into `kpi_summary` as `_sms_kpi` entries when available

### Requirement: Monthly report performance instrumentation

The monthly report scripts SHALL include `_perf.py` (copied from daily-report) and integrate `PerfTracer` at key stages.

#### Scenario: Performance traces are recorded

- **WHEN** a monthly report is generated via `report_direct_execute`
- **THEN** `<output_dir>/.perf/<trace_id>.jsonl` SHALL contain timing records for: org tree resolution, InS data fetch (per day batch), KPI computation, SMS fetch, and export
- **AND** each record SHALL include `trace_id`, `step_name`, `duration_ms`, `record_count`, `timestamp`

### Requirement: Monthly report InS concurrent fetching with date-level parallelism

The monthly report `_ins_client.py` SHALL use `asyncio.Semaphore` + `asyncio.gather` for rate-limited concurrent device data fetching. The `query_monthly.py` SHALL additionally use date-level parallelism — fetching multiple workdays concurrently via `ThreadPoolExecutor`, with each day's fetch using the Semaphore for device-level concurrency.

#### Scenario: Date-level concurrent fetching

- **WHEN** `query_monthly.py` fetches data for a month with ~22 workdays
- **THEN** it SHALL use `ThreadPoolExecutor` to fetch multiple days concurrently
- **AND** each day's fetch SHALL respect the `INS_CONCURRENCY_LIMIT` Semaphore for device-level concurrency
- **AND** all date-level fetches SHALL share a single Semaphore instance to prevent overwhelming the InS API

#### Scenario: Slim components cache is shared across days

- **WHEN** multiple days within a monthly report query the same equipment
- **THEN** `_get_slim_components_cached` SHALL return cached results for subsequent calls

### Requirement: Monthly report org tree passthrough

The monthly report `query_monthly.py` SHALL accept `--equipment-meta` CLI parameter and use it for equipment name resolution. Internal functions already support `equipment_meta: dict[str, dict] | None`; only CLI argument parsing and passthrough need to be added.

#### Scenario: Equipment metadata consumed from CLI parameter

- **WHEN** `query_monthly.py` is invoked with `--equipment-meta '<json>'`
- **THEN** it SHALL parse the JSON and pass it as `equipment_meta` to internal query functions
- **AND** the internal functions SHALL use it for equipment name resolution without querying the org tree API

#### Scenario: Static KPI catalog used in Round 1.5

- **WHEN** the monthly Agent generates the Round 2 KPI selection form
- **THEN** it SHALL read KPI metadata from `_report_common.get_kpi_catalog(equipment_type)` (static mapping)
- **AND** it SHALL NOT call `list_equipment.py --limit 1` to discover KPIs

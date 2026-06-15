## ADDED Requirements

### Requirement: Monthly report _perf.py instrumentation module

The `monthly-report/scripts/_perf.py` SHALL be a copy of `daily-report/scripts/_perf.py` providing the `PerfTracer` class with `start_span(step_name)` / `end_span(record_count=0)` interface, outputting structured JSON to stderr and appending to `<output_dir>/.perf/<trace_id>.jsonl`.

#### Scenario: Perf module exists in monthly skill

- **WHEN** the monthly-report skill is installed
- **THEN** `skills/custom/monthly-report/scripts/_perf.py` SHALL exist and export `PerfTracer` and `get_tracer`
- **AND** it SHALL be self-contained (no imports from other skills)

### Requirement: Monthly report InS client concurrent fetching with date-level parallelism

The `monthly-report/scripts/_ins_client.py` SHALL use `asyncio.Semaphore` + `asyncio.gather` for rate-limited concurrent device data fetching. Additionally, `query_monthly.py` SHALL implement date-level parallelism — fetching multiple workdays concurrently via `ThreadPoolExecutor`, with all dates sharing a single Semaphore for device-level concurrency.

#### Scenario: Date-level concurrent fetching

- **WHEN** `query_monthly.py` processes a month with ~22 workdays
- **THEN** it SHALL use `ThreadPoolExecutor` to fetch multiple days concurrently
- **AND** each day's device fetch SHALL share a global `asyncio.Semaphore(INS_CONCURRENCY_LIMIT)` instance
- **AND** the Semaphore SHALL be created once and passed to all day-level fetch calls

#### Scenario: Slim components cache shared across days

- **WHEN** multiple days within a monthly report query the same equipment
- **THEN** `_get_slim_components_cached(equipment_id)` SHALL return cached results for subsequent calls across different days

### Requirement: Monthly report _report_common.py KPI catalog function

The `monthly-report/scripts/_report_common.py` SHALL export `get_kpi_catalog(eq_type: str) -> list[dict]` returning the static KPI metadata for a given equipment type, including monthly-specific KPIs (`mtbf`, `mttr`, `target_rate`) where applicable.

#### Scenario: KPI catalog for each equipment type

- **WHEN** `get_kpi_catalog("all")` is called
- **THEN** it SHALL return a list of KPI dicts with `key`, `name`, `unit`, `default` fields
- **AND** the list SHALL include `runtime_rate`, `alarm_count`, and monthly-specific KPIs

### Requirement: Monthly report monthly_kpi.py SMS async fetch

The `monthly-report/scripts/monthly_kpi.py` SHALL include `_fetch_sms_direct(payload)` and `_sms_kpi(key, value)` helper functions, acquiring SMS data asynchronously within `compute()` via `ThreadPoolExecutor(max_workers=1)`.

#### Scenario: SMS fetch runs concurrently with KPI computation

- **WHEN** `monthly_kpi.py` `compute()` is called
- **THEN** it SHALL submit `_fetch_sms_direct(payload)` to a `ThreadPoolExecutor` before starting KPI computation
- **AND** SHALL call `sms_future.result()` after KPI computation to collect SMS data

#### Scenario: SMS fetch failure returns None

- **WHEN** `query_sms_abnormal.fetch_sms_abnormal` raises an exception
- **THEN** `_fetch_sms_direct` SHALL catch the exception and return None
- **AND** `compute()` SHALL proceed without SMS data in the output

### Requirement: Monthly report export_report.py performance instrumentation

The `monthly-report/scripts/export_report.py` SHALL integrate `PerfTracer` at the export stage for timing instrumentation.

#### Scenario: Export timing recorded

- **WHEN** `export_report.py` `render_markdown()` is called
- **THEN** it SHALL record export duration via `PerfTracer.start_span("export")` / `end_span()`

### Requirement: Monthly report query_monthly.py equipment-meta CLI parameter

The `monthly-report/scripts/query_monthly.py` SHALL accept `--equipment-meta` CLI parameter (JSON string or @file path) and pass it to internal functions that already support the `equipment_meta` keyword argument. The internal function signatures already accept `equipment_meta: dict[str, dict] | None`; only the CLI argument parsing and passthrough need to be added.

#### Scenario: Equipment meta consumed from CLI

- **WHEN** `query_monthly.py` is invoked with `--equipment-meta '<json>'`
- **THEN** it SHALL parse the JSON and pass it as `equipment_meta` to the internal query functions
- **AND** the internal functions SHALL use it for equipment name resolution without querying the org tree API

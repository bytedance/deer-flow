## ADDED Requirements

### Requirement: Weekly report _perf.py instrumentation module

The `weekly-report/scripts/_perf.py` SHALL be a copy of `daily-report/scripts/_perf.py` providing the `PerfTracer` class with `start_span(step_name)` / `end_span(record_count=0)` interface, outputting structured JSON to stderr and appending to `<output_dir>/.perf/<trace_id>.jsonl`.

#### Scenario: Perf module exists in weekly skill

- **WHEN** the weekly-report skill is installed
- **THEN** `skills/custom/weekly-report/scripts/_perf.py` SHALL exist and export `PerfTracer` and `get_tracer`
- **AND** it SHALL be self-contained (no imports from other skills)

#### Scenario: Tracer disabled when REPORT_RUN_ID is empty

- **WHEN** `get_tracer(trace_id=None)` is called
- **THEN** it SHALL return a no-op tracer that produces no output

### Requirement: Weekly report InS client concurrent fetching

The `weekly-report/scripts/_ins_client.py` SHALL use `asyncio.Semaphore` + `asyncio.gather` for rate-limited concurrent device data fetching, with a shared `_get_slim_components_cached` dict cache.

#### Scenario: fetch_trend_data_async uses semaphore

- **WHEN** `fetch_trend_data_async` is called with N equipment IDs
- **THEN** it SHALL limit concurrent requests to `INS_CONCURRENCY_LIMIT` (env var, default 4) via `asyncio.Semaphore`
- **AND** results SHALL be gathered via `asyncio.gather` preserving order

#### Scenario: fetch_alarm_events_async uses semaphore

- **WHEN** `fetch_alarm_events_async` is called with N equipment IDs
- **THEN** it SHALL apply the same Semaphore + gather pattern as `fetch_trend_data_async`

#### Scenario: Slim components cache hit

- **WHEN** `_get_slim_components_cached(equipment_id)` is called for the same equipment_id twice within a single script run
- **THEN** the second call SHALL return the cached result without making an API call

### Requirement: Weekly report _report_common.py KPI catalog function

The `weekly-report/scripts/_report_common.py` SHALL export `get_kpi_catalog(eq_type: str) -> list[dict]` returning the static KPI metadata for a given equipment type, including `key`, `name`, `unit`, and `default` fields.

#### Scenario: KPI catalog for each equipment type

- **WHEN** `get_kpi_catalog("rotating_machinery")` is called
- **THEN** it SHALL return a list of KPI dicts with `key`, `name`, `unit`, `default` fields
- **AND** the list SHALL include `runtime_rate`, `vibration_level`, `bearing_temp`, `downtime_count`

### Requirement: Weekly report weekly_kpi.py SMS async fetch

The `weekly-report/scripts/weekly_kpi.py` SHALL include `_fetch_sms_direct(payload)` and `_sms_kpi(key, value)` helper functions, acquiring SMS data asynchronously within `compute()` via `ThreadPoolExecutor(max_workers=1)`.

#### Scenario: SMS fetch runs concurrently with KPI computation

- **WHEN** `weekly_kpi.py` `compute()` is called
- **THEN** it SHALL submit `_fetch_sms_direct(payload)` to a `ThreadPoolExecutor` before starting KPI computation
- **AND** SHALL call `sms_future.result()` after KPI computation to collect SMS data

#### Scenario: SMS fetch failure returns None

- **WHEN** `query_sms_abnormal.fetch_sms_abnormal` raises an exception
- **THEN** `_fetch_sms_direct` SHALL catch the exception and return None
- **AND** `compute()` SHALL proceed without SMS data in the output

#### Scenario: SMS KPI entries injected when data available

- **WHEN** `_fetch_sms_direct` returns a valid dict with `total_count > 0`
- **THEN** `compute()` SHALL append `_sms_kpi("sms_abnormal_count", total)` and `_sms_kpi("sms_abnormal_pending", pending)` to `kpi_summary`

### Requirement: Weekly report export_report.py performance instrumentation

The `weekly-report/scripts/export_report.py` SHALL integrate `PerfTracer` at the export stage for timing instrumentation.

#### Scenario: Export timing recorded

- **WHEN** `export_report.py` `render_markdown()` is called
- **THEN** it SHALL record export duration via `PerfTracer.start_span("export")` / `end_span()`

### Requirement: Weekly report query_weekly.py equipment-meta CLI parameter

The `weekly-report/scripts/query_weekly.py` SHALL accept `--equipment-meta` CLI parameter (JSON string or @file path) and pass it to internal functions that already support the `equipment_meta` keyword argument. The internal function signatures already accept `equipment_meta: dict[str, dict] | None`; only the CLI argument parsing and passthrough need to be added.

#### Scenario: Equipment meta consumed from CLI

- **WHEN** `query_weekly.py` is invoked with `--equipment-meta '<json>'`
- **THEN** it SHALL parse the JSON and pass it as `equipment_meta` to the internal query functions
- **AND** the internal functions SHALL use it for equipment name resolution without querying the org tree API

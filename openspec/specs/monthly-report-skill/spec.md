# Monthly Report Skill

## Purpose

Defines the `monthly-report` skill as a fully self-contained unit that includes all scripts and internal modules needed to generate equipment monthly reports, independent of the `data-analyst`, `daily-report`, and `weekly-report` skills.

## Requirements

### Requirement: Self-contained monthly report skill

The `monthly-report` skill SHALL be a fully self-contained skill at `skills/custom/monthly-report/` that includes all scripts and internal modules needed to generate equipment monthly reports. The skill MUST NOT import or depend on any other skill's scripts or modules. Every internal module SHALL be an independent copy specific to this skill.

#### Scenario: Skill directory structure is complete

- **WHEN** the `monthly-report` skill is installed
- **THEN** its `scripts/` directory contains `_data_providers.py`, `_data_provider_impls.py`, `_platform_bridge.py`, `_ins_provider.py`, `_report_common.py`, `query_monthly.py`, `monthly_kpi.py`, `list_equipment.py`, `export_report.py`
- **AND** the skill root contains `SKILL.md` and `report_scripts.yaml`

#### Scenario: Skill has no cross-skill imports

- **WHEN** any script in `skills/custom/monthly-report/scripts/` is executed
- **THEN** all imports resolve to either stdlib, site-packages, or sibling modules within `skills/custom/monthly-report/scripts/`
- **AND** no import references `data-analyst`, `daily-report`, or `weekly-report` skill directories

#### Scenario: Skill runs independently

- **WHEN** the `monthly-report` skill directory is the only skill installed (no `data-analyst`, `daily-report`, or `weekly-report` present)
- **THEN** `query_monthly.py`, `monthly_kpi.py`, `list_equipment.py`, and `export_report.py` all execute successfully with valid inputs

### Requirement: Monthly report script registry

The `monthly-report/report_scripts.yaml` SHALL declare only the scripts needed for monthly report generation: `query_monthly`, `monthly_kpi`, `list_equipment`, and `export_report`. Each entry SHALL include `args_schema`, `output_files`, `timeout`, and `dependencies` matching the existing script contracts.

#### Scenario: Registry declares only monthly scripts

- **WHEN** `report_scripts.yaml` is loaded by the Script Registry
- **THEN** it exposes exactly four script names: `query_monthly`, `monthly_kpi`, `list_equipment`, `export_report`
- **AND** no daily, weekly, trend, diagnosis, or other script names are present

#### Scenario: Script names use monthly-report namespace

- **WHEN** a DSL template references a script as `monthly-report/query_monthly`
- **THEN** the Script Registry resolves it to `skills/custom/monthly-report/scripts/query_monthly.py`

### Requirement: Trimmed _report_common.py for monthly reports

The `monthly-report/scripts/_report_common.py` SHALL contain the daily subset plus `KPI_DISPLAY_NAMES_MONTHLY`, `KPI_BETTER_WHEN_HIGHER_MONTHLY`, `parse_report_month`, `month_bounds`, `has_previous_year_data_monthly`, and `aggregate_kpis`. Weekly-specific functions (`has_previous_year_data_weekly`) MUST NOT be present.

#### Scenario: Monthly constants are available

- **WHEN** `query_monthly.py` imports from `_report_common`
- **THEN** `KPI_DISPLAY_NAMES`, `KPI_DISPLAY_NAMES_MONTHLY`, `KPI_BETTER_WHEN_HIGHER_MONTHLY`, `parse_report_month`, `month_bounds`, and `aggregate_kpis` are defined

#### Scenario: Weekly-specific functions are absent

- **WHEN** inspecting `monthly-report/scripts/_report_common.py`
- **THEN** `has_previous_year_data_weekly` is not defined

### Requirement: Trimmed _data_provider_impls.py for monthly reports

The `monthly-report/scripts/_data_provider_impls.py` SHALL register only `PlatformMonthlyProvider`. No daily, weekly, trend, diagnosis, or other Provider classes SHALL be present.

#### Scenario: Only monthly Provider is registered

- **WHEN** `_data_provider_impls.py` is loaded
- **THEN** `get_provider("monthly")` returns `PlatformMonthlyProvider`
- **AND** calling `get_provider("daily")` or `get_provider("weekly")` raises `KeyError`

### Requirement: Trimmed export_report.py for monthly reports

The `monthly-report/scripts/export_report.py` SHALL support only the `monthly` report type in `render_markdown()` and `write_report()`. Daily, weekly, diagnosis, monitoring, and trend rendering logic MUST NOT be present.

#### Scenario: Monthly export works

- **WHEN** `export_report.py` is invoked with report type `monthly`
- **THEN** it renders a valid Markdown monthly report and writes the output file

#### Scenario: Daily type raises error

- **WHEN** `export_report.py` is invoked with report type `daily`
- **THEN** it raises a clear error indicating only `monthly` is supported

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

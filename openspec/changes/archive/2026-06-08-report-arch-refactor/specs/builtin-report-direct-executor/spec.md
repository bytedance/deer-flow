## ADDED Requirements

### Requirement: Builtin report direct execution tool

The system SHALL provide a `report_direct_execute` tool that bypasses the DSL template engine state machine and directly orchestrates Skill script calls for builtin report types (daily, weekly, monthly).

#### Scenario: Direct execute daily report

- **WHEN** the agent calls `report_direct_execute(report_type="daily", scope={report_date: "2026-06-08"}, equipment_type="all", compare_with="previous_day", equipment_ids=["P-203A"], equipment_labels=["进料泵P-203A"], kpi_keys=["runtime_rate", "alarm_count"])`
- **THEN** the tool SHALL execute the following sequence internally: (1) invoke `query_daily.py` with the provided parameters, (2) invoke `daily_kpi.py` to compute KPI aggregates, (3) invoke `export_report.py` to generate Markdown artifact, (4) return a JSON result containing `{report_run_id, artifacts: [{path, type}], status: "success"}`

#### Scenario: Direct execute weekly report

- **WHEN** the agent calls `report_direct_execute(report_type="weekly", scope={week_start: "2026-06-01", date_end: "2026-06-07"}, ...)`
- **THEN** the tool SHALL execute `query_weekly.py` → `weekly_kpi.py` → `export_report.py` and return the same result structure

#### Scenario: Direct execute monthly report

- **WHEN** the agent calls `report_direct_execute(report_type="monthly", scope={report_month: "2026-06"}, ...)`
- **THEN** the tool SHALL execute `query_monthly.py` → `monthly_kpi.py` → `export_report.py` and return the same result structure

### Requirement: Direct executor skips DSL state machine

The `report_direct_execute` tool SHALL NOT create or update any `status.json` file, SHALL NOT invoke `render_step` or `submit_step`, and SHALL NOT trigger any `before_step` scripts.

#### Scenario: No before_step script execution

- **WHEN** `report_direct_execute` is called with `kpi_keys=["runtime_rate"]`
- **THEN** the tool SHALL NOT call `list_equipment.py` or any other `before_step` script, and SHALL NOT make any Organize API calls

#### Scenario: No state machine transitions

- **WHEN** `report_direct_execute` completes
- **THEN** no `status.json` file SHALL be created in the thread output directory, and no DSL runtime state transitions SHALL occur

### Requirement: Direct executor error handling

When a Skill script fails during direct execution, the tool SHALL return a structured error response without raising an exception.

#### Scenario: Script execution failure

- **WHEN** `query_daily.py` exits with a non-zero code or outputs `{"error": "..."}`
- **THEN** the tool SHALL return `{"error": {"code": "SCRIPT_FAILED", "message": "...", "step": "query_daily"}, "status": "failed"}` and SHALL NOT continue to subsequent steps

#### Scenario: Missing equipment data

- **WHEN** the data script returns empty results for the specified equipment and date range
- **THEN** the tool SHALL return `{"error": {"code": "NO_DATA", "message": "...", "step": "query_daily"}, "status": "failed"}`

### Requirement: Direct executor artifact output

The tool SHALL write all output artifacts to the thread-scoped output directory and return their paths.

#### Scenario: Artifacts written to output directory

- **WHEN** `report_direct_execute` completes successfully
- **THEN** the tool SHALL write `daily_report.md` (or `weekly_report.md` / `monthly_report.md`) to `/mnt/user-data/outputs/` and include the path in the returned `artifacts` array

### Requirement: Direct executor parameter defaults

When optional parameters are omitted, the tool SHALL use the same defaults as the DSL template definitions.

#### Scenario: Default equipment selection

- **WHEN** `equipment_ids` is `None` or omitted
- **THEN** the tool SHALL pass `--scope all` to the data script (matching the DSL template default behavior)

#### Scenario: Default KPI selection

- **WHEN** `kpi_keys` is `None` or omitted
- **THEN** the tool SHALL use the template-defined default KPI set for the report type

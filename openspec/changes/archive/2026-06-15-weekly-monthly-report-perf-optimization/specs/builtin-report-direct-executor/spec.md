## MODIFIED Requirements

### Requirement: Builtin report direct execution tool

The system SHALL provide a `report_direct_execute` tool that bypasses the DSL template engine state machine and directly orchestrates Skill script calls for builtin report types (daily, weekly, monthly).

#### Scenario: Direct execute daily report

- **WHEN** the agent calls `report_direct_execute(report_type="daily", scope={report_date: "2026-06-08"}, equipment_type="all", compare_with="previous_day", equipment_ids=["P-203A"], equipment_labels=["进料泵P-203A"], kpi_keys=["runtime_rate", "alarm_count"])`
- **THEN** the tool SHALL execute the following sequence internally: (1) invoke `query_daily.py` with the provided parameters, (2) invoke `daily_kpi.py` to compute KPI aggregates, (3) invoke `export_report.py` to generate Markdown artifact, (4) return a JSON result containing `{report_run_id, artifacts: [{path, type}], status: "success"}`

#### Scenario: Direct execute weekly report

- **WHEN** the agent calls `report_direct_execute(report_type="weekly", scope={week_start: "2026-06-01", date_end: "2026-06-07"}, ...)`
- **THEN** the tool SHALL execute `query_weekly.py` -> `weekly_kpi.py` -> `export_report.py` and return the same result structure

#### Scenario: Direct execute monthly report

- **WHEN** the agent calls `report_direct_execute(report_type="monthly", scope={report_month: "2026-06"}, ...)`
- **THEN** the tool SHALL execute `query_monthly.py` -> `monthly_kpi.py` -> `export_report.py` and return the same result structure

#### Scenario: Equipment metadata passthrough

- **WHEN** the agent calls `report_direct_execute` with `equipment_meta={id: {id, name}}` dict
- **THEN** the executor SHALL construct `--equipment-meta` CLI argument as JSON `{"equipment_type": ..., "records": [...], **equipment_meta}` and pass it to the query script
- **AND** the query script SHALL consume the metadata for equipment name resolution and type detection without querying the org tree API

#### Scenario: REPORT_RUN_ID propagated to subprocesses

- **WHEN** `report_direct_execute` is called
- **THEN** the executor SHALL set the `REPORT_RUN_ID` environment variable (using the generated `report_run_id`) for all subprocess invocations
- **AND** scripts SHALL use this env var to initialize `PerfTracer` for performance instrumentation

# Weekly Report Skill

## ADDED Requirements

### Requirement: Self-contained weekly report skill

The `weekly-report` skill SHALL be a fully self-contained skill at `skills/custom/weekly-report/` that includes all scripts and internal modules needed to generate equipment weekly reports. The skill MUST NOT import or depend on any other skill's scripts or modules. Every internal module SHALL be an independent copy specific to this skill.

#### Scenario: Skill directory structure is complete

- **WHEN** the `weekly-report` skill is installed
- **THEN** its `scripts/` directory contains `_data_providers.py`, `_data_provider_impls.py`, `_platform_bridge.py`, `_ins_provider.py`, `_report_common.py`, `query_weekly.py`, `weekly_kpi.py`, `list_equipment.py`, `export_report.py`
- **AND** the skill root contains `SKILL.md` and `report_scripts.yaml`

#### Scenario: Skill has no cross-skill imports

- **WHEN** any script in `skills/custom/weekly-report/scripts/` is executed
- **THEN** all imports resolve to either stdlib, site-packages, or sibling modules within `skills/custom/weekly-report/scripts/`
- **AND** no import references `data-analyst`, `daily-report`, or `monthly-report` skill directories

#### Scenario: Skill runs independently

- **WHEN** the `weekly-report` skill directory is the only skill installed (no `data-analyst`, `daily-report`, or `monthly-report` present)
- **THEN** `query_weekly.py`, `weekly_kpi.py`, `list_equipment.py`, and `export_report.py` all execute successfully with valid inputs

### Requirement: Weekly report script registry

The `weekly-report/report_scripts.yaml` SHALL declare only the scripts needed for weekly report generation: `query_weekly`, `weekly_kpi`, `list_equipment`, and `export_report`. Each entry SHALL include `args_schema`, `output_files`, `timeout`, and `dependencies` matching the existing script contracts.

#### Scenario: Registry declares only weekly scripts

- **WHEN** `report_scripts.yaml` is loaded by the Script Registry
- **THEN** it exposes exactly four script names: `query_weekly`, `weekly_kpi`, `list_equipment`, `export_report`
- **AND** no daily, monthly, trend, diagnosis, or other script names are present

#### Scenario: Script names use weekly-report namespace

- **WHEN** a DSL template references a script as `weekly-report/query_weekly`
- **THEN** the Script Registry resolves it to `skills/custom/weekly-report/scripts/query_weekly.py`

### Requirement: Trimmed _report_common.py for weekly reports

The `weekly-report/scripts/_report_common.py` SHALL contain the daily subset plus `has_previous_year_data_weekly` and `aggregate_kpis` (7-day mean). Monthly-specific constants (`KPI_DISPLAY_NAMES_MONTHLY`, `KPI_BETTER_WHEN_HIGHER_MONTHLY`, `parse_report_month`, `month_bounds`, `has_previous_year_data_monthly`) MUST NOT be present.

#### Scenario: Weekly constants are available

- **WHEN** `query_weekly.py` imports from `_report_common`
- **THEN** `KPI_DISPLAY_NAMES`, `KPI_THRESHOLDS`, `aggregate_kpis`, and `has_previous_year_data_weekly` are defined

#### Scenario: Monthly constants are absent

- **WHEN** inspecting `weekly-report/scripts/_report_common.py`
- **THEN** `KPI_DISPLAY_NAMES_MONTHLY`, `KPI_BETTER_WHEN_HIGHER_MONTHLY`, `parse_report_month`, `month_bounds`, and `has_previous_year_data_monthly` are not defined

### Requirement: Trimmed _data_provider_impls.py for weekly reports

The `weekly-report/scripts/_data_provider_impls.py` SHALL register only `PlatformWeeklyProvider`. No daily, monthly, trend, diagnosis, or other Provider classes SHALL be present.

#### Scenario: Only weekly Provider is registered

- **WHEN** `_data_provider_impls.py` is loaded
- **THEN** `get_provider("weekly")` returns `PlatformWeeklyProvider`
- **AND** calling `get_provider("daily")` or `get_provider("monthly")` raises `KeyError`

### Requirement: Trimmed export_report.py for weekly reports

The `weekly-report/scripts/export_report.py` SHALL support only the `weekly` report type in `render_markdown()` and `write_report()`. Daily, monthly, diagnosis, monitoring, and trend rendering logic MUST NOT be present.

#### Scenario: Weekly export works

- **WHEN** `export_report.py` is invoked with report type `weekly`
- **THEN** it renders a valid Markdown weekly report and writes the output file

#### Scenario: Daily type raises error

- **WHEN** `export_report.py` is invoked with report type `daily`
- **THEN** it raises a clear error indicating only `weekly` is supported

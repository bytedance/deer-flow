# Daily Report Skill

## ADDED Requirements

### Requirement: Self-contained daily report skill

The `daily-report` skill SHALL be a fully self-contained skill at `skills/custom/daily-report/` that includes all scripts and internal modules needed to generate equipment daily reports. The skill MUST NOT import or depend on any other skill's scripts or modules. Every internal module SHALL be an independent copy specific to this skill.

#### Scenario: Skill directory structure is complete

- **WHEN** the `daily-report` skill is installed
- **THEN** its `scripts/` directory contains `_data_providers.py`, `_data_provider_impls.py`, `_platform_bridge.py`, `_ins_provider.py`, `_report_common.py`, `query_daily.py`, `daily_kpi.py`, `list_equipment.py`, `export_report.py`
- **AND** the skill root contains `SKILL.md` and `report_scripts.yaml`

#### Scenario: Skill has no cross-skill imports

- **WHEN** any script in `skills/custom/daily-report/scripts/` is executed
- **THEN** all imports resolve to either stdlib, site-packages, or sibling modules within `skills/custom/daily-report/scripts/`
- **AND** no import references `data-analyst`, `weekly-report`, or `monthly-report` skill directories

#### Scenario: Skill runs independently

- **WHEN** the `daily-report` skill directory is the only skill installed (no `data-analyst`, `weekly-report`, or `monthly-report` present)
- **THEN** `query_daily.py`, `daily_kpi.py`, `list_equipment.py`, and `export_report.py` all execute successfully with valid inputs

### Requirement: Daily report script registry

The `daily-report/report_scripts.yaml` SHALL declare only the scripts needed for daily report generation: `query_daily`, `daily_kpi`, `list_equipment`, and `export_report`. Each entry SHALL include `args_schema`, `output_files`, `timeout`, and `dependencies` matching the existing script contracts.

#### Scenario: Registry declares only daily scripts

- **WHEN** `report_scripts.yaml` is loaded by the Script Registry
- **THEN** it exposes exactly four script names: `query_daily`, `daily_kpi`, `list_equipment`, `export_report`
- **AND** no weekly, monthly, trend, diagnosis, or other script names are present

#### Scenario: Script names use daily-report namespace

- **WHEN** a DSL template references a script as `daily-report/query_daily`
- **THEN** the Script Registry resolves it to `skills/custom/daily-report/scripts/query_daily.py`

### Requirement: Trimmed _report_common.py for daily reports

The `daily-report/scripts/_report_common.py` SHALL contain only the constants and functions needed by daily report scripts: `KPI_DISPLAY_NAMES` (without monthly extensions), `KPI_BETTER_WHEN_HIGHER`, `KPI_THRESHOLDS`, `validate_equipment_ids`, `parse_csv`, `error_output`, `load_sibling_module`, `detect_equipment_type`, `resolve_equipment_by_scope`, `direction`, and `safe_pct`. Weekly-specific and monthly-specific constants and functions MUST NOT be present.

#### Scenario: Daily constants are available

- **WHEN** `query_daily.py` imports from `_report_common`
- **THEN** `KPI_DISPLAY_NAMES` and `KPI_THRESHOLDS` are defined and match the existing values from `data-analyst`

#### Scenario: Monthly constants are absent

- **WHEN** inspecting `daily-report/scripts/_report_common.py`
- **THEN** `KPI_DISPLAY_NAMES_MONTHLY`, `KPI_BETTER_WHEN_HIGHER_MONTHLY`, `parse_report_month`, `month_bounds`, `has_previous_year_data_monthly`, and `has_previous_year_data_weekly` are not defined

### Requirement: Trimmed _data_provider_impls.py for daily reports

The `daily-report/scripts/_data_provider_impls.py` SHALL register only `PlatformDailyProvider`. No weekly, monthly, trend, diagnosis, or other Provider classes SHALL be present.

#### Scenario: Only daily Provider is registered

- **WHEN** `_data_provider_impls.py` is loaded
- **THEN** `get_provider("daily")` returns `PlatformDailyProvider`
- **AND** calling `get_provider("weekly")` or `get_provider("monthly")` raises `KeyError`

### Requirement: Trimmed export_report.py for daily reports

The `daily-report/scripts/export_report.py` SHALL support only the `daily` report type in `render_markdown()` and `write_report()`. Weekly, monthly, diagnosis, monitoring, and trend rendering logic MUST NOT be present.

#### Scenario: Daily export works

- **WHEN** `export_report.py` is invoked with report type `daily`
- **THEN** it renders a valid Markdown daily report and writes the output file

#### Scenario: Weekly type raises error

- **WHEN** `export_report.py` is invoked with report type `weekly`
- **THEN** it raises a clear error indicating only `daily` is supported

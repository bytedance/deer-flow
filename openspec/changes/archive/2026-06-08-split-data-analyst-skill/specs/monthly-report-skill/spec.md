# Monthly Report Skill

## ADDED Requirements

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

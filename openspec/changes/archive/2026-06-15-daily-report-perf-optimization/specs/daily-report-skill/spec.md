## MODIFIED Requirements

### Requirement: Daily report script registry

The `daily-report/report_scripts.yaml` SHALL declare only the scripts needed for daily report generation: `query_daily`, `daily_kpi`, `list_equipment`, and `export_report`. Each entry SHALL include `args_schema`, `output_files`, `timeout`, and `dependencies` matching the existing script contracts. The `list_equipment` script SHALL NOT be invoked during Round 1.5 for KPI metadata retrieval; KPI metadata SHALL be sourced from a static mapping.

#### Scenario: Registry declares only daily scripts

- **WHEN** `report_scripts.yaml` is loaded by the Script Registry
- **THEN** it exposes exactly four script names: `query_daily`, `daily_kpi`, `list_equipment`, `export_report`
- **AND** no weekly, monthly, trend, diagnosis, or other script names are present

#### Scenario: Script names use daily-report namespace

- **WHEN** a DSL template references a script as `daily-report/query_daily`
- **THEN** the Script Registry resolves it to `skills/custom/daily-report/scripts/query_daily.py`

#### Scenario: Round 1.5 does not invoke list_equipment

- **WHEN** the daily report skill processes a Round 1.5 callback (device selection)
- **THEN** the skill SHALL NOT invoke `list_equipment.py` for KPI metadata retrieval
- **AND** KPI metadata SHALL be sourced from the static `_EQUIPMENT_TYPE_DEFAULT_KPIS` mapping

## ADDED Requirements

### Requirement: Static KPI metadata mapping

The daily report skill SHALL provide a static mapping `_EQUIPMENT_TYPE_DEFAULT_KPIS` that maps each `equipment_type` to its default KPI list. This mapping SHALL cover all equipment types: `all`, `rotating_machinery`, `static_equipment`, `pump`, `reciprocating_machinery`. The mapping SHALL be the sole source of KPI metadata for Round 1.5 form generation.

#### Scenario: KPI metadata available for all equipment types

- **WHEN** Round 1.5 processes a device selection with `equipment_type="pump"`
- **THEN** the skill SHALL retrieve the KPI list from `_EQUIPMENT_TYPE_DEFAULT_KPIS["pump"]`
- **AND** the KPI list SHALL include all KPIs relevant to pump equipment

#### Scenario: Static mapping covers all equipment types

- **WHEN** the static mapping is loaded
- **THEN** it SHALL contain entries for `all`, `rotating_machinery`, `static_equipment`, `pump`, and `reciprocating_machinery`

### Requirement: Equipment metadata passthrough to generation phase

The daily report skill SHALL pass equipment metadata (equipment IDs, labels, types, equipment_type) from the form interaction phase to the generation phase without re-querying the organization tree. The generation phase SHALL consume this metadata directly.

#### Scenario: No organization tree query in generation phase

- **WHEN** the daily report enters the generation phase after Round 2 confirmation
- **THEN** `detect_equipment_type` SHALL NOT be called
- **AND** `resolve_equipment_by_scope` SHALL NOT be called
- **AND** the equipment metadata from the form payload SHALL be used directly

#### Scenario: Equipment metadata included in direct execution parameters

- **WHEN** the user submits the Round 2 confirmation form
- **THEN** the parameters passed to `report_direct_execute` SHALL include `equipment_ids`, `equipment_labels`, `equipment_type`, and `equipment_meta` (constructed from the device selector payload)

### Requirement: Direct execution for regular entry

After the user submits the Round 2 confirmation form, the daily report skill SHALL invoke `report_direct_execute` directly with the structured parameters, bypassing the Agent-based step-by-step script orchestration.

#### Scenario: Regular entry uses direct execution

- **WHEN** the user submits the Round 2 confirmation form with validated parameters
- **THEN** the skill SHALL call `report_direct_execute(report_type="daily", scope=..., equipment_type=..., compare_with=..., equipment_ids=..., equipment_labels=..., kpi_keys=...)`
- **AND** the skill SHALL NOT invoke `query_daily.py`, `daily_kpi.py`, or `export_report.py` individually via Agent tool calls

## REMOVED Requirements

### Requirement: Round 1.5 KPI metadata from list_equipment script

**Reason**: Replaced by static KPI metadata mapping to eliminate redundant organization tree queries.
**Migration**: Use `_EQUIPMENT_TYPE_DEFAULT_KPIS` static mapping instead of invoking `list_equipment.py --limit 1`.

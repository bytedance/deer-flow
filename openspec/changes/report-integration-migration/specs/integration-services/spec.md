# Integration Services - No New Report Service

## MODIFIED Requirements

### Requirement: No ReportAggregationService added

The system SHALL NOT add a `ReportAggregationService` class. Report data access goes through the CLI bridge (subprocess), not through a service layer class. This is because:

1. Report scripts run as subprocesses and use the CLI bridge — they never import service classes
2. Agent tools for reports are not needed — the report Agent delegates to scripts, not to tools
3. KPI aggregation is adapter-internal knowledge, not a cross-system capability that belongs in a service

The existing service classes (`AssetService`, `MonitoringService`, `AssessmentService`, `CrmService`, `ErpService`) remain unchanged.

#### Scenario: Report data access path

- **WHEN** a report script needs KPI data
- **THEN** it calls `call_capability("monitoring.trend", ...)` for raw data
- **THEN** it calls `call_action("aggregate_kpi", ...)` for KPI computation
- **THEN** it does NOT instantiate any service class

#### Scenario: Agent report tools not added

- **WHEN** the report Agent generates a report
- **THEN** it uses the `run_script` tool to execute report scripts
- **THEN** it does NOT call any report-specific integration tool

### Requirement: Existing services unchanged

The existing service layer (`deerflow/integrations/services/`) SHALL remain unchanged. No new service classes are added for this migration.

`ToolRegistry.initialize()` SHALL NOT register any report aggregation tool.

#### Scenario: Service registry unchanged

- **WHEN** `ToolRegistry.initialize()` is called
- **THEN** the same 5 service instances are registered as before
- **THEN** no new report-related tools are available to agents

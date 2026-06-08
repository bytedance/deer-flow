# custom-report-template-engine Specification

## Purpose

Defines the DSL template engine scope after the architecture refactor. The DSL engine (`report_templates/runtime/`) is now scoped exclusively to custom/user-created report templates and is no longer used by builtin reports (daily, weekly, monthly), which use the direct executor instead.

## Requirements

### Requirement: DSL engine scoped to custom reports

The DSL template engine (`report_templates/runtime/`) SHALL only be activated for agents whose name does not match the builtin report agent name pattern (`ai-report--daily`, `ai-report--weekly`, `ai-report--monthly`).

#### Scenario: Custom agent uses DSL tools

- **WHEN** an agent named `ai-report--custom` calls `report_template_prepare_run`
- **THEN** the DSL runtime SHALL process the call normally, creating a `status.json` and advancing through the state machine

#### Scenario: Builtin agent blocked from DSL tools

- **WHEN** an agent named `ai-report--daily` calls `report_template_prepare_run`
- **THEN** the tool SHALL return `{"error": {"code": "AGENT_NOT_ALLOWED", "message": "Builtin reports use direct execution. Use report_direct_execute instead."}}`

### Requirement: DSL template API unchanged

The REST API for report templates (`/api/report-templates/*`) SHALL continue to function for user-created and tenant-created templates.

#### Scenario: List user templates

- **WHEN** a user calls `GET /api/report-templates?visibility=private`
- **THEN** the API SHALL return the user's custom templates (excluding builtin templates, which are read-only)

#### Scenario: Publish custom template

- **WHEN** a user calls `POST /api/report-templates/{id}/publish`
- **THEN** the template SHALL be validated against the DSL schema and a new immutable version snapshot SHALL be created

### Requirement: DSL tools available only to custom agents

The `report_template_*` tool family (14 tools across `report_template_tools.py` and `report_template_runtime_tools.py`) SHALL only be bound to agents that are not builtin report agents.

#### Scenario: Tool binding for custom agent

- **WHEN** `get_available_tools()` is called for an `ai-report--custom` agent
- **THEN** the returned tool set SHALL include all 14 `report_template_*` tools

#### Scenario: Tool binding for builtin agent

- **WHEN** `get_available_tools()` is called for an `ai-report--daily` agent
- **THEN** the returned tool set SHALL NOT include any `report_template_*` tools, but SHALL include `report_direct_execute`

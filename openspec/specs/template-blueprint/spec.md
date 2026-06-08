# template-blueprint Specification

## Purpose

Defines the blueprint system for report templates. Blueprints are pre-built template starting points that users can fork to create custom report templates. Each blueprint carries a base DSL, configuration annotations, and an `executor_type` marker that determines which execution path (direct or DSL) the resulting report uses.

## Requirements

### Requirement: Blueprint catalog

The system SHALL provide a catalog of pre-built template blueprints for common report types.

#### Scenario: Browse blueprints

- **WHEN** user navigates to the template creation page
- **THEN** the system SHALL display a blueprint catalog with cards for each blueprint showing: name, description, icon, and "Use Blueprint" button

#### Scenario: Blueprint categories

- **WHEN** user views the blueprint catalog
- **THEN** the catalog SHALL include at minimum these blueprint categories: Equipment Daily Report, Equipment Weekly Report, Fault Diagnosis, Trend Analysis, Failure Analysis, Closure Summary, and Inspection Report

### Requirement: Create template from blueprint

The system SHALL allow users to create new templates by starting from a blueprint.

#### Scenario: Create from blueprint

- **WHEN** user clicks "Use Blueprint" on a blueprint card
- **THEN** the system SHALL open the visual template editor with the blueprint's DSL pre-filled, highlight fields that need user configuration, and display a guided setup wizard

#### Scenario: Blueprint pre-fills form steps

- **WHEN** user creates a template from the "Equipment Daily Report" blueprint
- **THEN** the editor SHALL be pre-filled with: scope step (date, equipment_type, compare_with fields), equipment selector step, and KPI selection step -- matching the structure of `agents/builtin/report-templates/daily-equipment/default.yaml`

#### Scenario: Blueprint pre-fills sections

- **WHEN** user creates a template from a blueprint
- **THEN** the editor SHALL be pre-filled with the blueprint's recommended section layout (e.g., overview, kpi_cards, trend, anomalies, recommendations for daily reports)

### Requirement: Blueprint configuration wizard

The system SHALL guide users through configuring the blueprint-specific parts.

#### Scenario: Wizard highlights required fields

- **WHEN** user opens a blueprint-based template
- **THEN** the system SHALL highlight fields marked as "user-configurable" in the blueprint definition with a blue border and tooltip "Configure this field"

#### Scenario: Wizard skip to advanced

- **WHEN** user clicks "Skip to Editor"
- **THEN** the system SHALL close the wizard and display the full visual editor with all blueprint defaults applied

### Requirement: Blueprint definition format

The system SHALL define blueprints using a structured format that extends the DSL with configuration annotations and an executor type marker.

#### Scenario: Blueprint definition structure

- **WHEN** a blueprint is loaded
- **THEN** it SHALL contain: a base DSL (valid DSL v1), a `user_configurable` array listing field paths the user should configure, a `recommended_scripts` array of script registry entries, a `preview_sections` array describing the expected output, and an `executor_type` field (`"direct"` for builtin blueprints, `"dsl"` for user-created blueprints)

#### Scenario: Blueprint from existing builtin template

- **WHEN** system administrator runs the blueprint generation script
- **THEN** the system SHALL reverse-engineer a blueprint from an existing builtin template YAML, marking form fields as user-configurable, preserving data_steps/transforms/sections structure, and setting `executor_type: "direct"`

#### Scenario: Builtin blueprint executor type

- **WHEN** a builtin blueprint (e.g., "Equipment Daily Report") is loaded
- **THEN** the blueprint SHALL have `executor_type: "direct"`, indicating that the builtin report uses direct execution rather than the DSL state machine

### Requirement: Blueprint API

The system SHALL provide API endpoints for blueprint operations.

#### Scenario: List blueprints

- **WHEN** client calls `GET /api/template-blueprints/`
- **THEN** the system SHALL return a list of available blueprints with metadata (name, description, category, icon)

#### Scenario: Get blueprint DSL

- **WHEN** client calls `GET /api/template-blueprints/{blueprint_id}`
- **THEN** the system SHALL return the full blueprint definition including base DSL and configuration annotations

#### Scenario: Create template from blueprint via API

- **WHEN** authenticated user calls `POST /api/template-blueprints/{blueprint_id}/create-template` with a name and visibility
- **THEN** the system SHALL create a new template draft pre-filled with the blueprint's DSL and return the new template ID

### Requirement: Blueprint executor type routing hint

The `executor_type` field in a blueprint definition SHALL serve as a routing hint for the system to determine which execution path to use.

#### Scenario: Direct blueprint cannot use DSL tools

- **WHEN** a blueprint has `executor_type: "direct"`
- **THEN** the system SHALL NOT allow the blueprint to be executed via `report_template_prepare_run` or any other DSL runtime tool

#### Scenario: DSL blueprint cannot use direct executor

- **WHEN** a blueprint has `executor_type: "dsl"`
- **THEN** the system SHALL NOT allow the blueprint to be executed via `report_direct_execute`

### Requirement: Fork converts executor type

When a user forks a builtin blueprint to create a customizable template, the system SHALL convert the executor type from `direct` to `dsl`.

#### Scenario: Fork builtin blueprint to custom template

- **WHEN** user forks a builtin blueprint with `executor_type: "direct"`
- **THEN** the resulting template SHALL have `executor_type: "dsl"` and SHALL be executed via the DSL template engine (not direct execution)

#### Scenario: Forked template uses custom agent

- **WHEN** a forked template is published
- **THEN** the template SHALL be associated with the `ai-report--custom` agent, which binds DSL tools (`report_template_*`) rather than direct execution tools

#### Scenario: Fork API automatic conversion

- **WHEN** client calls `POST /api/report-templates/{id}/fork` on a template whose source blueprint has `executor_type: "direct"`
- **THEN** the API SHALL set the forked template's `executor_type` to `"dsl"` in the template metadata, and the template SHALL be executable only via the DSL runtime

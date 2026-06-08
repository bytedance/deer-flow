## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Blueprint executor type routing hint
The `executor_type` field in a blueprint definition SHALL serve as a routing hint for the system to determine which execution path to use.

#### Scenario: Direct blueprint cannot use DSL tools
- **WHEN** a blueprint has `executor_type: "direct"`
- **THEN** the system SHALL NOT allow the blueprint to be executed via `report_template_prepare_run` or any other DSL runtime tool

#### Scenario: DSL blueprint cannot use direct executor
- **WHEN** a blueprint has `executor_type: "dsl"`
- **THEN** the system SHALL NOT allow the blueprint to be executed via `report_direct_execute`

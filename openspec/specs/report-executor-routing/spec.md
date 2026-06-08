# report-executor-routing Specification

## Purpose

Defines the routing layer that selects the appropriate execution path for report generation. The system reads the agent name to determine whether to use direct execution (builtin tri-reports) or the DSL template engine (custom templates), and injects executor-specific instructions into the agent's system prompt.

## Requirements

### Requirement: Agent name-based executor routing

The system SHALL route report execution based on the agent name. Agents matching the builtin report name pattern SHALL use direct execution; all other report agents SHALL use the DSL template engine.

#### Scenario: Builtin agent routed to direct executor

- **WHEN** a thread is started with agent `ai-report--daily`
- **THEN** the system SHALL bind `report_direct_execute` to the agent's tool set and SHALL NOT bind `report_template_*` tools

#### Scenario: Custom agent routed to DSL engine

- **WHEN** a thread is started with agent `ai-report--custom`
- **THEN** the system SHALL bind all `report_template_*` tools to the agent's tool set and SHALL NOT bind `report_direct_execute`

### Requirement: Router middleware injection

The system SHALL inject executor-specific instructions into the system prompt based on the routing decision.

#### Scenario: Direct execution instructions injected

- **WHEN** the agent is `ai-report--daily` and deep-link parameters are present in the first human message
- **THEN** the system prompt SHALL include instructions to call `report_direct_execute` with parsed parameters, and SHALL NOT include DSL state machine instructions

#### Scenario: DSL execution instructions injected

- **WHEN** the agent is `ai-report--custom` and deep-link parameters are present
- **THEN** the system prompt SHALL include DSL execution instructions (the existing `report_template_*` tool sequence)

### Requirement: Routing is transparent to frontend

The routing decision SHALL NOT affect the frontend. Both direct execution and DSL execution produce the same GenUI output (cards, echart, table, markdown blocks).

#### Scenario: Frontend receives same output format

- **WHEN** a builtin report is generated via direct execution
- **THEN** the frontend SHALL receive the same GenUI block structure (card, echart, table, markdown) as it would from DSL execution, with no indication of which executor was used

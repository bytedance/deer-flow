# interaction-mode-tiers

## Purpose

Defines tiered interaction modes (Basic, Pro, Ultra) for the monitoring agent, controlling the complexity of user input from step-by-step forms to natural language conversation.

## Requirements

### Requirement: Basic interaction — step-by-step forms
At Basic tier, the user SHALL interact with the monitoring agent through a fixed form sequence: device selection → analysis scope → wait for results.

### Requirement: Pro interaction — smart defaults + pre-fill
At Pro tier, the system SHALL pre-fill analysis parameters based on equipment type and historical analysis patterns, reducing the number of manual choices.

#### Scenario: Parameters pre-filled for a pump
- **WHEN** a user selects a pump for monitoring and the agent has `monitoring:pro`
- **THEN** the scope form SHALL pre-select metrics relevant to pumps (vibration_level, pressure, flow_rate, temperature) and set date range to the last 30 days

#### Scenario: User can override pre-filled values
- **WHEN** Pro-tier pre-fills metrics but user wants different ones
- **THEN** the user SHALL be able to modify any pre-filled field before submitting

### Requirement: Ultra interaction — natural language conversation
At Ultra tier, the user SHALL be able to initiate monitoring analysis via free-form natural language without navigating forms. The agent SHALL infer analysis type, time range, and metrics from the conversation context.

#### Scenario: NL request for vibration check
- **WHEN** user types "这台泵最近振动有点高，帮我看看怎么回事"
- **THEN** the agent SHALL infer: equipment=current context, analysis_type=anomaly(+spectrum), metrics=[vibration_level, temperature], date_range=last 30 days, and proceed directly to analysis after confirmation

#### Scenario: Ambiguous NL request requires clarification
- **WHEN** user types "帮我看看设备情况" without specifying equipment or what to check
- **THEN** the agent SHALL ask at most 2 clarifying questions before proceeding

#### Scenario: Ultra NL falls back to forms when needed
- **WHEN** Ultra NL interaction cannot determine required parameters after 2 clarification rounds
- **THEN** the agent SHALL fall back to rendering the scope form with whatever parameters were successfully inferred

## ADDED Requirements

### Requirement: New agents inherit industrial skills
The system SHALL pre-enable industrial skills (`tier=core-industrial`) when creating new custom agents via fork or bootstrap. Agents created from scratch SHALL have industrial skills suggested but not auto-enabled.

#### Scenario: Fork agent with industrial skills
- **WHEN** a user forks an existing agent that has industrial skills enabled
- **THEN** the forked agent inherits all industrial skills from the source agent with `enabled=true`

#### Scenario: Fork agent without skills
- **WHEN** a user forks an agent that has no skills configured
- **THEN** the forked agent is created with default industrial skills pre-enabled: `vibration-fault-diagnosis`, `ins-device-analysis`, `monitoring-analysis`

#### Scenario: Bootstrap new agent
- **WHEN** a user creates a new agent via the bootstrap flow (`setup_agent` tool)
- **THEN** the agent creation dialog displays "Industrial Agent" as the first template option with industrial skills pre-selected

### Requirement: Industrial context in agent SOUL templates
The system SHALL include industrial intelligence context in the default SOUL.md template for new agents. The template SHALL describe industrial workflows, device types, and monitoring scenarios as the primary domain.

#### Scenario: New agent SOUL template
- **WHEN** a user creates a new agent and the system generates the default SOUL.md
- **THEN** the SOUL.md includes an "Industrial Context" section describing the agent's role in industrial intelligence workflows

#### Scenario: Industrial agent template
- **WHEN** a user selects the "Industrial Agent" template during agent creation
- **THEN** the generated SOUL.md includes industrial-specific instructions: prioritize device diagnostics, reference ISO standards, use industrial terminology

### Requirement: Industrial tools prioritized in agent tool list
The system SHALL prioritize industrial-specific tools (device selectors, monitoring point queries, equipment data access) at the top of the tool list for agents with industrial skills enabled.

#### Scenario: Agent tool ordering with industrial skills
- **WHEN** an agent has industrial skills enabled (`tier=core-industrial`)
- **THEN** the agent's tool list displays industrial tools first: `device_selector`, `monitoring_point_query`, `equipment_data_access`, followed by general tools

#### Scenario: Agent tool ordering without industrial skills
- **WHEN** an agent has no industrial skills enabled
- **THEN** the agent's tool list displays tools in default order (general tools first)

### Requirement: Agent creation UI prioritizes industrial templates
The system SHALL display "Industrial Agent" as the first template option in the agent creation UI. Other templates (General Agent, Research Agent, Data Analysis Agent) SHALL appear as secondary options.

#### Scenario: Agent creation dialog
- **WHEN** a user opens the agent creation dialog
- **THEN** the dialog displays template options in this order: 1. Industrial Agent (featured), 2. General Agent, 3. Research Agent, 4. Data Analysis Agent

#### Scenario: Industrial agent template selection
- **WHEN** a user selects the "Industrial Agent" template
- **THEN** the system pre-fills the agent configuration with: industrial skills enabled, industrial SOUL template, industrial-themed icon

### Requirement: Agent fork preserves industrial configuration
The system SHALL preserve industrial configuration (skills, prompts, tools) when forking an agent. Forked agents SHALL inherit the source agent's industrial-first settings.

#### Scenario: Fork industrial agent
- **WHEN** a user forks an agent that has industrial configuration (skills, SOUL template, tools)
- **THEN** the forked agent inherits all industrial configuration from the source agent

#### Scenario: Fork non-industrial agent
- **WHEN** a user forks an agent that has no industrial configuration
- **THEN** the forked agent is created with default industrial skills pre-enabled (as per Requirement 1)

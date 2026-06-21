## ADDED Requirements

### Requirement: Agents can be hidden from navigation without being disabled
The system SHALL support an agent visibility mode that hides an agent from user-facing navigation and pickers while preserving its enabled runtime availability.

#### Scenario: Hidden agent omitted from builtin agent navigation
- **WHEN** an enabled agent has `visibility: hidden`
- **THEN** the left builtin-agent navigation SHALL omit that agent
- **AND** the agent's `enabled` state SHALL remain unchanged

#### Scenario: Hidden legacy agent does not remove legacy closed-loop workspace
- **WHEN** `defect-closure` has `visibility: hidden` and remains enabled
- **THEN** the legacy `/workspace/closed-loop` navigation item SHALL continue to use the legacy closed-loop availability rules
- **AND** hiding the agent from the builtin-agent list SHALL NOT disable the legacy closed-loop workspace or its APIs

### Requirement: Agents API exposes visibility
The agents API SHALL expose each agent's visibility value so frontend clients can make consistent presentation decisions.

#### Scenario: List agents includes visibility
- **WHEN** the frontend calls `GET /api/agents`
- **THEN** each returned agent SHALL include a `visibility` field
- **AND** missing visibility in older configs SHALL default to `public`

#### Scenario: Frontend type model includes visibility
- **WHEN** frontend code consumes an agent object
- **THEN** the `Agent` type SHALL include `visibility`
- **AND** filtering hidden agents SHALL be explicit at presentation boundaries rather than inside the low-level API fetch function

### Requirement: New visible agent replaces old visible display entry
The system SHALL show the new EHM defect workflow closure agent as the visible "缺陷闭环" builtin agent entry while hiding the legacy `defect-closure` entry.

#### Scenario: Sidebar shows one defect closure agent entry
- **WHEN** both `defect-workflow-closure` and legacy `defect-closure` are enabled
- **AND** legacy `defect-closure` has `visibility: hidden`
- **THEN** the builtin-agent navigation SHALL show `defect-workflow-closure` with display name "缺陷闭环"
- **AND** SHALL NOT show a duplicate visible `defect-closure` entry

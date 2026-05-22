## ADDED Requirements

### Requirement: Primary flow diagram exists and is approved
The system SHALL have a published primary flow diagram that defines DeerFlow's main product chain as "Task/Conversation → Tool/Knowledge → Report/Artifact → Closure/Governance", approved by product, architecture, frontend and backend leads.

#### Scenario: Diagram covers all four stages
- **WHEN** a stakeholder reviews the primary flow diagram
- **THEN** each of the four stages (Task/Conversation, Tool/Knowledge, Report/Artifact, Closure/Governance) is represented with at least one concrete user scenario

#### Scenario: Diagram identifies swimlane responsibilities
- **WHEN** a team member consults the primary flow diagram
- **THEN** the responsibilities of user, product surface, runtime, and gateway are clearly distinguished across all stages

#### Scenario: Diagram approval is documented
- **WHEN** the primary flow is presented for sign-off
- **THEN** product lead, architecture lead, frontend lead, and backend lead all confirm alignment in a traceable record

### Requirement: Open questions are explicitly separated
The system SHALL maintain a separate list of unresolved questions that are excluded from the primary flow definition until resolved.

#### Scenario: Open questions tracked separately
- **WHEN** the primary flow definition is finalized
- **THEN** all unresolved questions are listed in a separate appendix or document, not embedded in the main flow definition

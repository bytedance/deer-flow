## ADDED Requirements

### Requirement: Disputed capabilities are tracked
The system SHALL maintain a register of capabilities whose layer classification is disputed or unresolved.

#### Scenario: Disputed capability is listed
- **WHEN** the boundary review identifies a capability whose classification cannot be agreed upon
- **THEN** it SHALL be explicitly listed in a dispute register with the conflicting viewpoints and the designated decision owner

#### Scenario: Dispute is resolved
- **WHEN** a disputed capability receives a final classification decision
- **THEN** it SHALL be removed from the dispute register and added to the main classification

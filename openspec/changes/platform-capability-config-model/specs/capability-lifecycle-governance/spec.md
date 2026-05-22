## ADDED Requirements

### Requirement: Lifecycle governance is defined per type
The system SHALL define publish, rollback, deactivation, and change responsibility rules for each of the five capability types.

#### Scenario: Each type has defined lifecycle actions
- **WHEN** a platform operator needs to publish, rollback, or deactivate a capability
- **THEN** the required approvals, impact scope, and responsible roles SHALL be defined per capability type

#### Scenario: Change responsibility is clear
- **WHEN** a capability configuration change is proposed
- **THEN** the responsible role for approving and executing the change SHALL be identifiable from the governance rules

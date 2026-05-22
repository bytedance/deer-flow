## ADDED Requirements

### Requirement: Change impact is traceable
The system SHALL provide impact visibility for capability changes, showing which tenants are affected by a publish, override, or deactivation.

#### Scenario: Deactivation impact preview
- **WHEN** an operator attempts to deactivate a global capability
- **THEN** the system SHALL display the list of tenants that will be affected before the deactivation is executed

#### Scenario: Change audit record
- **WHEN** a capability scope change is executed (publish, override, deactivate)
- **THEN** the system SHALL generate an audit record including the operator, timestamp, change type, and affected scope

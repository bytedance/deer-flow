## ADDED Requirements

### Requirement: Detail view shows scope and recent changes
The system SHALL provide a detail view for each capability that shows its full configuration, scope, and recent change history.

#### Scenario: Configurator views capability details
- **WHEN** a configurator clicks on a capability from the list view
- **THEN** they SHALL see the capability's full configuration including base attributes, type-specific extension fields, and scope classification

#### Scenario: Configurator views recent changes
- **WHEN** a configurator views a capability detail
- **THEN** they SHALL see a list of recent changes with timestamps and responsible users

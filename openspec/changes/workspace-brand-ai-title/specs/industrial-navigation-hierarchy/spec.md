## MODIFIED Requirements

### Requirement: Workspace brand in sidebar header
The system SHALL display the workspace sidebar brand as `AI工作台` without the previous `E` square brand icon.

#### Scenario: Expanded workspace sidebar brand
- **WHEN** a user views the workspace sidebar in expanded state
- **THEN** the sidebar header displays `AI工作台`
- **AND** the sidebar header does not display the previous `E` square brand icon

#### Scenario: Collapsed workspace sidebar brand
- **WHEN** a user views the workspace sidebar in collapsed state
- **THEN** the sidebar header does not display the previous `E` square brand icon
- **AND** the sidebar header still provides the sidebar expand/collapse control

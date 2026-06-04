## ADDED Requirements

### Requirement: Todo counts displayed under bell icon

The system SHALL display pending todo counts (anomaly, startup, shutdown) under a single bell icon button instead of three separate labeled badges.

#### Scenario: No pending todos

- **WHEN** all three todo counts are zero
- **THEN** the bell icon is displayed in default/muted color
- **AND** no count badge is shown on the bell

#### Scenario: Some pending todos

- **WHEN** one or more todo counts are greater than zero
- **THEN** the bell icon displays the total count as a badge indicator
- **AND** the bell icon is highlighted in amber/warning color

#### Scenario: Click bell to view details

- **WHEN** user clicks the bell icon
- **THEN** a dropdown panel opens showing three rows:
  - Anomaly (amber) with AlertTriangle icon and count
  - Startup (blue) with Play icon and count
  - Shutdown (gray) with Power icon and count

#### Scenario: Dropdown items are read-only

- **WHEN** the dropdown panel is open
- **THEN** each row displays icon, label, and count as non-interactive information
- **AND** no navigation or action occurs on clicking a row

### Requirement: Data fetching unchanged

The system SHALL continue fetching todo stats from `GET /api/workbench/todo-stats` every 60 seconds.

#### Scenario: Data refresh

- **WHEN** the todo bell component is mounted
- **THEN** it fetches todo stats immediately
- **AND** refreshes every 60 seconds thereafter

# industrial-navigation-hierarchy Specification

## Purpose
TBD - created by archiving change industrial-intelligence-primary-track. Update Purpose after archive.
## Requirements
### Requirement: Industrial workflows in top-level navigation
The system SHALL display industrial workflows (Device Management, Monitoring Analysis, Diagnosis Reports) in top-level navigation positions. These items SHALL appear before general tools (Chat, Research, Data Analysis).

#### Scenario: Workspace navigation order
- **WHEN** a user views the workspace sidebar navigation
- **THEN** the navigation items appear in this order: 1. Device Management, 2. Monitoring Analysis, 3. Diagnosis Reports, 4. Report Templates, 5. Tools (collapsible)

#### Scenario: Navigation icons
- **WHEN** a user views the top-level navigation items
- **THEN** industrial workflow items (Device Management, Monitoring Analysis, Diagnosis Reports) display industrial-themed icons (gear, chart, stethoscope)

### Requirement: General tools in collapsible secondary menu
The system SHALL group general tools (Chat, Research, Data Analysis, Image Generation) in a collapsible "Tools" menu in secondary navigation position. This menu SHALL be collapsed by default.

#### Scenario: Tools menu default state
- **WHEN** a user views the workspace navigation for the first time
- **THEN** the "Tools" menu is collapsed, showing only the "Tools" label with expand icon

#### Scenario: Expand tools menu
- **WHEN** a user clicks the "Tools" menu
- **THEN** the menu expands to show: Chat, Research, Data Analysis, Image Generation

### Requirement: Industrial navigation items cannot be hidden
The system SHALL NOT allow users to hide or remove industrial workflow items (Device Management, Monitoring Analysis, Diagnosis Reports) from the navigation. These items are permanent platform features.

#### Scenario: Navigation customization
- **WHEN** a user opens navigation customization settings
- **THEN** industrial workflow items (Device Management, Monitoring Analysis, Diagnosis Reports) are locked (cannot be unchecked or reordered)

#### Scenario: Navigation item visibility
- **WHEN** a user views the navigation
- **THEN** industrial workflow items are always visible, regardless of user preferences

### Requirement: Industrial navigation deep links
The system SHALL provide deep links to industrial workflows from the landing page and onboarding overlay. Clicking these links SHALL navigate directly to the corresponding industrial workspace view.

#### Scenario: Landing page industrial links
- **WHEN** a user views the landing page
- **THEN** the page displays "Quick Access" links to: Device Management, Monitoring Analysis, Diagnosis Reports

#### Scenario: Onboarding overlay navigation
- **WHEN** a user is in the industrial onboarding overlay and clicks "Go to Device Management"
- **THEN** the system navigates to the Device Management workspace view and closes the overlay

### Requirement: Navigation state persistence
The system SHALL persist the expanded/collapsed state of the "Tools" menu across sessions. Industrial workflow items do not have collapsible state (always visible).

#### Scenario: Tools menu state persistence
- **WHEN** a user expands the "Tools" menu, then refreshes the page
- **THEN** the "Tools" menu remains expanded after page reload

#### Scenario: Industrial items always visible
- **WHEN** a user refreshes the page
- **THEN** industrial workflow items (Device Management, Monitoring Analysis, Diagnosis Reports) remain visible in top-level navigation


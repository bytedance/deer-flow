## ADDED Requirements

### Requirement: Budget usage displayed in settings

The system SHALL provide a "费用用量" (Cost & Quota) section within the workspace settings dialog that displays LLM usage cost and quota status.

#### Scenario: User views budget settings

- **WHEN** user opens settings and navigates to "费用用量"
- **THEN** the system displays daily cost usage (used / limit) with a progress bar, and monthly cost usage (used / limit) with a progress bar

#### Scenario: Quota approaching limit

- **WHEN** usage exceeds 80% of the daily or monthly quota
- **THEN** a warning indicator with alert icon is displayed

#### Scenario: Quota exceeded

- **WHEN** usage has exceeded the quota limit
- **THEN** a critical indicator is displayed with guidance to contact admin

### Requirement: Budget indicator removed from sidebar

The system SHALL NOT display the budget/cost indicator in the sidebar footer.

#### Scenario: Sidebar renders without budget indicator

- **WHEN** the workspace sidebar is rendered
- **THEN** no cost/usage progress bars are displayed in the sidebar footer area

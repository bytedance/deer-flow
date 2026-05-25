## ADDED Requirements

### Requirement: Ticket can be created from report or diagnosis
The system SHALL allow users to create a closure ticket directly from a report result or diagnosis conclusion.

#### Scenario: Create ticket from report
- **WHEN** a user views a report result and clicks "Create Ticket"
- **THEN** a ticket creation form SHALL appear pre-populated with the report context (report ID, run ID, key findings summary)

#### Scenario: Create ticket from diagnosis
- **WHEN** a user views a diagnosis result and clicks "Create Ticket"
- **THEN** a ticket creation form SHALL appear pre-populated with the diagnosis context

## ADDED Requirements

### Requirement: Ticket traces back to source
The system SHALL enable traceability from a closure ticket back to the report result or diagnosis context that triggered it.

#### Scenario: User traces ticket to source report
- **WHEN** a user views a closure ticket
- **THEN** the UI SHALL display a link back to the source report or diagnosis that triggered it

#### Scenario: Source page shows associated tickets
- **WHEN** a user views a report or diagnosis that has associated tickets
- **THEN** the UI SHALL display the list of linked closure tickets

## ADDED Requirements

### Requirement: Report navigates back to source thread
The system SHALL allow users to navigate from a report result or artifact back to the originating thread and run context.

#### Scenario: User navigates from report to source thread
- **WHEN** a user views a report result
- **THEN** the UI SHALL display a link that navigates back to the source thread/run that generated it

#### Scenario: User navigates from artifact to source report
- **WHEN** a user views an artifact
- **THEN** the UI SHALL display a link that navigates back to the report run or thread that generated it

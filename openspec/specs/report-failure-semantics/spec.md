## ADDED Requirements

### Requirement: Report failure scenarios have clear semantics
The system SHALL provide clear error semantics for three failure categories: template invalid, knowledge unavailable, and run interrupted.

#### Scenario: Template invalid error
- **WHEN** a report run fails because the template is deleted or invalid
- **THEN** the error SHALL indicate "Template unavailable" with the template ID and suggest updating or recreating the report configuration

#### Scenario: Knowledge unavailable error
- **WHEN** a report run fails because required knowledge bases are inaccessible
- **THEN** the error SHALL indicate "Knowledge source unavailable" with the knowledge base IDs and whether the issue is permission-based or availability-based

#### Scenario: Run interrupted error
- **WHEN** a report run is interrupted mid-execution (timeout, service restart, crash)
- **THEN** the error SHALL indicate "Run interrupted" and offer a retry option

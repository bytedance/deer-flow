## ADDED Requirements

### Requirement: Ticket state changes preserve source and responsibility
The system SHALL preserve source context and processing responsibility information throughout ticket state transitions.

#### Scenario: Source info survives state change
- **WHEN** a ticket transitions from OPEN to IN_PROGRESS to RESOLVED
- **THEN** the source report/diagnosis reference and the creating user SHALL remain accessible and unchanged

#### Scenario: Responsibility is tracked
- **WHEN** a ticket is assigned or reassigned
- **THEN** the assignment history SHALL be recorded without overwriting the original source information

## ADDED Requirements

### Requirement: Artifact traces back to report run
The system SHALL enable traceability from a report artifact back to the report run that produced it.

#### Scenario: User traces artifact to run
- **WHEN** a user views a report artifact
- **THEN** the UI SHALL display a link or reference to the report run that generated it

#### Scenario: Run traces to template
- **WHEN** a user views a report run
- **THEN** the UI SHALL display which template version was used and allow navigation to the template

## ADDED Requirements

### Requirement: Run context is recorded at generation time
The system SHALL record the template version, trigger context, and knowledge sources at the time of each report run generation.

#### Scenario: Run record includes template version
- **WHEN** a report run is initiated
- **THEN** the run record SHALL capture the template ID and version that was used

#### Scenario: Run record includes knowledge sources
- **WHEN** a report run is initiated
- **THEN** the run record SHALL capture the identifiers of all knowledge bases and documents used as inputs

#### Scenario: Run record includes trigger context
- **WHEN** a report run is initiated
- **THEN** the run record SHALL capture the trigger type (manual, scheduled, event-driven) and the triggering user or event ID

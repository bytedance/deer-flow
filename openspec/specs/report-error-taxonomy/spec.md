## ADDED Requirements

### Requirement: Standardized error codes for template unavailability
The system SHALL use the error code prefix `TEMPLATE_UNAVAILABLE` when a report run's template has been deleted or archived.

#### Scenario: Archived template run shows clear error
- **WHEN** a user views a report run whose template has been archived or deleted
- **THEN** the run record SHALL have `error_code` starting with `TEMPLATE_UNAVAILABLE` and the UI SHALL display a message indicating the template is no longer available

### Requirement: Standardized error codes for knowledge base unavailability
The system SHALL use the error code prefix `KB_UNAVAILABLE` when a knowledge base document required for report generation is inaccessible.

#### Scenario: KB document unavailable shows affected document
- **WHEN** a knowledge base document used during report generation is deleted or becomes inaccessible
- **THEN** the run record SHALL have `error_code` starting with `KB_UNAVAILABLE` and `error_message` SHALL identify the affected document

### Requirement: Standardized error codes for run interruption
The system SHALL use the error code prefix `RUN_INTERRUPTED` when a report run is canceled or times out.

#### Scenario: Canceled run shows interruption error
- **WHEN** a report run is canceled before completion
- **THEN** the run record SHALL have `error_code` starting with `RUN_INTERRUPTED` and `status` SHALL be `canceled`

### Requirement: Standardized error codes for data step failure
The system SHALL use the error code prefix `DATA_STEP_FAILED` when a data step or transform script fails during report generation.

#### Scenario: Failed data step shows step identifier
- **WHEN** a data step script exits with a non-zero code during report generation
- **THEN** the run record SHALL have `error_code` starting with `DATA_STEP_FAILED` and `error_message` SHALL include the step identifier

### Requirement: End-to-end traceability verification test
The system SHALL have at least one automated test that verifies the complete chain from template to artifact.

#### Scenario: Full chain verification test passes
- **WHEN** the test suite runs
- **THEN** a test SHALL create a template, publish a version, simulate a run through all stages (prepare → data → assemble → export), and verify that the run record references the correct template version, the payload contains template and run metadata, and the artifact paths point to existing files

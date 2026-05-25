## ADDED Requirements

### Requirement: Failure classification taxonomy
The system SHALL classify all execution failures into exactly three categories: EXECUTION_FAILED, UPLOAD_FAILED, and EXTERNAL_DEPENDENCY_UNAVAILABLE.

#### Scenario: Execution failure is distinct
- **WHEN** a run fails due to internal processing error (e.g., code exception, timeout)
- **THEN** the system SHALL classify it as EXECUTION_FAILED with a user prompt to retry or contact support

#### Scenario: Upload failure is distinct
- **WHEN** a file upload fails due to network, size limit, or format rejection
- **THEN** the system SHALL classify it as UPLOAD_FAILED with a user prompt to re-upload or check file format

#### Scenario: External dependency failure is distinct
- **WHEN** a run fails because an external service (LLM, RPC, object storage) is unavailable
- **THEN** the system SHALL classify it as EXTERNAL_DEPENDENCY_UNAVAILABLE with a user prompt to wait and retry later

### Requirement: Recoverable actions for each failure type
The system SHALL provide a specific recoverable action for each failure category.

#### Scenario: User sees actionable next step
- **WHEN** a failure state is displayed to the user
- **THEN** the UI SHALL show a distinct next action: retry for EXECUTION_FAILED, re-upload for UPLOAD_FAILED, or wait/retry-later for EXTERNAL_DEPENDENCY_UNAVAILABLE

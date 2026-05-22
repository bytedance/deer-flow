## ADDED Requirements

### Requirement: Layer identification on failure
The system SHALL include a layer identifier in each failure state indicating where the failure occurred: runtime, gateway, or external.

#### Scenario: User identifies failure layer
- **WHEN** a run or upload is in a failed state
- **THEN** the UI SHALL display which layer caused the failure (runtime, gateway, or external)

#### Scenario: Ops can locate failure in logs
- **WHEN** an operator investigates a failure via logs or monitoring
- **THEN** the layer identifier SHALL be present in log events and traceable to the specific service or component

### Requirement: State mapping regression coverage
The system SHALL have regression tests covering key state transitions and error semantics for thread, run, upload, and artifact.

#### Scenario: State transition test coverage
- **WHEN** a state transition occurs for any of thread, run, upload, or artifact
- **THEN** the transition SHALL be covered by an automated regression test

#### Scenario: Failure classification test coverage
- **WHEN** a failure scenario is triggered (execution failure, upload failure, external dependency unavailable)
- **THEN** the failure classification and layer identification SHALL be verified by an automated test

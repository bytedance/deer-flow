## ADDED Requirements

### Requirement: Unified lifecycle states for thread and run
The system SHALL define a unified set of lifecycle states for thread and run objects, where each state has identical name and meaning across frontend and backend.

#### Scenario: States are consistent across layers
- **WHEN** a developer inspects a thread or run state in the API response, database record, and frontend UI
- **THEN** the state name and its meaning are identical in all three locations

#### Scenario: Common states are defined
- **WHEN** a user views a thread or run
- **THEN** the system SHALL display one of the following unambiguous states: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED

### Requirement: Unified lifecycle states for upload
The system SHALL define a unified set of lifecycle states for upload objects, including indexing-related states.

#### Scenario: Upload indexing states are visible
- **WHEN** a user uploads a document
- **THEN** the system SHALL display distinct states for UPLOADING, PENDING_INDEX, INDEXING, INDEXED, and FAILED

### Requirement: Unified lifecycle states for artifact
The system SHALL define a unified set of lifecycle states for artifact objects.

#### Scenario: Artifact states are visible
- **WHEN** a user views an artifact
- **THEN** the system SHALL display its state as GENERATING, READY, or FAILED

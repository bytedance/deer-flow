## ADDED Requirements

### Requirement: Upload to index status is visible
The system SHALL display the full pipeline status from upload through indexing completion.

#### Scenario: User sees indexing progress
- **WHEN** a user uploads a document to a knowledge base
- **THEN** the UI SHALL show the current status: UPLOADING, PENDING_INDEX, INDEXING, INDEXED, or FAILED

#### Scenario: User sees indexing failure reason
- **WHEN** indexing fails
- **THEN** the UI SHALL display the specific failure reason and suggest a recoverable action (e.g., retry, check file format)

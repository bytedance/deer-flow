## MODIFIED Requirements

### Requirement: Upload to index status is visible
The system SHALL display the full pipeline status from upload through indexing completion, including real-time auto-polling until terminal state is reached.

#### Scenario: User sees indexing progress
- **WHEN** a user uploads a document to a knowledge base
- **THEN** the UI SHALL show the current status: PENDING_INDEX, INDEXING, INDEXED, or FAILED

#### Scenario: User sees indexing failure reason
- **WHEN** indexing fails
- **THEN** the UI SHALL display the specific failure reason and suggest a recoverable action (e.g., retry, check file format)

#### Scenario: Frontend auto-polls until terminal state
- **WHEN** a document enters PENDING_INDEX or INDEXING status
- **THEN** the frontend SHALL poll the document status at regular intervals (every 2 seconds) until the status transitions to INDEXED or FAILED

#### Scenario: Frontend stops polling on terminal state
- **WHEN** a document reaches INDEXED or FAILED status
- **THEN** the frontend SHALL stop polling and display the final status without further requests

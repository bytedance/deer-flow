## ADDED Requirements

### Requirement: Upload to index status is visible
The system SHALL display the full pipeline status from upload through indexing completion, including real-time auto-polling until terminal state is reached.

#### Scenario: User sees indexing progress
- **WHEN** a user uploads a document to a knowledge base
- **THEN** the UI SHALL show the current status: UPLOADING, PENDING_INDEX, INDEXING, INDEXED, or FAILED

#### Scenario: User sees indexing failure reason
- **WHEN** indexing fails
- **THEN** the UI SHALL display the specific failure reason and suggest a recoverable action (e.g., retry, check file format)

#### Scenario: Frontend auto-polls until terminal state
- **WHEN** a document enters PENDING_INDEX or INDEXING status
- **THEN** the frontend SHALL poll the document status at regular intervals (every 2 seconds) until the status transitions to INDEXED or FAILED

#### Scenario: Frontend stops polling on terminal state
- **WHEN** a document reaches INDEXED or FAILED status
- **THEN** the frontend SHALL stop polling and display the final status without further requests

### Requirement: KB-level aggregated index statistics
The system SHALL aggregate per-document indexing status into knowledge-base-level statistics accessible via API.

#### Scenario: KB list endpoint includes index summary
- **WHEN** a user lists knowledge bases via `GET /api/knowledge-bases`
- **THEN** each returned KB entry SHALL carry `document_count`, `indexed_count`, and `failed_count` computed from the KB's documents

#### Scenario: KB detail endpoint includes index detail
- **WHEN** a user requests `GET /api/knowledge-bases/{id}`
- **THEN** the response SHALL include per-status document counts, last index timestamp, and recent failure entries

### Requirement: Failure classification in pipeline visibility
The system SHALL classify index failures displayed in the pipeline view by standardized error categories.

#### Scenario: Failed document shows classified error type
- **WHEN** a document's index_status is "failed"
- **THEN** the UI SHALL display the classified failure type alongside the raw error message

#### Scenario: KB detail groups failures by type
- **WHEN** a knowledge base has multiple failed documents
- **THEN** the index stats SHALL group failures by category (e.g., "EMPTY_RESULT: 3, ENCRYPTED_PDF: 1")

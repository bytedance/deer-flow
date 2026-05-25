## ADDED Requirements

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

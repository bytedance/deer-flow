## ADDED Requirements

### Requirement: Index stats endpoint per knowledge base
The system SHALL provide a REST endpoint that returns aggregated indexing statistics for a specific knowledge base.

#### Scenario: Admin queries index stats for a healthy KB
- **WHEN** an authorized user requests `GET /api/knowledge-bases/{id}/index-stats`
- **THEN** the response SHALL include `total`, `ready`, `pending`, `indexing`, `failed`, and `cancelled` document counts

#### Scenario: Index stats include failure classification
- **WHEN** the knowledge base has failed indexing jobs
- **THEN** the response SHALL include `failure_by_type` mapping each error category to its count

#### Scenario: Index stats include timing information
- **WHEN** the knowledge base has completed indexing jobs
- **THEN** the response SHALL include `avg_index_duration_ms` computed from recent completed jobs

### Requirement: Knowledge base list includes index health
The system SHALL include basic indexing health metrics in the knowledge base list and detail responses.

#### Scenario: KB list shows document counts
- **WHEN** an authorized user requests `GET /api/knowledge-bases`
- **THEN** each KB entry SHALL include `document_count`, `indexed_count`, and `failed_count`

#### Scenario: KB detail shows index health summary
- **WHEN** an authorized user requests `GET /api/knowledge-bases/{id}`
- **THEN** the response SHALL include `document_count`, `indexed_count`, `indexing_count`, `failed_count`, `last_indexed_at`, and the 5 most recent failures with document name and error type

### Requirement: Indexing failure classification
The system SHALL classify indexing failures into standardized categories for observability and alerting.

#### Scenario: Conversion error classification
- **WHEN** an indexing job fails due to a document conversion error
- **THEN** the failure SHALL be classified under the corresponding ConversionErrorCode (EMPTY_RESULT, ENCRYPTED_PDF, UNSUPPORTED_FORMAT)

#### Scenario: Embedding dimension mismatch classification
- **WHEN** an indexing job fails due to embedding dimension mismatch
- **THEN** the failure SHALL be classified as DIMENSION_MISMATCH

#### Scenario: Unclassified error falls to OTHER
- **WHEN** an indexing job fails with an unrecognized error message
- **THEN** the failure SHALL be classified as OTHER

### Requirement: Frontend index health panel
The system SHALL display indexing health metrics on the knowledge base detail page.

#### Scenario: Index health panel shows completion rate
- **WHEN** a user views a knowledge base detail page
- **THEN** the UI SHALL display the index completion rate (ready / total) as a percentage

#### Scenario: Index health panel shows recent failures
- **WHEN** the knowledge base has recent indexing failures
- **THEN** the UI SHALL list the failed documents with their failure type and timestamp

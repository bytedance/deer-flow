## MODIFIED Requirements

### Requirement: End-to-end verification path exists
The system SHALL have at least one end-to-end integration test that exercises the complete upload-to-report chain with real pipeline stages, not just structural simulation.

#### Scenario: Full chain integration test passes
- **WHEN** the integration test suite runs
- **THEN** at least one test SHALL complete the full path: upload document → wait for indexing → verify retrieval returns the document → verify report can consume the knowledge

#### Scenario: Index incomplete boundary is tested
- **WHEN** the integration test suite runs
- **THEN** at least one test SHALL verify that documents with PENDING_INDEX or INDEXING status are excluded from retrieval results

#### Scenario: Permission denied boundary is tested
- **WHEN** the integration test suite runs
- **THEN** at least one test SHALL verify that a user without read permission receives a structured access-denied error when attempting retrieval through the report chain

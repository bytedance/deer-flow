## ADDED Requirements

### Requirement: End-to-end verification path exists
The system SHALL have at least one end-to-end verification that covers the complete upload-to-report chain.

#### Scenario: Full chain integration test passes
- **WHEN** the integration test suite runs
- **THEN** at least one test SHALL complete the full path: upload document → wait for indexing → verify retrieval returns the document → verify report can consume the knowledge

## ADDED Requirements

### Requirement: Report run retrieval respects KB permissions
The system SHALL apply knowledge base access control checks when KB data is consumed during report generation, ensuring the same permission model used in workspace and retrieval contexts.

#### Scenario: Report run blocks unauthorized KB access
- **WHEN** a report run attempts to retrieve data from a knowledge base the user does not have read access to
- **THEN** the retrieval SHALL return a structured error indicating "access denied" rather than silently skipping or returning empty results

#### Scenario: Report run permits authorized KB access
- **WHEN** a report run retrieves data from a knowledge base the user has read access to
- **THEN** the retrieval SHALL succeed and return relevant chunks, matching the permission level in workspace and standalone retrieval contexts

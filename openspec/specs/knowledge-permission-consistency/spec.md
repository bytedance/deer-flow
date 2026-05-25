## ADDED Requirements

### Requirement: Knowledge permissions are consistent across chains
The system SHALL ensure knowledge base permissions are applied consistently across workspace, report, and retrieval access paths.

#### Scenario: Permission denied in workspace matches report
- **WHEN** a user lacks permission to a knowledge base in the workspace
- **THEN** the same user SHALL also be denied access to that knowledge base in report generation and retrieval contexts

### Requirement: Report run retrieval respects KB permissions
The system SHALL apply knowledge base access control checks when KB data is consumed during report generation, ensuring the same permission model used in workspace and retrieval contexts.

#### Scenario: Report run blocks unauthorized KB access
- **WHEN** a report run attempts to retrieve data from a knowledge base the user does not have read access to
- **THEN** the retrieval SHALL return a structured error indicating "access denied" rather than silently skipping or returning empty results

#### Scenario: Report run permits authorized KB access
- **WHEN** a report run retrieves data from a knowledge base the user has read access to
- **THEN** the retrieval SHALL succeed and return relevant chunks, matching the permission level in workspace and standalone retrieval contexts

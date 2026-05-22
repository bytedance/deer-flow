## ADDED Requirements

### Requirement: Knowledge permissions are consistent across chains
The system SHALL ensure knowledge base permissions are applied consistently across workspace, report, and retrieval access paths.

#### Scenario: Permission denied in workspace matches report
- **WHEN** a user lacks permission to a knowledge base in the workspace
- **THEN** the same user SHALL also be denied access to that knowledge base in report generation and retrieval contexts

#### Scenario: Permission granted is consistent
- **WHEN** a user is granted access to a knowledge base
- **THEN** the user SHALL have equivalent access level across workspace, report, and retrieval chains

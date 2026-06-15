## MODIFIED Requirements

### Requirement: Migration verifies multi-worker readiness

After migration to PostgreSQL completes, the system SHALL run a verification step that checks all critical backends are accessible.

#### Scenario: Post-migration verification

- **WHEN** the migration script completes the data transfer
- **THEN** the system SHALL connect to PostgreSQL and verify:
  - All ORM tables have the expected row counts
  - BaseStore entries (including memory namespace) are readable
  - Connection pools can be established for all components
  - Redis is reachable (if multi-worker mode)
- **AND** SHALL report a summary: "Migration complete. N tables verified, all checks passed."

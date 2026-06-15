## ADDED Requirements

### Requirement: Migrate all ORM tables from SQLite to PostgreSQL

The system SHALL provide a migration script (`scripts/migrate_sqlite_to_postgres.py`) that migrates all 16 ORM tables from SQLite to PostgreSQL:
- `users`
- `tenants`
- `threads_meta`
- `runs`
- `run_events`
- `knowledge_bases`
- `knowledge_base_documents`
- `index_jobs`
- `kb_permissions`
- `agents`
- `agent_permissions`
- `agent_usage`
- `feedback`
- `tenant_http_connectors`
- `tenant_mcp_servers`
- `closure_tickets`
- `closure_ticket_events`
- `closure_sla_configs`

The migration SHALL be idempotent (safe to re-run) and SHALL preserve all data.

#### Scenario: Successful migration of all tables

- **WHEN** the migration script is executed with valid SQLite and PostgreSQL connection parameters
- **AND** the SQLite database contains data in all 16 tables
- **THEN** the script SHALL migrate all rows from SQLite to PostgreSQL
- **AND** the script SHALL exit with status code 0
- **AND** the script SHALL output a migration report listing the number of rows migrated per table

#### Scenario: Idempotent migration (re-run after partial failure)

- **WHEN** the migration script is executed a second time after a partial failure
- **AND** some tables were already migrated in the first run
- **THEN** the script SHALL skip rows that already exist in PostgreSQL (based on primary key)
- **AND** the script SHALL only migrate rows that are missing
- **AND** the script SHALL exit with status code 0

#### Scenario: Migration with empty SQLite database

- **WHEN** the migration script is executed with an empty SQLite database (no rows in any table)
- **THEN** the script SHALL complete successfully with 0 rows migrated
- **AND** the script SHALL exit with status code 0

### Requirement: Validate migration completeness

The migration script SHALL validate that the number of rows in PostgreSQL matches the number of rows in SQLite for each table. The validation SHALL be performed after migration unless explicitly disabled.

#### Scenario: Validation passes when row counts match

- **WHEN** the migration completes and validation is enabled
- **AND** all tables have matching row counts in SQLite and PostgreSQL
- **THEN** the script SHALL output "Validation passed: all row counts match"
- **AND** the script SHALL exit with status code 0

#### Scenario: Validation fails when row counts differ

- **WHEN** the migration completes and validation is enabled
- **AND** one or more tables have different row counts in SQLite and PostgreSQL
- **THEN** the script SHALL output "Validation failed: row count mismatch for table X"
- **AND** the script SHALL list the mismatched tables with expected vs actual counts
- **AND** the script SHALL exit with status code 1

#### Scenario: Validation can be disabled

- **WHEN** the migration script is executed with the `--skip-validation` flag
- **THEN** the script SHALL NOT perform row count validation
- **AND** the script SHALL exit with status code 0 regardless of row count differences

### Requirement: Support batch migration for large tables

The migration script SHALL support batch processing for large tables to avoid memory exhaustion. The batch size SHALL be configurable via command-line argument (default: 1000 rows per batch).

#### Scenario: Batch migration of large table

- **WHEN** the migration script is executed with `--batch-size 500`
- **AND** a table contains 2500 rows
- **THEN** the script SHALL migrate the table in 5 batches of 500 rows each
- **AND** the script SHALL log progress for each batch (e.g., "Migrated batch 1/5: 500 rows")

#### Scenario: Default batch size

- **WHEN** the migration script is executed without specifying `--batch-size`
- **THEN** the script SHALL use the default batch size of 1000 rows per batch

### Requirement: Provide migration report

The migration script SHALL output a detailed report at the end of migration, including:
- Total number of tables migrated
- Number of rows migrated per table
- Number of rows skipped (already existed) per table
- Validation results (if enabled)
- Total migration duration

#### Scenario: Migration report includes all details

- **WHEN** the migration completes successfully
- **THEN** the script SHALL output a report in the following format:
  ```
  Migration Report
  ================
  Tables migrated: 16
  Duration: 45.2 seconds
  
  Table Breakdown:
  - users: 150 rows migrated, 0 skipped
  - tenants: 5 rows migrated, 0 skipped
  - threads_meta: 1200 rows migrated, 50 skipped
  ...
  
  Validation: PASSED (all row counts match)
  ```

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

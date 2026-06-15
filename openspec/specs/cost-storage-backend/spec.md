## ADDED Requirements

### Requirement: Support PostgreSQL as cost storage backend

The `CostConfig` SHALL support `postgres` as a valid value for the `storage_backend` field, in addition to the existing `json` option. When `storage_backend=postgres`, cost and token usage data SHALL be persisted to the PostgreSQL database using the existing `RunRow` and `AgentUsageRow` ORM models.

#### Scenario: PostgreSQL backend stores cost data in database

- **WHEN** `cost.storage_backend=postgres` is configured
- **AND** a run completes with token usage data
- **THEN** the system SHALL persist the token usage to the `runs` table (via `RunRow.total_tokens`, `RunRow.total_input_tokens`, `RunRow.total_output_tokens`)
- **AND** the system SHALL persist agent-level usage to the `agent_usage` table (via `AgentUsageRow`)
- **AND** the system SHALL NOT write to any JSON file

#### Scenario: JSON backend stores cost data in file (existing behavior)

- **WHEN** `cost.storage_backend=json` is configured
- **AND** a run completes with token usage data
- **THEN** the system SHALL persist the token usage to the `token_usage.json` file (existing behavior)
- **AND** the system SHALL NOT write to the database

#### Scenario: Invalid storage backend is rejected

- **WHEN** `cost.storage_backend=redis` is configured (unsupported value)
- **THEN** the system SHALL raise a `ConfigValidationError` during startup
- **AND** the error message SHALL list the valid options: `json`, `postgres`

### Requirement: Auto-default cost storage backend from database.backend

When `database.backend=postgres` is configured and `cost.storage_backend` is not explicitly set, the system SHALL automatically set `cost.storage_backend=postgres`. This auto-default behavior SHALL be logged at INFO level during startup.

#### Scenario: Auto-default sets cost storage to postgres

- **WHEN** `database.backend=postgres` is configured
- **AND** `cost.storage_backend` is not explicitly set in config.yaml
- **THEN** the system SHALL automatically set `cost.storage_backend=postgres`
- **AND** the startup log SHALL contain an INFO message: "Auto-defaulted cost.storage_backend=postgres from database.backend=postgres"

#### Scenario: Explicit cost storage backend overrides auto-default

- **WHEN** `database.backend=postgres` is configured
- **AND** `cost.storage_backend=json` is explicitly set in config.yaml
- **THEN** the system SHALL use `cost.storage_backend=json` (explicit value takes precedence)
- **AND** the startup log SHALL contain an INFO message: "cost.storage_backend explicitly configured to json (auto-default skipped)"

### Requirement: Migrate existing JSON cost data to PostgreSQL

When switching from `cost.storage_backend=json` to `cost.storage_backend=postgres`, the system SHALL provide a migration path to archive the existing `token_usage.json` files. The migration SHALL:

1. Validate that the JSON data is already present in the ORM tables (`RunRow` and `AgentUsageRow`)
2. Archive the JSON files to a `backups/` directory
3. Log the migration status

#### Scenario: Successful migration of JSON cost data

- **WHEN** the system starts with `cost.storage_backend=postgres`
- **AND** `token_usage.json` files exist in the data directory
- **AND** the JSON data matches the ORM data (within 1% tolerance)
- **THEN** the system SHALL move the JSON files to `backups/token_usage.json.bak`
- **AND** the system SHALL log: "Archived token_usage.json to backups/ (data already in ORM)"

#### Scenario: Migration skipped when JSON and ORM data mismatch

- **WHEN** the system starts with `cost.storage_backend=postgres`
- **AND** `token_usage.json` files exist in the data directory
- **AND** the JSON data differs from the ORM data by more than 1%
- **THEN** the system SHALL NOT archive the JSON files
- **AND** the system SHALL log a WARNING: "token_usage.json data mismatch with ORM, manual review required before archiving"

#### Scenario: Migration skipped when no JSON files exist

- **WHEN** the system starts with `cost.storage_backend=postgres`
- **AND** no `token_usage.json` files exist
- **THEN** the system SHALL skip the migration step
- **AND** the system SHALL log: "No token_usage.json files found, migration skipped"

### Requirement: Multi-worker mode auto-default for cost storage

When `deployment.mode: multi_worker` is active and `cost.storage_backend` is not explicitly set, the system SHALL automatically set `cost.storage_backend=postgres`. This ensures cost data is shared across all workers via PostgreSQL instead of local JSON files.

#### Scenario: Multi-worker mode auto-defaults cost storage to postgres

- **WHEN** `deployment.mode: multi_worker` is active
- **AND** `cost.storage_backend` is not explicitly set in config.yaml
- **THEN** the system SHALL automatically set `cost.storage_backend=postgres`
- **AND** the startup log SHALL contain an INFO message: "Multi-worker mode: auto-defaulted cost.storage_backend=postgres"

#### Scenario: Explicit cost storage backend overrides mode default

- **WHEN** `deployment.mode: multi_worker` is active
- **AND** `cost.storage_backend=json` is explicitly set in config.yaml
- **THEN** the system SHALL use `cost.storage_backend=json` (explicit value takes precedence)
- **AND** the startup log SHALL contain a WARNING: "cost.storage_backend explicitly set to json in multi-worker mode; cost data will not be shared across workers"

#### Scenario: Single-worker mode preserves existing behavior

- **WHEN** `deployment.mode: single_worker` (default)
- **AND** `cost.storage_backend` is not explicitly set
- **THEN** the system SHALL use `cost.storage_backend=json` (existing behavior)

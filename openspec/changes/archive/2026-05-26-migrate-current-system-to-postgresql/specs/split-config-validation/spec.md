## ADDED Requirements

### Requirement: Validate configuration consistency at startup

The system SHALL validate backend configuration consistency during startup. When `database.backend=postgres`, the system SHALL check that all subsystem backends are also set to PostgreSQL-compatible values. The validation behavior SHALL differ based on the deployment environment:

- In production mode (`DEER_FLOW_ENV=production`): The system SHALL reject split backend configurations and refuse to start
- In development mode (default or `DEER_FLOW_ENV=development`): The system SHALL log warnings but allow the application to start

Split backend configurations are defined as:
- `database.backend=postgres` with `cost.storage_backend=json`
- `database.backend=postgres` with `run_events.backend=memory`
- `database.backend=postgres` with `memory.storage_class=FileMemoryStorage`
- `database.backend=postgres` with `rag.vector_store_backend=chroma`

#### Scenario: Production mode rejects split configuration

- **WHEN** `DEER_FLOW_ENV=production` is set
- **AND** `database.backend=postgres` is configured
- **AND** `cost.storage_backend=json` is configured
- **THEN** the system SHALL raise a `ConfigValidationError` during startup
- **AND** the error message SHALL list all conflicting configurations
- **AND** the application SHALL NOT start

#### Scenario: Development mode warns about split configuration

- **WHEN** `DEER_FLOW_ENV=development` is set (or not set)
- **AND** `database.backend=postgres` is configured
- **AND** `cost.storage_backend=json` is configured
- **THEN** the system SHALL log a WARNING message listing all conflicting configurations
- **AND** the application SHALL start normally

#### Scenario: Consistent configuration passes validation

- **WHEN** `database.backend=postgres` is configured
- **AND** all subsystem backends are set to PostgreSQL-compatible values (`db`, `StoreMemoryStorage`, `pgvector`, `postgres`)
- **THEN** the system SHALL pass validation without errors or warnings
- **AND** the application SHALL start normally

#### Scenario: SQLite backend skips validation

- **WHEN** `database.backend=sqlite` is configured
- **THEN** the system SHALL NOT perform split backend validation
- **AND** the application SHALL start regardless of subsystem backend settings

### Requirement: Provide actionable error messages

Validation error messages SHALL include:
- The list of conflicting configurations
- The recommended fix (e.g., "Set cost.storage_backend=postgres or remove explicit configuration to allow auto-default")
- A link to the migration documentation

#### Scenario: Error message includes actionable guidance

- **WHEN** validation fails due to `database.backend=postgres` and `cost.storage_backend=json`
- **THEN** the error message SHALL include:
  - The conflicting configuration: `cost.storage_backend=json`
  - The recommended fix: "Set cost.storage_backend=postgres or remove to auto-default"
  - A documentation link: "See docs/POSTGRESQL_MIGRATION.md#configuration"

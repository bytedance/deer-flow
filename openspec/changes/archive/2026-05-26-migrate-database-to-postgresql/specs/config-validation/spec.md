## ADDED Requirements

### Requirement: Configuration consistency validation
The system SHALL validate storage configuration consistency at startup and reject invalid combinations.

#### Scenario: PostgreSQL mode validation
- **WHEN** system starts with `database.backend=postgres`
- **THEN** system validates `run_events.backend` is set to `db`
- **AND** system validates `memory.storage_class` is set to `StoreMemoryStorage`
- **AND** system validates `rag.vector_store_backend` is set to `pgvector` if RAG is enabled
- **AND** system fails startup with clear error if validation fails

#### Scenario: Split configuration rejection
- **WHEN** system starts with `database.backend=postgres` but `run_events.backend=memory`
- **THEN** system logs error message explaining configuration conflict
- **AND** system fails startup
- **AND** error message suggests correct configuration

#### Scenario: SQLite mode validation
- **WHEN** system starts with `database.backend=sqlite`
- **THEN** system allows `run_events.backend=memory`
- **AND** system allows `memory.storage_class=FileMemoryStorage`
- **AND** system allows `rag.vector_store_backend=chroma`

### Requirement: Deprecation warnings
The system SHALL emit deprecation warnings for obsolete configuration sections.

#### Scenario: Deprecated checkpointer config
- **WHEN** system starts with standalone `checkpointer` configuration section
- **THEN** system logs deprecation warning
- **AND** warning message explains that `checkpointer` is deprecated
- **AND** warning message directs user to use `database.backend` instead
- **AND** system continues to function using deprecated config

#### Scenario: Deprecated config documentation
- **WHEN** deprecation warning is logged
- **THEN** warning includes link to migration documentation
- **AND** warning specifies version when config will be removed

### Requirement: Auto-default configuration
The system SHALL automatically set appropriate defaults for subsystems based on `database.backend` setting.

#### Scenario: PostgreSQL auto-defaults
- **WHEN** system starts with `database.backend=postgres` and subsystem configs are not explicitly set
- **THEN** system defaults `run_events.backend` to `db`
- **AND** system defaults `cost.storage_backend` to `postgres`
- **AND** system defaults `memory.storage_class` to `StoreMemoryStorage`
- **AND** system defaults `rag.vector_store_backend` to `pgvector`

#### Scenario: SQLite auto-defaults
- **WHEN** system starts with `database.backend=sqlite` and subsystem configs are not explicitly set
- **THEN** system defaults `run_events.backend` to `memory`
- **AND** system defaults `cost.storage_backend` to `json`
- **AND** system defaults `memory.storage_class` to `FileMemoryStorage`
- **AND** system defaults `rag.vector_store_backend` to `chroma`

### Requirement: Configuration validation error messages
The system SHALL provide clear, actionable error messages for configuration validation failures.

#### Scenario: Missing PostgreSQL URL
- **WHEN** system starts with `database.backend=postgres` but `postgres_url` is empty
- **THEN** system logs error explaining PostgreSQL URL is required
- **AND** error message shows example configuration
- **AND** system fails startup

#### Scenario: Missing extension
- **WHEN** system connects to PostgreSQL but `vector` extension is not installed
- **THEN** system logs error explaining extension requirement
- **AND** error message shows SQL command to install extension
- **AND** system fails startup

## ADDED Requirements

### Requirement: Auto-default subsystem backends from database.backend

When `database.backend` is set to `postgres`, the system SHALL automatically set the following subsystem backends to PostgreSQL-compatible values if they are not explicitly configured:
- `run_events.backend` SHALL be set to `db`
- `memory.storage_class` SHALL be set to `StoreMemoryStorage`
- `rag.vector_store_backend` SHALL be set to `pgvector`
- `cost.storage_backend` SHALL be set to `postgres`

The auto-default logic SHALL only apply when a subsystem backend is not explicitly set in the configuration. Explicit configuration SHALL always take precedence over auto-defaults.

#### Scenario: All subsystems auto-default to PostgreSQL

- **WHEN** `database.backend=postgres` is set in config.yaml
- **AND** no subsystem backends are explicitly configured
- **THEN** the system SHALL use `run_events.backend=db`, `memory.storage_class=StoreMemoryStorage`, `rag.vector_store_backend=pgvector`, and `cost.storage_backend=postgres`

#### Scenario: Explicit configuration overrides auto-default

- **WHEN** `database.backend=postgres` is set in config.yaml
- **AND** `cost.storage_backend=json` is explicitly configured
- **THEN** the system SHALL use `cost.storage_backend=json` (explicit value takes precedence)

#### Scenario: SQLite backend does not trigger auto-defaults

- **WHEN** `database.backend=sqlite` is set in config.yaml
- **THEN** the system SHALL NOT modify any subsystem backend configurations

#### Scenario: Memory backend does not trigger auto-defaults

- **WHEN** `database.backend=memory` is set in config.yaml
- **THEN** the system SHALL NOT modify any subsystem backend configurations

### Requirement: Log auto-default decisions

The system SHALL log all auto-default decisions at INFO level during startup, including which subsystems were auto-defaulted and which were explicitly configured.

#### Scenario: Log shows auto-defaulted subsystems

- **WHEN** the system starts with `database.backend=postgres` and auto-defaults 3 subsystems
- **THEN** the startup log SHALL contain INFO messages listing each auto-defaulted subsystem and its new value

#### Scenario: Log shows explicitly configured subsystems

- **WHEN** the system starts with `database.backend=postgres` and `cost.storage_backend=json` explicitly set
- **THEN** the startup log SHALL contain an INFO message indicating that `cost.storage_backend` was explicitly configured and not auto-defaulted

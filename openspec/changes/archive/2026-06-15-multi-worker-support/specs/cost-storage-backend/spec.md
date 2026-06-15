## MODIFIED Requirements

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

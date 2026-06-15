## ADDED Requirements

### Requirement: Opt-in multi-worker deployment mode

The system SHALL provide a `deployment.mode` configuration field (default: `"single_worker"`) and a `DEER_FLOW_MULTI_WORKER=1` environment variable. When multi-worker mode is activated, all stateful components SHALL automatically switch to shared backends (PostgreSQL + Redis), unless explicitly overridden by the user.

#### Scenario: Multi-worker mode via config

- **WHEN** `config.yaml` contains `deployment.mode: multi_worker`
- **THEN** the system SHALL switch all stateful components to shared backends:
  - `database.backend` → `postgres`
  - `stream_bridge.type` → `redis`
  - `rag.vector_store_backend` → `pgvector`
  - `rate_limit.backend` → `redis`
  - `cost.storage_backend` → `postgres`
  - `indexing.dispatcher_mode` → `queue`
  - `im.coordination_mode` → `redis`
  - `memory.storage_class` → `StoreMemoryStorage`

#### Scenario: Multi-worker mode via environment variable

- **WHEN** `DEER_FLOW_MULTI_WORKER=1` is set
- **THEN** the system SHALL behave as if `deployment.mode: multi_worker` is configured

#### Scenario: Explicit config overrides mode defaults

- **WHEN** `deployment.mode: multi_worker` is set
- **AND** `config.yaml` explicitly sets `database.backend: memory`
- **THEN** the system SHALL use `memory` for database (explicit value takes precedence)
- **AND** SHALL log a warning that an explicit override may break multi-worker functionality

#### Scenario: Single-worker mode preserves existing behavior

- **WHEN** `deployment.mode` is `"single_worker"` (default) or not configured
- **THEN** the system SHALL use existing defaults for all components (memory, chroma, json, etc.)
- **AND** behavior SHALL be identical to current production deployments

### Requirement: Config unification with existing _apply_database_defaults

The `deployment.mode: multi_worker` mechanism SHALL be implemented as an extension of the existing `_apply_database_defaults()` method in `app_config.py`. When multi-worker mode is active, the method SHALL additionally override non-database subsystems (stream_bridge, indexing, im). When only `database.backend=postgres` is set (without multi-worker mode), the existing auto-default logic SHALL continue to apply.

#### Scenario: Config priority order

- **WHEN** both `deployment.mode: multi_worker` and `database.backend=postgres` are set
- **THEN** the system SHALL apply multi-worker overrides for all components
- **AND** SHALL NOT double-apply or conflict

#### Scenario: database.backend=postgres without multi-worker mode

- **WHEN** `database.backend=postgres` is set
- **AND** `deployment.mode` is `"single_worker"` (default)
- **THEN** the existing auto-default logic SHALL apply (memory.storage_class → StoreMemoryStorage, rag → pgvector, cost → postgres)
- **AND** non-database subsystems (stream_bridge, indexing, im) SHALL NOT be overridden

### Requirement: Startup validation in multi-worker mode

When multi-worker mode is active, the system SHALL validate that all required shared backends are reachable at startup. If any critical backend is unavailable, the system SHALL fail to start with a clear error message.

#### Scenario: PostgreSQL required in multi-worker mode

- **WHEN** `deployment.mode: multi_worker` is set
- **AND** PostgreSQL is unreachable
- **THEN** the system SHALL log an error: "Multi-worker mode requires PostgreSQL. Connection failed"
- **AND** SHALL exit with non-zero status code

#### Scenario: Redis required in multi-worker mode

- **WHEN** `deployment.mode: multi_worker` is set
- **AND** Redis is unreachable
- **THEN** the system SHALL log an error: "Multi-worker mode requires Redis. Connection failed"
- **AND** SHALL exit with non-zero status code

#### Scenario: Single-worker mode skips shared backend validation

- **WHEN** `deployment.mode: single_worker` (default)
- **THEN** the system SHALL NOT require PostgreSQL or Redis
- **AND** SHALL start normally with in-memory/file backends

### Requirement: Development mode convenience

The system SHALL provide a `DEER_FLOW_DEV_MODE=1` environment variable as an alias for single-worker mode with all in-memory/file defaults. This enables local development without PostgreSQL/Redis.

#### Scenario: Dev mode uses all local backends

- **WHEN** `DEER_FLOW_DEV_MODE=1` is set
- **THEN** the system SHALL use `memory` for database, stream bridge, rate limit; `chroma` for vector store; `FileMemoryStorage` for agent memory
- **AND** SHALL log a WARNING: "Development mode active. Not suitable for production."

#### Scenario: Dev mode equivalent to single-worker defaults

- **WHEN** `DEER_FLOW_DEV_MODE=1` is set
- **THEN** behavior SHALL be identical to `deployment.mode: single_worker` with all default backends

### Requirement: Worker ID in logs

Each worker process SHALL include a unique `worker_id` (short UUID, 8 chars) in all log messages. This enables debugging and monitoring in multi-worker deployments.

#### Scenario: Worker ID appears in log format

- **WHEN** a log message is emitted by any component
- **THEN** the log line SHALL include `[worker_id]` prefix
- **AND** the format SHALL be: `timestamp [worker_id] LEVEL module: message`

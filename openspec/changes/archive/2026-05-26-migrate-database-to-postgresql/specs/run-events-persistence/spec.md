## MODIFIED Requirements

### Requirement: Database-backed run events persistence
The system SHALL persist run events to database when `run_events.backend` is set to `db`.

#### Scenario: Run events storage in PostgreSQL
- **WHEN** `database.backend` is set to `postgres` and `run_events.backend` is set to `db`
- **THEN** system stores all run events in PostgreSQL `run_events` table
- **AND** events persist across restarts
- **AND** events are queryable for audit and debugging

#### Scenario: Run event recording
- **WHEN** agent execution generates events
- **THEN** system records each event with `run_id`, `event_type`, `event_data`, `created_at`
- **AND** system includes `tenant_id` and `thread_id` for filtering
- **AND** system records events asynchronously to avoid blocking execution

#### Scenario: Run events query
- **WHEN** user queries run events for specific run
- **THEN** system retrieves events from database filtered by `run_id`
- **AND** system returns events sorted by `created_at`
- **AND** system supports pagination for large event sets

### Requirement: Run events default to database in PostgreSQL mode
The system SHALL default `run_events.backend` to `db` when `database.backend` is set to `postgres`.

#### Scenario: Auto-default to database backend
- **WHEN** system starts with `database.backend=postgres` and `run_events.backend` is not explicitly set
- **THEN** system defaults `run_events.backend` to `db`
- **AND** system logs configuration decision
- **AND** run events are persisted to PostgreSQL

#### Scenario: Explicit memory backend rejected
- **WHEN** system starts with `database.backend=postgres` and `run_events.backend=memory`
- **THEN** system logs configuration error
- **AND** system fails startup with clear error message
- **AND** error message explains that memory backend is not allowed in PostgreSQL mode

### Requirement: Run events retention policy
The system SHALL support configurable retention policy for run events.

#### Scenario: Retention period configuration
- **WHEN** `run_events.retention_days` is set to 90
- **THEN** system archives or deletes events older than 90 days
- **AND** system runs retention cleanup periodically

#### Scenario: Retention cleanup
- **WHEN** retention cleanup runs
- **THEN** system identifies events older than retention period
- **AND** system deletes or archives old events
- **AND** system logs number of events cleaned up

### Requirement: Run events query performance
The system SHALL provide efficient run events queries with appropriate indexes.

#### Scenario: Run ID query
- **WHEN** querying events for specific run
- **THEN** query uses index on `run_id`
- **AND** query completes within acceptable latency

#### Scenario: Thread events query
- **WHEN** querying events for specific thread
- **THEN** query uses index on `(thread_id, created_at DESC)`
- **AND** query returns events sorted by timestamp

#### Scenario: Tenant events query
- **WHEN** querying events for specific tenant
- **THEN** query uses index on `(tenant_id, created_at DESC)`
- **AND** query supports filtering by event type

### Requirement: Run events backward compatibility
The system SHALL maintain backward compatibility with memory backend for SQLite mode.

#### Scenario: Memory backend in SQLite mode
- **WHEN** `database.backend` is set to `sqlite` and `run_events.backend` is set to `memory`
- **THEN** system uses in-memory event storage
- **AND** events are lost on restart
- **AND** system logs warning about non-persistent events

## ADDED Requirements

### Requirement: PostgreSQL as primary storage backend
The system SHALL use PostgreSQL as the primary storage backend for all structured business data, runtime state, and operational data when `database.backend` is set to `postgres`.

#### Scenario: PostgreSQL mode initialization
- **WHEN** system starts with `database.backend=postgres`
- **THEN** all structured data tables are created in PostgreSQL
- **AND** LangGraph checkpointer uses PostgreSQL
- **AND** LangGraph store uses PostgreSQL
- **AND** run events are persisted to PostgreSQL

#### Scenario: Multi-instance state consistency
- **WHEN** multiple application instances connect to the same PostgreSQL database
- **THEN** all instances see consistent thread state
- **AND** all instances see consistent user data
- **AND** all instances see consistent run events

### Requirement: Connection pooling
The system SHALL manage PostgreSQL connections using connection pooling with configurable pool size.

#### Scenario: Connection pool configuration
- **WHEN** `database.pool_size` is set to 20
- **THEN** system creates a connection pool with 20 connections
- **AND** connections are reused across requests

#### Scenario: Connection pool exhaustion handling
- **WHEN** all connections in the pool are in use
- **THEN** new requests wait for an available connection
- **AND** system logs a warning if wait time exceeds threshold

### Requirement: PostgreSQL extension dependencies
The system SHALL require and validate the presence of necessary PostgreSQL extensions.

#### Scenario: Required extensions check
- **WHEN** system initializes PostgreSQL backend
- **THEN** system verifies `vector` extension is installed
- **AND** system verifies `pgcrypto` extension is installed
- **AND** system fails startup with clear error if extensions are missing

### Requirement: Schema migration management
The system SHALL manage PostgreSQL schema migrations using Alembic for application tables.

#### Scenario: Initial schema creation
- **WHEN** system connects to empty PostgreSQL database
- **THEN** Alembic creates all application tables
- **AND** Alembic creates migration version table
- **AND** system logs successful schema initialization

#### Scenario: Schema version upgrade
- **WHEN** system starts with outdated schema version
- **THEN** Alembic applies pending migrations
- **AND** system logs each migration applied
- **AND** system fails startup if migration fails

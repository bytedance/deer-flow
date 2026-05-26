## MODIFIED Requirements

### Requirement: PostgreSQL connection configuration
The system SHALL support PostgreSQL connection configuration with connection pooling and SSL options.

#### Scenario: PostgreSQL URL configuration
- **WHEN** `database.backend` is set to `postgres`
- **THEN** system reads `postgres_url` from configuration
- **AND** system supports standard PostgreSQL URL format: `postgresql://user:pass@host:port/database`
- **AND** system automatically adds `+asyncpg` driver suffix for SQLAlchemy async engine

#### Scenario: Connection pool configuration
- **WHEN** `database.pool_size` is set
- **THEN** system creates connection pool with specified size
- **AND** system uses pool for all database operations
- **AND** system logs pool statistics periodically

#### Scenario: Environment variable resolution
- **WHEN** `postgres_url` contains `$DATABASE_URL` placeholder
- **THEN** system resolves value from environment variable
- **AND** system fails startup with clear error if environment variable is not set

### Requirement: Dual-mode backend support
The system SHALL support both SQLite and PostgreSQL backends through configuration.

#### Scenario: SQLite mode
- **WHEN** `database.backend` is set to `sqlite`
- **THEN** system uses SQLite database file at `sqlite_dir/deerflow.db`
- **AND** system enables WAL journal mode
- **AND** system sets 5-second busy timeout

#### Scenario: PostgreSQL mode
- **WHEN** `database.backend` is set to `postgres`
- **THEN** system uses PostgreSQL connection from `postgres_url`
- **AND** system creates connection pool with `pool_size` connections
- **AND** system enables SQL echo if `echo_sql` is true

#### Scenario: Memory mode
- **WHEN** `database.backend` is set to `memory`
- **THEN** system uses in-memory storage
- **AND** system does not persist data across restarts
- **AND** system is suitable for testing only

### Requirement: Checkpointer backend follows database backend
The system SHALL automatically configure LangGraph checkpointer backend based on `database.backend` setting.

#### Scenario: Checkpointer follows PostgreSQL
- **WHEN** `database.backend` is set to `postgres`
- **THEN** LangGraph checkpointer uses PostgreSQL backend
- **AND** checkpointer shares same connection pool as application
- **AND** checkpointer tables are created automatically

#### Scenario: Checkpointer follows SQLite
- **WHEN** `database.backend` is set to `sqlite`
- **THEN** LangGraph checkpointer uses SQLite backend
- **AND** checkpointer shares same database file as application
- **AND** checkpointer tables are created automatically

### Requirement: Store backend follows database backend
The system SHALL automatically configure LangGraph store backend based on `database.backend` setting.

#### Scenario: Store follows PostgreSQL
- **WHEN** `database.backend` is set to `postgres`
- **THEN** LangGraph store uses PostgreSQL backend
- **AND** store shares same connection pool as application
- **AND** store tables are created automatically

#### Scenario: Store follows SQLite
- **WHEN** `database.backend` is set to `sqlite`
- **THEN** LangGraph store uses SQLite backend
- **AND** store shares same database file as application
- **AND** store tables are created automatically

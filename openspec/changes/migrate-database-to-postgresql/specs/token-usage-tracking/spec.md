## MODIFIED Requirements

### Requirement: PostgreSQL-backed token usage storage
The system SHALL store token usage data in PostgreSQL table when `cost.storage_backend` is set to `postgres`.

#### Scenario: Token usage recording
- **WHEN** LLM generates response
- **THEN** system records token usage in `token_usage` table
- **AND** record includes `tenant_id`, `user_id`, `thread_id`, `run_id`
- **AND** record includes `model_name`, `input_tokens`, `output_tokens`, `total_tokens`
- **AND** record includes `cost_usd` and `created_at`

#### Scenario: Token usage aggregation
- **WHEN** user queries token usage statistics
- **THEN** system aggregates usage by tenant, user, or thread
- **AND** system filters by date range
- **AND** system returns total tokens and cost

#### Scenario: Token usage retention
- **WHEN** token usage records exceed retention period
- **THEN** system archives or deletes old records
- **AND** system maintains configurable retention policy (default 90 days)

### Requirement: Token usage ORM model
The system SHALL define token usage as formal ORM model managed by Alembic.

#### Scenario: Token usage table schema
- **WHEN** Alembic migration creates `token_usage` table
- **THEN** table includes columns: `id`, `tenant_id`, `user_id`, `thread_id`, `run_id`, `model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd`, `created_at`
- **AND** table has primary key on `id`
- **AND** table has indexes on `(tenant_id, created_at DESC)`, `(thread_id, created_at DESC)`, `(user_id, created_at DESC)`

#### Scenario: Token usage repository
- **WHEN** system needs to query token usage
- **THEN** system uses `TokenUsageRepository` for CRUD operations
- **AND** repository provides methods for aggregation and filtering
- **AND** repository handles pagination for large result sets

### Requirement: JSON file migration to PostgreSQL
The system SHALL support migrating existing `token_usage.json` data to PostgreSQL table.

#### Scenario: Token usage JSON migration
- **WHEN** token usage migration script is executed
- **THEN** script reads all records from `token_usage.json`
- **AND** script inserts records into PostgreSQL `token_usage` table
- **AND** script validates record count matches
- **AND** script is idempotent (can be run multiple times safely)

#### Scenario: Migration validation
- **WHEN** token usage migration completes
- **THEN** script validates total token count matches
- **AND** script validates total cost matches
- **AND** script spot-checks sample records

### Requirement: Token usage query performance
The system SHALL provide efficient token usage queries with appropriate indexes.

#### Scenario: Tenant usage query
- **WHEN** querying token usage for specific tenant
- **THEN** query uses index on `(tenant_id, created_at DESC)`
- **AND** query completes within acceptable latency

#### Scenario: Thread usage query
- **WHEN** querying token usage for specific thread
- **THEN** query uses index on `(thread_id, created_at DESC)`
- **AND** query returns usage sorted by timestamp

#### Scenario: Date range query
- **WHEN** querying token usage for date range
- **THEN** query uses index on `created_at` column
- **AND** query efficiently filters by date range

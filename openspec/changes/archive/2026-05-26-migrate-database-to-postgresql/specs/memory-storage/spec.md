## MODIFIED Requirements

### Requirement: Store-backed memory storage
The system SHALL use LangGraph Store as the primary memory storage backend when `memory.storage_class` is set to `StoreMemoryStorage`.

#### Scenario: Memory storage in PostgreSQL mode
- **WHEN** `database.backend` is set to `postgres`
- **THEN** system defaults `memory.storage_class` to `StoreMemoryStorage`
- **AND** memory data is stored in LangGraph Store tables in PostgreSQL
- **AND** memory data persists across restarts

#### Scenario: Memory namespace isolation
- **WHEN** memory is stored in LangGraph Store
- **THEN** each user's memory is stored in separate namespace
- **AND** each agent's memory is stored in separate namespace
- **AND** memory data is isolated by `(user_id, agent_name)` tuple

#### Scenario: Memory data retrieval
- **WHEN** agent needs to inject memory into prompt
- **THEN** system retrieves memory from Store using `(user_id, agent_name)` key
- **AND** system returns top 15 facts plus context summaries
- **AND** system caches memory data to avoid repeated Store queries

### Requirement: File-based memory fallback
The system SHALL support file-based memory storage as fallback when Store is not available.

#### Scenario: Memory storage in SQLite mode
- **WHEN** `database.backend` is set to `sqlite`
- **THEN** system defaults `memory.storage_class` to `FileMemoryStorage`
- **AND** memory data is stored in `{base_dir}/users/{user_id}/memory.json`
- **AND** memory data persists across restarts

#### Scenario: Per-agent memory files
- **WHEN** custom agent has separate memory
- **THEN** system stores memory in `{base_dir}/users/{user_id}/agents/{agent_name}/memory.json`
- **AND** memory is isolated per agent

### Requirement: Memory migration from files to Store
The system SHALL support migrating existing file-based memory data to Store.

#### Scenario: Memory migration script
- **WHEN** memory migration script is executed
- **THEN** script reads `memory.json` for each user
- **AND** script writes memory data to Store namespace `(user_id, agent_name)`
- **AND** script validates memory data is retrievable from Store

#### Scenario: Memory data preservation
- **WHEN** memory is migrated from file to Store
- **THEN** all user context is preserved
- **AND** all facts are preserved with metadata
- **AND** all history summaries are preserved

### Requirement: Memory cache invalidation
The system SHALL invalidate memory cache when underlying storage changes.

#### Scenario: Cache invalidation on update
- **WHEN** memory is updated in Store
- **THEN** system invalidates cache for affected `(user_id, agent_name)` key
- **AND** next memory retrieval reads fresh data from Store

#### Scenario: Cache key includes user and agent
- **WHEN** memory is cached
- **THEN** cache key includes both `user_id` and `agent_name`
- **AND** different users' memory is cached separately
- **AND** different agents' memory is cached separately

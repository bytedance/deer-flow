## ADDED Requirements

### Requirement: Agent Memory cross-worker sharing via StoreMemoryStorage

When multi-worker mode is active, Agent Memory SHALL use the existing `StoreMemoryStorage` class with PostgreSQL `AsyncPostgresStore` as the backend. Memory data SHALL be stored in the LangGraph BaseStore `store_items` table under namespace `("memory", tenant_id, user_id, agent_name)` with key `"data"`. No new storage class or database table SHALL be created.

#### Scenario: Multi-worker memory sharing

- **WHEN** `deployment.mode: multi_worker` is active
- **AND** `database.backend=postgres`
- **THEN** `get_memory_storage()` SHALL return a `StoreMemoryStorage` instance
- **AND** the underlying store SHALL be `AsyncPostgresStore` connected to the shared PostgreSQL instance
- **AND** Worker A's memory writes SHALL be visible to Worker B

#### Scenario: Single-worker mode preserves existing behavior

- **WHEN** `deployment.mode: single_worker` (default)
- **THEN** `get_memory_storage()` SHALL follow the existing priority: StoreMemoryStorage (if store factory available) → FileMemoryStorage (fallback)

### Requirement: Optimistic merge for concurrent writes

When `StoreMemoryStorage.save()` is called from the memory updater, the system SHALL perform a read-merge-write operation at the application layer (before calling `save()`) to handle concurrent writes from multiple workers. The merge SHALL deduplicate facts by content key (casefold, consistent with existing `_fact_content_key()`) and append new facts.

#### Scenario: Two workers add different facts concurrently

- **WHEN** Worker A saves memory with facts [a, b, c, d]
- **AND** Worker B saves memory with facts [a, b, c, e] at nearly the same time
- **THEN** the final stored facts SHALL contain [a, b, c, d, e] (both new facts preserved)
- **AND** existing facts [a, b, c] SHALL NOT be duplicated

#### Scenario: Save when no existing data

- **WHEN** the memory updater calls save and no data exists for the given (tenant_id, user_id, agent_name)
- **THEN** the system SHALL insert the incoming data directly (no merge needed)

#### Scenario: Merge logic location

- **WHEN** the memory updater saves facts
- **THEN** the merge logic SHALL be in the memory updater layer (not in StoreMemoryStorage)
- **AND** SHALL call `storage.load()` to read current data, merge facts, then call `storage.save()` with merged result

### Requirement: File locking for FileMemoryStorage

When using `FileMemoryStorage` (single-worker mode), the system SHALL use file-level locking (via `filelock`) to prevent data corruption from concurrent access by multiple processes pointing to the same data directory. Intra-process thread synchronization is already handled by the existing `cache_lock` (RLock).

#### Scenario: Concurrent saves across processes

- **WHEN** two processes call `FileMemoryStorage.save()` for the same agent/user simultaneously
- **THEN** file locking SHALL ensure only one write proceeds at a time
- **AND** no data corruption SHALL occur

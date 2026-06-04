## ADDED Requirements

### Requirement: PostgreSQL checkpoint cleanup on thread deletion
When a thread is deleted via `DELETE /api/threads/{thread_id}` and the active checkpointer is a PostgreSQL backend, the system SHALL delete all checkpoint rows for that thread from the `checkpoints`, `checkpoint_writes`, and `checkpoint_blobs` tables.

#### Scenario: PostgreSQL backend deletes all checkpoint rows
- **WHEN** a thread is deleted and the checkpointer is an instance of `AsyncPostgresSaver`
- **THEN** all rows in `checkpoints`, `checkpoint_writes`, and `checkpoint_blobs` with matching `thread_id` are deleted

#### Scenario: SQLite backend uses existing adelete_thread path
- **WHEN** a thread is deleted and the checkpointer has the `adelete_thread` method (e.g., `AsyncSqliteSaver`)
- **THEN** the existing `adelete_thread` path is used and no raw SQL is executed

#### Scenario: Memory backend skips cleanup
- **WHEN** a thread is deleted and the checkpointer is an `InMemorySaver` or similar non-persistent backend
- **THEN** no checkpoint cleanup is attempted

### Requirement: Checkpoint cleanup failure does not block thread deletion
PostgreSQL checkpoint cleanup SHALL be best-effort. A failure during checkpoint deletion MUST log a warning but MUST NOT prevent the thread from being deleted.

#### Scenario: Cleanup failure is non-fatal
- **WHEN** checkpoint cleanup raises an exception (e.g., pool exhausted, connection lost)
- **THEN** the error is logged at warning level and the thread deletion continues to completion

### Requirement: All checkpoint namespaces are cleaned
For PostgreSQL backends, the cleanup SHALL delete checkpoint rows for all `checkpoint_ns` values belonging to the deleted thread. The system MUST NOT leave rows behind for non-empty namespaces.

#### Scenario: Multiple namespaces cleaned
- **WHEN** a thread has checkpoint data in namespaces `""` (empty), `"subagent:1"`, and `"subagent:2"`
- **THEN** all rows across all three namespaces are deleted

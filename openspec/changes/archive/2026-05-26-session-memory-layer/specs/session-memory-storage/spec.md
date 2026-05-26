## ADDED Requirements

### Requirement: Session-scoped storage namespace
The system SHALL store session memory in LangGraph BaseStore under namespace `("memory_session", tenant_id, user_id, thread_id)` with key `"data"`. Each thread SHALL have isolated session memory that does not leak across threads or users.

#### Scenario: New thread creates isolated session memory
- **WHEN** a user sends the first message in a new thread
- **THEN** the system creates session memory at namespace `("memory_session", tenant_id, user_id, thread_id)` with key `"data"`

#### Scenario: Different threads have isolated memory
- **WHEN** user A has thread T1 and thread T2
- **THEN** session memory for T1 is stored at `("memory_session", tenant, A, T1)` and T2 at `("memory_session", tenant, A, T2)` with no cross-contamination

#### Scenario: Different users have isolated memory
- **WHEN** user A and user B each have a thread with the same thread_id
- **THEN** their session memory is stored at different namespaces and remains isolated

### Requirement: Automatic fact extraction from conversations
The system SHALL extract session-relevant facts from user and AI messages during agent execution. Facts SHALL be extracted via LLM analysis and stored with metadata (timestamp, source, confidence).

#### Scenario: User provides project context
- **WHEN** user says "I'm working on the Q3 budget report"
- **THEN** the system extracts fact "User is working on Q3 budget report" with category "context" and confidence >= 0.8

#### Scenario: AI confirms understanding
- **WHEN** AI responds "I'll help you analyze the budget data"
- **THEN** the system may extract fact "AI will assist with budget analysis" with category "task" if confidence >= threshold

#### Scenario: Low-confidence facts are filtered
- **WHEN** extracted fact has confidence < configured threshold (default 0.7)
- **THEN** the fact is NOT stored in session memory

### Requirement: Full-text retrieval with time-descending ordering
The system SHALL retrieve session memory facts using full-text search. Results SHALL be ordered by timestamp descending (most recent first). Retrieval SHALL be limited to configurable max tokens (default 2000).

#### Scenario: Retrieve recent session context
- **WHEN** agent needs session context for prompt composition
- **THEN** system retrieves facts from `("memory_session", tenant, user, thread)`, orders by timestamp desc, and returns up to max_injection_tokens

#### Scenario: Empty session memory returns empty context
- **WHEN** thread has no session memory yet
- **THEN** retrieval returns empty list with no errors

#### Scenario: Large session memory is truncated
- **WHEN** session memory contains 50 facts totaling 5000 tokens
- **THEN** retrieval returns most recent facts up to 2000 tokens, older facts are excluded

### Requirement: Thread lifecycle binding
Session memory SHALL be bound to thread lifecycle. When a thread is archived or closed, its session memory SHALL be archived (not deleted). No decay policies SHALL be applied during active thread lifetime.

#### Scenario: Active thread retains session memory
- **WHEN** thread is active and user sends messages over multiple days
- **THEN** all session memory facts remain accessible with no decay or expiration

#### Scenario: Archived thread retains session memory
- **WHEN** thread is archived by user
- **THEN** session memory remains in storage and can be retrieved if thread is reopened

#### Scenario: Deleted thread session memory is orphaned
- **WHEN** thread is permanently deleted
- **THEN** session memory remains in storage as orphaned data (manual cleanup required)

### Requirement: MemoryMiddleware integration
MemoryMiddleware SHALL write to both User Memory (existing StoreMemoryStorage) and Session Memory (new SessionStorage) in parallel. Session memory writes SHALL not block user memory writes.

#### Scenario: Conversation updates both memory layers
- **WHEN** user sends message and AI responds
- **THEN** MemoryMiddleware queues conversation for both User Memory update and Session Memory update

#### Scenario: Session memory write failure does not affect user memory
- **WHEN** session memory write fails (e.g., storage error)
- **THEN** user memory write continues and completes successfully, error is logged

#### Scenario: Agent-scoped session memory
- **WHEN** agent_name is provided in MemoryMiddleware
- **THEN** session memory is stored at `("memory_session", tenant, user, thread)` with agent_name in fact metadata (not in namespace)

### Requirement: Basic telemetry
The system SHALL track session memory read and write operations via structured logs. Logs SHALL include tenant_id, user_id, thread_id, operation type, and latency.

#### Scenario: Session memory write is logged
- **WHEN** session memory is successfully written
- **THEN** system emits INFO log: "Session memory saved: tenant=X user=Y thread=Z facts=N latency=Xms"

#### Scenario: Session memory read is logged
- **WHEN** session memory is retrieved for prompt composition
- **THEN** system emits DEBUG log: "Session memory retrieved: tenant=X user=Y thread=Z facts=N tokens=X latency=Xms"

#### Scenario: Session memory error is logged
- **WHEN** session memory operation fails
- **THEN** system emits ERROR log with exception details and operation context

### Requirement: Backward compatibility
Existing threads without session memory SHALL continue to work without modification. New messages in existing threads SHALL populate session memory incrementally.

#### Scenario: Legacy thread without session memory
- **WHEN** user opens thread created before session memory feature
- **THEN** system retrieves empty session memory and agent execution continues normally

#### Scenario: Legacy thread gains session memory
- **WHEN** user sends new message in legacy thread
- **THEN** system creates session memory and extracts facts from new conversation only (no backfill)

#### Scenario: Mixed memory layers
- **WHEN** thread has user memory but no session memory
- **THEN** prompt composition includes user memory context, session memory context is empty

## Why

Long conversations in DeerFlow suffer from context loss after message summarization. When a thread accumulates many messages, the system summarizes older messages to stay within context limits, but this causes important session-specific details to be lost. Session Memory provides a dedicated storage layer scoped to (tenant_id, user_id, thread_id) that persists key facts, decisions, and context for the lifetime of the thread, ensuring continuity even after summarization.

## What Changes

- **New SessionStorage class**: Implements LangGraph BaseStore with namespace scheme `("memory_session", tenant_id, user_id, thread_id)` for thread-scoped memory persistence
- **Session memory retrieval**: Full-text search with time-descending ordering to surface recent session context during agent execution
- **MemoryMiddleware integration**: Automatically captures and stores session-relevant facts from user and AI messages into SessionStorage
- **Thread lifecycle binding**: Session memory is archived when the thread closes, with no decay policies or manual cleanup required
- **Basic telemetry**: Track session memory reads/writes to measure adoption and effectiveness
- **Migration path**: Existing threads without session memory continue to work; new messages populate session storage incrementally

## Capabilities

### New Capabilities

- `session-memory-storage`: Thread-scoped memory layer with automatic fact extraction, full-text retrieval, and thread lifecycle binding

### Modified Capabilities

No existing capabilities are modified. Session Memory is a new layer that operates alongside the existing User Memory (StoreMemoryStorage) without changing its behavior.

## Impact

**Code changes:**
- New `SessionStorage` class in `backend/packages/harness/deerflow/memory/`
- Extend `MemoryMiddleware` to write to both Session and User memory layers
- Add session retrieval to agent prompt composition
- New database namespace in LangGraph Store (no schema changes)

**APIs:**
- No API changes in this phase. Session memory is internal to the agent execution pipeline.

**Dependencies:**
- Uses existing LangGraph BaseStore (already installed)
- No new external dependencies

**Systems:**
- Affects agent execution pipeline (memory read/write path)
- No frontend changes
- No configuration changes (session memory is always enabled when using StoreMemoryStorage)

**Migration:**
- Existing threads work without session memory
- New messages automatically populate session storage
- No data migration required

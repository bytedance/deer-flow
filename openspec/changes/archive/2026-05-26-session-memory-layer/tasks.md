# Tasks

## 1. SessionStorage Implementation

- [x] 1.1 Create `SessionStorage` class in `backend/packages/harness/deerflow/agents/memory/session_storage.py` extending `MemoryStorage` ABC
- [x] 1.2 Implement `_ns(thread_id, user_id)` method returning namespace `("memory_session", tenant_id, user_id, thread_id)`
- [x] 1.3 Implement `load(thread_id, user_id)` method to retrieve session memory from BaseStore
- [x] 1.4 Implement `save(memory_data, thread_id, user_id)` method to persist session memory to BaseStore
- [x] 1.5 Implement `reload(thread_id, user_id)` method (same as load for Store backend)
- [x] 1.6 Add `get_session_storage()` function with singleton pattern and lazy initialization
- [x] 1.7 Add `set_session_storage()` function for dependency injection (Gateway lifespan, tests)
- [x] 1.8 Write unit tests for SessionStorage (namespace construction, load/save, empty memory, tenant isolation)

## 2. Session Memory Updater

- [x] 2.1 Add `update_session_memory()` method to `MemoryUpdater` class
- [x] 2.2 Implement `_prepare_session_update_prompt()` that loads session memory and builds extraction prompt (simpler than user memory prompt, no user/history sections)
- [x] 2.3 Implement `_finalize_session_update()` that parses LLM response and saves to SessionStorage
- [x] 2.4 Add `update_session_from_conversation()` convenience function (similar to `update_memory_from_conversation()`)
- [x] 2.5 Write unit tests for session memory updater (fact extraction, confidence filtering, save success/failure)

## 3. Session Memory Queue

- [x] 3.1 Create `SessionMemoryUpdateQueue` class in `backend/packages/harness/deerflow/agents/memory/session_queue.py` (similar to MemoryUpdateQueue)
- [x] 3.2 Implement `add(thread_id, messages, user_id)` method with debounce (30s default)
- [x] 3.3 Implement `_process_queue()` that calls `update_session_from_conversation()` for each batched conversation
- [x] 3.4 Add `get_session_memory_queue()` singleton accessor
- [x] 3.5 Write unit tests for session queue (debounce, batching, processing)

## 4. MemoryMiddleware Integration

- [x] 4.1 Update `MemoryMiddleware.after_agent()` to queue conversations for both User Memory and Session Memory
- [x] 4.2 Ensure session memory writes are non-blocking (parallel with user memory writes)
- [x] 4.3 Add `session_memory_enabled` config check before queueing session updates
- [x] 4.4 Write unit tests for middleware integration (dual queue, session disabled, write failure isolation)

## 5. Session Memory Retrieval

- [x] 5.1 Create `get_session_context(thread_id, user_id, max_tokens)` function in `backend/packages/harness/deerflow/agents/memory/retrieval.py`
- [x] 5.2 Implement full-text retrieval from SessionStorage (load facts, sort by createdAt desc)
- [x] 5.3 Implement token budgeting (truncate to max_tokens, default 2000)
- [x] 5.4 Format session context as string with header "Session context:"
- [x] 5.5 Add in-memory LRU cache for session memory (keyed by `(tenant, user, thread)`, invalidate on write)
- [x] 5.6 Write unit tests for retrieval (empty session, large session truncation, caching, token budgeting)

## 6. Prompt Composition

- [x] 6.1 Create `compose_memory_for_prompt(thread_id, user_id, max_tokens)` function that merges User Memory + Session Memory
- [x] 6.2 Allocate token budget: 2000 for User Memory, 2000 for Session Memory, 4000 total
- [x] 6.3 Format output with clear section headers ("User context:" and "Session context:")
- [x] 6.4 Integrate `compose_memory_for_prompt()` into agent system prompt builder (locate existing prompt composition code)
- [x] 6.5 Add `memory.injection_enabled` config check before injecting memory into prompt
- [x] 6.6 Write unit tests for prompt composition (user only, session only, both, neither, token overflow)

## 7. Configuration

- [x] 7.1 Add `SessionMemoryConfig` class in `backend/packages/harness/deerflow/config/session_memory_config.py`
- [x] 7.2 Add fields: `enabled`, `model_name`, `debounce_seconds`, `max_facts`, `fact_confidence_threshold`, `max_injection_tokens`
- [x] 7.3 Add `get_session_memory_config()` and `set_session_memory_config()` functions
- [x] 7.4 Add `load_session_memory_config_from_dict()` for YAML config loading
- [x] 7.5 Integrate session memory config into main `AppConfig` (add `session_memory` section)
- [x] 7.6 Write unit tests for config (defaults, validation, loading from dict)

## 8. Telemetry

- [x] 8.1 Add structured logging for session memory writes: "Session memory saved: tenant=X user=Y thread=Z facts=N latency=Xms"
- [x] 8.2 Add structured logging for session memory reads: "Session memory retrieved: tenant=X user=Y thread=Z facts=N tokens=X latency=Xms"
- [x] 8.3 Add error logging for session memory failures with exception details
- [x] 8.4 Write unit tests verifying log output (use caplog fixture)

## 9. Integration Tests

- [x] 9.1 Write integration test: new thread → send messages → verify session memory created
- [x] 9.2 Write integration test: multiple threads → verify isolation between threads
- [x] 9.3 Write integration test: legacy thread → send new message → verify session memory created incrementally
- [x] 9.4 Write integration test: session memory write failure → verify user memory still written
- [x] 9.5 Write integration test: prompt composition with both user and session memory

## 10. Documentation

- [x] 10.1 Create `docs/SESSION_MEMORY.md` explaining Session Memory feature, configuration, and usage
- [x] 10.2 Document session memory namespace scheme and lifecycle binding
- [x] 10.3 Document configuration options (`session_memory.enabled`, `session_memory.model_name`, etc.)
- [x] 10.4 Update `config.example.yaml` with session memory section and comments

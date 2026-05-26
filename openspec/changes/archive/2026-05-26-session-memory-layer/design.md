## Context

DeerFlow's current memory system uses a single User Memory layer scoped to `(tenant_id, user_id, agent_name)`. This layer persists long-term facts about user preferences, work context, and background across all threads. While effective for cross-thread continuity, it suffers from **context loss after summarization** within long threads: when a thread accumulates many messages, older messages are summarized to stay within context limits, causing session-specific details (e.g., "user mentioned they're working on Q3 budget report 20 messages ago") to be lost.

Session Memory addresses this gap by providing a **thread-scoped** memory layer that persists session-relevant facts for the lifetime of the thread. It operates alongside User Memory without replacing it.

**Current architecture:**
- `MemoryMiddleware` (position 13 in middleware chain) filters user + AI messages after agent execution
- `MemoryUpdateQueue` debounces updates (30s default) and batches conversations
- `MemoryUpdater` uses LLM to extract facts and update `StoreMemoryStorage` (namespace: `("memory", tenant, user, agent)`)
- Facts are injected into system prompt via `compose_for_prompt()` (not yet implemented, but planned)

**Constraints:**
- Must not break existing User Memory behavior
- Must work with StoreMemoryStorage backend (FileMemoryStorage users do not enable Session Memory)
- Must not add significant latency to agent execution
- Must handle multi-tenant isolation (tenant_id in namespace)
- Must respond to correction/reinforcement signals (same as User Memory)

## Goals / Non-Goals

**Goals:**
- Provide thread-scoped memory that survives message summarization
- Extract session-relevant facts automatically via LLM
- Retrieve session context efficiently (full-text search, time-descending)
- Integrate with existing MemoryMiddleware without disrupting User Memory writes
- Bind session memory lifecycle to thread lifecycle (no manual cleanup)
- Maintain backward compatibility (legacy threads work without session memory)

**Non-Goals:**
- Domain Memory layer (scoped to `tenant_id, domain, entity_id`) — deferred to Phase B
- Frontend UI for session memory inspection/editing — deferred to Phase C
- Decay policies (linear/exponential aging) — not needed for thread-scoped memory
- Cross-thread memory sharing or linking
- Session memory export/import
- Automatic cleanup of orphaned session memory (deleted threads)
- Real-time session memory streaming to frontend

## Decisions

### D1: SessionStorage class extends MemoryStorage ABC

**Decision:** Create `SessionStorage` class that extends the existing `MemoryStorage` abstract base class, but with a different namespace scheme.

**Rationale:** Reusing `MemoryStorage` ABC provides consistency with existing storage providers (FileMemoryStorage, StoreMemoryStorage). However, SessionStorage has different semantics (thread-scoped vs user-scoped), so it cannot be used as a drop-in replacement for `get_memory_storage()`. Instead, it will be accessed via a dedicated `get_session_storage()` function.

**Alternatives considered:**

- Create a separate `SessionMemoryStorage` ABC — rejected because it duplicates interface without benefit
- Use composition instead of inheritance — rejected because SessionStorage shares 80% of MemoryStorage behavior

**Implementation:**

```python
class SessionStorage(MemoryStorage):
    def _ns(self, thread_id: str, user_id: str | None = None) -> tuple[str, str, str, str]:
        return ("memory_session", get_current_tenant_id(), user_id or "", thread_id)
    
    def load(self, thread_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        # Load from BaseStore at namespace
        ...
    
    def save(self, memory_data: dict[str, Any], thread_id: str, *, user_id: str | None = None) -> bool:
        # Save to BaseStore at namespace
        ...
```

### D2: Reuse MemoryUpdater for session fact extraction

**Decision:** Extend `MemoryUpdater` to support session memory updates by adding a `update_session_memory()` method that writes to `SessionStorage` instead of `StoreMemoryStorage`.

**Rationale:** The LLM-based fact extraction logic (prompt, response parsing, confidence filtering) is identical for both User Memory and Session Memory. Duplicating this logic would create maintenance burden. Instead, parameterize the storage target.

**Alternatives considered:**

- Create separate `SessionMemoryUpdater` class — rejected due to code duplication
- Use strategy pattern to inject storage — considered but overkill for two storage targets

**Implementation:**

```python
class MemoryUpdater:
    def update_session_memory(
        self,
        messages: list[Any],
        thread_id: str,
        user_id: str | None = None,
    ) -> bool:
        # Reuse _prepare_update_prompt() but load from SessionStorage
        # Reuse _finalize_update() but save to SessionStorage
        ...
```

### D3: Parallel writes to User Memory and Session Memory

**Decision:** MemoryMiddleware SHALL queue conversations for both User Memory and Session Memory updates in parallel (non-blocking).

**Rationale:** Session Memory writes should not add latency to User Memory writes (which are already debounced and async). Both writes can happen concurrently via the existing `MemoryUpdateQueue` mechanism.

**Alternatives considered:**

- Sequential writes (User Memory first, then Session Memory) — rejected because it doubles latency
- Single queue with dual write — rejected because it complicates queue processing logic

**Implementation:**

```python
class MemoryMiddleware:
    def after_agent(self, state, runtime):
        # ... existing filtering logic ...
        queue = get_memory_queue()
        queue.add(...)  # User Memory
        session_queue = get_session_memory_queue()
        session_queue.add(thread_id=thread_id, messages=filtered_messages, user_id=user_id)
```

### D4: Session memory retrieval via dedicated function

**Decision:** Add `get_session_context(thread_id, user_id, max_tokens)` function that retrieves session facts and formats them for prompt injection.

**Rationale:** Session memory retrieval is distinct from User Memory retrieval (different namespace, different ordering). A dedicated function keeps concerns separated and makes testing easier.

**Alternatives considered:**

- Unified `get_memory_context()` that merges User + Session — rejected because it complicates token budgeting
- Inject session memory directly into agent state — rejected because it bypasses prompt composition

**Implementation:**

```python
def get_session_context(
    thread_id: str,
    user_id: str | None = None,
    max_tokens: int = 2000,
) -> str:
    storage = get_session_storage()
    memory_data = storage.load(thread_id, user_id=user_id)
    facts = memory_data.get("facts", [])
    # Sort by createdAt desc, truncate to max_tokens
    # Format as "Session context: ..."
    ...
```

### D5: Session memory injection into system prompt

**Decision:** Inject session memory context into system prompt after User Memory context, with clear section headers.

**Rationale:** Session memory is more recent and thread-specific than User Memory, so it should appear later in the prompt (closer to the conversation). Clear headers help the model distinguish between long-term preferences and session-specific context.

**Alternatives considered:**

- Inject session memory before User Memory — rejected because recency bias favors session memory
- Merge session + user facts — rejected because it obscures provenance

**Implementation:**

```python
def compose_for_prompt(
    thread_id: str,
    user_id: str | None = None,
    max_tokens: int = 4000,
) -> str:
    user_context = get_user_context(user_id, max_tokens=2000)
    session_context = get_session_context(thread_id, user_id, max_tokens=2000)
    return f"{user_context}\n\n{session_context}"
```

### D6: Session memory uses same empty-memory structure as User Memory

**Decision:** Session memory SHALL use the same JSON structure as User Memory (`version`, `lastUpdated`, `user`, `history`, `facts`), but only the `facts` array will be populated.

**Rationale:** Reusing the structure simplifies implementation and allows future extensions (e.g., session-level `user` context). The `user` and `history` sections are ignored for session memory.

**Alternatives considered:**

- Create a new `SessionMemory` schema with only `facts` — rejected because it requires schema migration if we add fields later
- Use a flat list of facts — rejected because it loses metadata (version, lastUpdated)

### D7: Session storage singleton with lazy initialization

**Decision:** Use a global singleton pattern for `SessionStorage` (similar to `get_memory_storage()`), with lazy initialization on first access.

**Rationale:** Session storage is accessed frequently during agent execution (once per prompt composition). Singleton avoids repeated instantiation. Lazy initialization ensures Store is available before creating storage.

**Alternatives considered:**

- Dependency injection via Runtime context — rejected because it requires changes to all agent signatures
- Per-request storage instance — rejected due to instantiation overhead

### D8: Session Memory only supports Store backend

**Decision:** Session Memory SHALL only be available when using `StoreMemoryStorage` (LangGraph Store backend). Users with `FileMemoryStorage` will not have Session Memory enabled.

**Rationale:** Session Memory is designed for production deployments using PostgreSQL (via LangGraph Store). FileMemoryStorage is for local development and single-user scenarios where thread-scoped memory provides limited value. Supporting both backends would double implementation complexity.

**Alternatives considered:**

- Support FileMemoryStorage for Session Memory — rejected because it requires file-per-thread management, complicates cleanup, and contradicts PostgreSQL migration goals
- Make Session Memory backend-agnostic — rejected because it adds complexity for a feature targeted at production deployments

**Implementation:**

```python
def get_session_storage() -> SessionStorage | None:
    memory_storage = get_memory_storage()
    if not isinstance(memory_storage, StoreMemoryStorage):
        logger.info("Session Memory disabled: requires StoreMemoryStorage backend")
        return None
    # Create SessionStorage using same Store factory
    return SessionStorage(store_factory=_store_factory)
```

### D9: Session Memory responds to correction/reinforcement signals

**Decision:** Session Memory extraction SHALL respond to `correction_detected` and `reinforcement_detected` signals, same as User Memory. Corrections in a thread update session facts with high confidence.

**Rationale:** Users may correct thread-specific details (e.g., "No, the deadline is Friday, not Thursday"). These corrections should update Session Memory with high confidence, just like User Memory corrections.

**Alternatives considered:**

- Ignore correction signals for Session Memory — rejected because thread-specific corrections are valuable
- Only respond to corrections, not reinforcements — rejected because positive feedback is also useful

**Implementation:**

```python
def update_session_memory(
    self,
    messages: list[Any],
    thread_id: str,
    user_id: str | None = None,
    correction_detected: bool = False,
    reinforcement_detected: bool = False,
) -> bool:
    # Build prompt with correction/reinforcement hints (reuse existing logic)
    correction_hint = self._build_correction_hint(correction_detected, reinforcement_detected)
    # ... extract facts with hints
```

### D10: Session Memory includes session_context summary field

**Decision:** Session Memory SHALL include a `session_context` field (similar to `user.workContext` in User Memory) that summarizes the current thread's purpose and key decisions. LLM updates this summary on each memory update.

**Rationale:** Facts alone may not capture the thread's overall context (e.g., "User is debugging authentication issue in staging environment"). A summary field provides high-level context that complements individual facts.

**Alternatives considered:**

- Only use facts, no summary — rejected because facts lack narrative context
- Use full `user` and `history` sections like User Memory — rejected because they're designed for long-term context, not thread-scoped

**Implementation:**

```python
def create_empty_session_memory() -> dict[str, Any]:
    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "session_context": {"summary": "", "updatedAt": ""},
        "facts": [],
    }

# In _apply_session_updates():
if update_data.get("sessionContext", {}).get("shouldUpdate"):
    current_memory["session_context"] = {
        "summary": update_data["sessionContext"]["summary"],
        "updatedAt": now,
    }
```

### D11: Separate injection toggles for User and Session Memory

**Decision:** Use separate config toggles for User Memory injection (`memory.injection_enabled`) and Session Memory injection (`session_memory.injection_enabled`). Each can be enabled/disabled independently.

**Rationale:** Users may want to inject User Memory (long-term preferences) without Session Memory (thread context), or vice versa. Separate toggles provide flexibility for different use cases and cost optimization.

**Alternatives considered:**

- Single toggle for both — rejected because it reduces flexibility
- Session Memory always injects when enabled — rejected because it prevents cost optimization (disable injection but keep extraction for future use)

**Implementation:**

```python
def compose_memory_for_prompt(
    thread_id: str,
    user_id: str | None = None,
    max_tokens: int = 4000,
) -> str:
    parts = []
    
    user_config = get_memory_config()
    if user_config.injection_enabled:
        user_context = get_user_context(user_id, max_tokens=2000)
        parts.append(f"User context:\n{user_context}")
    
    session_config = get_session_memory_config()
    if session_config.injection_enabled:
        session_context = get_session_context(thread_id, user_id, max_tokens=2000)
        parts.append(f"Session context:\n{session_context}")
    
    return "\n\n".join(parts)
```

## Risks / Trade-offs

### R1: Increased LLM cost for dual memory updates

**Risk:** Running LLM-based fact extraction twice (once for User Memory, once for Session Memory) doubles the cost per conversation.

**Mitigation:** Session memory extraction uses a simpler prompt (no `user`/`history` sections to update), reducing token count by ~40%. Additionally, session memory updates can use a smaller/cheaper model (configurable via `session_memory.model_name`).

**Trade-off:** Accept 60% cost increase (not 100%) in exchange for session continuity.

### R2: Session memory retrieval latency

**Risk:** Retrieving session facts from BaseStore adds latency to prompt composition, especially for threads with many facts.

**Mitigation:** Session memory is cached in-memory (LRU cache keyed by `(tenant, user, thread)`), with cache invalidation on write. Retrieval is also async and non-blocking.

**Trade-off:** First retrieval after write is slow (~50ms), subsequent retrievals are fast (~5ms).

### R3: Orphaned session memory for deleted threads

**Risk:** When a thread is deleted, its session memory remains in storage as orphaned data, consuming storage space.

**Mitigation:** Deferred to future phase. For now, orphaned data is acceptable because:
- Session memory is small (~1KB per thread)
- Manual cleanup script can be run periodically
- Thread deletion is rare in typical usage

**Trade-off:** Accept storage bloat in exchange for simpler implementation.

### R4: Session memory write failure does not affect User Memory

**Risk:** If session memory write fails, User Memory write continues, leading to inconsistent state (User Memory has fact, Session Memory does not).

**Mitigation:** This is acceptable behavior because:
- User Memory is long-term, Session Memory is short-term
- Inconsistency is temporary (next conversation will retry session write)
- Error is logged for debugging

**Trade-off:** Accept eventual consistency in exchange for fault isolation.

### R5: Multi-tenant isolation via namespace

**Risk:** Incorrect namespace construction could leak session memory across tenants.

**Mitigation:** Namespace always includes `tenant_id` from `get_current_tenant_id()`, which is validated at Gateway middleware. Unit tests verify isolation across tenants.

**Trade-off:** None — this is a hard requirement.

## Migration Plan

**Deployment:**
1. Deploy code with Session Memory feature disabled by default (`session_memory.enabled: false` in config)
2. Enable on staging environment, monitor for 24 hours
3. Enable on production environment for 10% of tenants (canary deployment)
4. Monitor error rates, latency, LLM cost for 1 week
5. Enable for all tenants

**Rollback:**
1. Set `session_memory.enabled: false` in config
2. Restart Gateway pods
3. Session memory reads return empty context, writes are skipped
4. No data loss (User Memory unaffected)

**Data migration:**
- No migration required. Existing threads work without session memory.
- New messages in existing threads populate session memory incrementally.

## Open Questions

1. **Session memory injection token budget:** Should session memory share the 4000-token budget with User Memory, or have its own budget? Current design: 2000 tokens each, 4000 total.

2. **Session memory model:** Should session memory use the same LLM model as User Memory, or a cheaper model (e.g., `gpt-4o-mini`)? Current design: configurable via `session_memory.model_name`, defaults to User Memory model.

3. **Session memory cache TTL:** How long should session memory be cached before re-fetching from storage? Current design: no TTL, invalidate on write.

4. **Orphaned session memory cleanup:** Should we implement automatic cleanup for deleted threads, or defer to manual script? Current design: deferred.

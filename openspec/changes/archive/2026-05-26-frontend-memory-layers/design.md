## Context

DeerFlow's memory system (User, Session, Domain) operates as a black box to users. Agents recall facts from memory during conversations, but users cannot inspect what the agent "knows," correct misinformation, or delete outdated facts. This lack of transparency erodes trust and creates frustration when agents recall incorrect context.

The Memory Inspection and Editing UI provides users with visibility and control over the memory system. It consists of two main capabilities:
1. **Memory Inspection UI**: Frontend panel for viewing, searching, and filtering memory facts across all three layers
2. **Memory Editing API**: REST endpoints for CRUD operations on memory facts with audit logging

**Current architecture:**
- User Memory: stored in BaseStore at `("memory", tenant, user, agent)`
- Session Memory: stored in BaseStore at `("memory_session", tenant, user, thread)`
- Domain Memory: stored in vector DB at collection `domain_{tenant_id}`
- No REST API for memory access (only internal Python functions)
- No frontend UI for memory inspection

**Constraints:**
- Must enforce tenant isolation (users can only access their tenant's memory)
- Must support authentication and authorization (users can only edit their own User Memory, admins can edit any)
- Must log all edits for audit purposes
- Must not add latency to agent execution (API is separate from agent pipeline)

## Goals / Non-Goals

**Goals:**
- Provide transparent view of memory facts across User/Session/Domain layers
- Enable users to create, update, and delete memory facts
- Support search and filtering by keyword, confidence, date range, domain/entity
- Log all memory edits for audit purposes
- Real-time notifications when memory is updated during conversations
- Export/import memory as JSON for backup and correction

**Non-Goals:**
- Automatic memory correction (LLM-based fact validation) — deferred to future phase
- Cross-tenant memory sharing or admin override — deferred
- Memory versioning (track all historical versions of a fact) — deferred
- Memory analytics dashboard (usage statistics, retrieval patterns) — deferred
- Decay policy configuration UI — deferred (config via YAML only in this phase)

## Decisions

### D1: API design — REST vs GraphQL

**Decision:** Use REST API with resource-oriented endpoints for memory CRUD operations.

**Rationale:** REST is simpler to implement, document, and test. Memory operations are straightforward CRUD, not complex queries that benefit from GraphQL's flexibility. REST also aligns with DeerFlow's existing API patterns.

**Alternatives considered:**
- GraphQL — rejected because it adds complexity without benefit for simple CRUD
- gRPC — rejected because frontend clients don't support gRPC natively

**Implementation:**
```
GET    /api/v1/memory/{layer}              # List facts (with filters)
POST   /api/v1/memory/{layer}/facts        # Create fact
GET    /api/v1/memory/{layer}/facts/{id}   # Get single fact
PUT    /api/v1/memory/{layer}/facts/{id}   # Update fact
DELETE /api/v1/memory/{layer}/facts/{id}   # Delete fact
GET    /api/v1/memory/{layer}/export       # Export as JSON
POST   /api/v1/memory/{layer}/import       # Import from JSON
GET    /api/v1/memory/audit                # Query audit logs (admin only)
```

### D2: Frontend framework — React components

**Decision:** Build memory inspection UI as React components using existing DeerFlow frontend stack (React, TanStack Query, Tailwind).

**Rationale:** Reusing the existing stack ensures consistency with other DeerFlow UI components and leverages existing developer expertise.

**Alternatives considered:**
- Vue.js — rejected because DeerFlow uses React
- Vanilla JS — rejected because it lacks component reusability

**Implementation:**
- `MemoryPanel`: Main container with tabs for User/Session/Domain
- `MemoryFactCard`: Individual fact display with metadata
- `MemorySearchBar`: Keyword search and filter controls
- `MemoryEditor`: Modal for creating/editing facts
- `MemoryExportImport`: Dialog for export/import operations

### D3: Authentication and authorization

**Decision:** Use existing DeerFlow authentication (JWT tokens) and add role-based authorization: users can edit their own User Memory, admins can edit any memory.

**Rationale:** Reusing existing auth infrastructure avoids duplication. Role-based access ensures users can't access other users' memory.

**Alternatives considered:**
- No auth (open access) — rejected because memory is sensitive
- API keys — rejected because DeerFlow uses JWT

**Implementation:**
```python
@router.get("/api/v1/memory/user")
async def get_user_memory(
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    # User can only access their own User Memory
    return storage.load(user_id=user.id)

@router.delete("/api/v1/memory/user/facts/{fact_id}")
async def delete_user_fact(
    fact_id: str,
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant_id),
):
    # User can only delete their own facts
    # Admin can delete any fact
    ...
```

### D4: Audit logging storage

**Decision:** Store audit logs in the same database as other DeerFlow data (SQLite or PostgreSQL). Create new `MemoryAuditRow` ORM model.

**Rationale:** Reusing the existing database avoids introducing a new storage dependency. Audit logs are relational data (user, timestamp, action, fact_id) that fit naturally in SQL.

**Alternatives considered:**
- Structured logs (stdout) — rejected because they're hard to query
- Separate audit database — rejected because it adds operational complexity

**Implementation:**
```python
class MemoryAuditRow(Base):
    __tablename__ = "memory_audit"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str]
    user_id: Mapped[str]
    action: Mapped[str]  # "create", "update", "delete"
    layer: Mapped[str]   # "user", "session", "domain"
    fact_id: Mapped[str]
    before: Mapped[dict | None]  # JSON
    after: Mapped[dict | None]   # JSON
    timestamp: Mapped[datetime]
```

### D5: WebSocket event emission

**Decision:** Use existing DeerFlow WebSocket infrastructure to emit `memory_updated` events. Events are tenant-scoped (only connections for the same tenant receive them).

**Rationale:** Reusing existing WebSocket infrastructure avoids duplication. Tenant-scoped events ensure isolation.

**Alternatives considered:**
- Server-Sent Events (SSE) — rejected because DeerFlow already uses WebSocket
- Polling — rejected because it adds latency and server load

**Implementation:**
```python
async def emit_memory_update(
    tenant_id: str,
    layer: str,
    action: str,
    fact_id: str,
    user_id: str,
    thread_id: str | None = None,
):
    event = {
        "type": "memory_updated",
        "layer": layer,
        "action": action,
        "fact_id": fact_id,
        "user_id": user_id,
        "thread_id": thread_id,
    }
    await websocket_manager.broadcast(tenant_id, event)
```

### D6: Memory export format

**Decision:** Export memory as JSON with schema versioning. Include all facts and metadata (version, exportedAt, facts array).

**Rationale:** JSON is human-readable and easy to edit. Schema versioning allows future format changes without breaking imports.

**Alternatives considered:**
- CSV — rejected because memory facts have nested metadata
- YAML — rejected because JSON is more widely supported

**Implementation:**
```json
{
  "version": "1.0",
  "exportedAt": "2026-05-26T10:00:00Z",
  "layer": "user",
  "facts": [
    {
      "id": "fact_abc123",
      "content": "Prefers concise responses",
      "category": "preference",
      "confidence": 0.9,
      "createdAt": "2026-05-20T14:30:00Z",
      "source": "thread_xyz"
    }
  ]
}
```

## Risks / Trade-offs

### R1: Memory editing introduces inconsistency

**Risk:** User edits may conflict with agent-extracted facts, leading to inconsistent memory state.

**Mitigation:** Audit logs track all edits. Future phase: add conflict detection (warn if user edits fact that agent recently extracted).

**Trade-off:** Accept potential inconsistency in exchange for user control.

### R2: Audit log storage bloat

**Risk:** High-volume memory edits generate many audit log entries, consuming storage.

**Mitigation:** Implement log rotation (delete logs older than 90 days). Add admin API to query and purge old logs.

**Trade-off:** Accept storage bloat in exchange for audit trail.

### R3: WebSocket event flooding

**Risk:** Rapid memory updates (e.g., during long conversations) flood WebSocket connections, causing UI lag.

**Mitigation:** Debounce WebSocket events (max 1 event per second per connection). Batch multiple updates into single event.

**Trade-off:** Accept slight delay in UI updates in exchange for performance.

### R4: Memory export includes sensitive data

**Risk:** Exported JSON may contain sensitive user preferences or domain facts that shouldn't be shared.

**Mitigation:** Add warning dialog before export: "Exported memory may contain sensitive information. Handle with care."

**Trade-off:** Accept risk in exchange for user control.

### R5: Cross-browser session synchronization

**Risk:** User edits memory in one browser, but another browser session still shows old data.

**Mitigation:** WebSocket events notify all active sessions. Users can manually refresh if needed.

**Trade-off:** Accept eventual consistency in exchange for simplicity.

## Migration Plan

**Deployment:**
1. Deploy backend API with feature flag `memory_api.enabled: false`
2. Enable on staging, test with internal users for 1 week
3. Enable on production for canary tenants (10%), monitor error rates
4. Deploy frontend UI with feature flag `memory_ui.enabled: false`
5. Enable frontend for canary tenants, gather feedback for 2 weeks
6. Enable for all tenants

**Rollback:**
1. Set feature flags to `false`
2. Restart Gateway and frontend pods
3. Memory API and UI are disabled, no data loss

**Data migration:**
- No migration required. Memory UI reads existing memory data.
- Audit log table is created via ORM migration.

## Open Questions

1. **Memory versioning:** Should we track all historical versions of a fact (e.g., "Pump A flow rate: 500 GPM" → "600 GPM")? Current design: no, only current version stored, history in audit logs.

2. **Admin override:** Should admins be able to edit any user's memory (e.g., to correct misinformation)? Current design: no, only users can edit their own memory.

3. **Memory analytics:** Should we build a dashboard showing memory usage statistics (facts per user, retrieval patterns)? Current design: deferred to future phase.

4. **Decay policy UI:** Should we build a UI for configuring per-domain decay policies, or keep it YAML-only? Current design: YAML-only, UI deferred.

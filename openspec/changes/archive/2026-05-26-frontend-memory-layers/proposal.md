## Why

DeerFlow's memory system (User, Session, Domain) operates invisibly to users. When agents recall incorrect facts or forget important context, users have no way to inspect what the agent "knows" or correct misinformation. This creates frustration and erodes trust. A memory inspection and editing UI gives users transparency and control over the memory system, enabling them to view, correct, and delete stored facts across all three memory layers.

## What Changes

- **Memory inspection UI**: New frontend panel showing User Memory, Session Memory, and Domain Memory facts with search and filtering
- **Memory editing API**: REST endpoints to create, update, and delete facts across all memory layers
- **Fact metadata display**: Show confidence scores, timestamps, source threads, and decay status for each fact
- **Memory export/import**: Allow users to export memory as JSON and import corrected versions
- **Decay policy configuration UI**: Admin interface to configure per-domain decay policies (optional)
- **Real-time memory updates**: WebSocket notifications when memory is updated during conversations

## Capabilities

### New Capabilities

- `memory-inspection-ui`: Frontend panel for viewing and searching memory facts across User/Session/Domain layers
- `memory-editing-api`: REST API for CRUD operations on memory facts with audit logging

### Modified Capabilities

- `kb-retrieval-telemetry`: Extend to include memory inspection/editing metrics (optional)

## Impact

**Code changes:**
- New frontend components: `MemoryPanel`, `MemoryFactCard`, `MemorySearchBar`, `MemoryEditor`
- New REST endpoints: `GET/POST/PUT/DELETE /api/v1/memory/{layer}/facts`
- WebSocket event: `memory_updated` for real-time notifications
- Audit logging for all memory edits (who changed what, when)

**APIs:**
- New REST API for memory CRUD (6 endpoints)
- WebSocket event for memory updates
- Optional: Admin API for decay policy configuration

**Dependencies:**
- Frontend: React components, TanStack Query for API calls, Tailwind for styling
- Backend: FastAPI endpoints, audit logging middleware

**Systems:**
- Frontend: new memory inspection panel (accessible from thread view and settings)
- Backend: new REST API, WebSocket events
- No changes to agent execution pipeline

**Migration:**
- No migration required. Memory UI is new capability.
- Existing memory data is readable via new API.

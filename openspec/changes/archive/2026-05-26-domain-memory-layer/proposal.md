## Why

DeerFlow agents often work with domain-specific entities (e.g., equipment, systems, processes) across multiple threads. When a user discusses "Pump A" in one thread and "Pump A" in another thread, the agent has no way to connect these conversations or recall domain-specific facts. Domain Memory provides a semantic search layer scoped to `(tenant_id, domain, entity_id)` that persists domain knowledge and enables cross-thread retrieval, solving the "entity amnesia" problem where agents repeatedly ask for the same domain context.

## What Changes

- **New DomainStorage class**: Implements semantic search over domain facts using ChromaDB (or pgvector) with KB-bound embedding
- **Domain fact extraction**: LLM-based extraction of domain-specific facts from conversations, tagged with domain and entity_id
- **Semantic retrieval**: Vector similarity search to find relevant domain facts during agent execution
- **Decay policies**: Configurable aging (never/linear/exponential) for domain facts based on confidence and recency
- **Cross-thread linking**: Facts from different threads about the same entity are linked and searchable
- **Telemetry**: Track domain memory reads/writes, retrieval relevance scores

## Capabilities

### New Capabilities

- `domain-memory-storage`: Entity-scoped memory layer with semantic search, decay policies, and cross-thread linking

### Modified Capabilities

- `kb-retrieval-telemetry`: Extend to include domain memory retrieval metrics (if domain memory uses RAG infrastructure)

## Impact

**Code changes:**
- New `DomainStorage` class in `backend/packages/harness/deerflow/memory/`
- Extend `MemoryMiddleware` to extract domain facts (requires entity recognition)
- Add domain retrieval to agent prompt composition
- New ChromaDB collection (or pgvector table) for domain embeddings
- Decay policy engine for fact aging

**APIs:**
- New REST endpoint `GET /api/v1/memory/domain?entity_id=X` to inspect domain memory (optional, deferred to Phase C)

**Dependencies:**
- ChromaDB (already installed for RAG) or pgvector (from PostgreSQL migration)
- Embedding model for domain facts (reuse RAG embedding config)

**Systems:**
- Affects agent execution pipeline (memory read/write path)
- Uses RAG infrastructure (embedding models, vector store)
- No frontend changes in this phase

**Migration:**
- No migration required. Domain memory is new capability.
- Existing threads work without domain memory.

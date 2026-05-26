## Context

DeerFlow's memory system currently operates at two levels: User Memory (long-term preferences across all threads) and Session Memory (thread-scoped facts, Phase A). However, many DeerFlow use cases involve **domain-specific entities** (equipment, systems, processes, people) that span multiple threads and users within a tenant. When a user discusses "Pump A" in one thread and another user discusses "Pump A" in a different thread, there is no mechanism to connect these conversations or recall domain-specific knowledge.

Domain Memory addresses this by providing a **semantic search layer** scoped to `(tenant_id, domain, entity_id)`. It uses vector embeddings to enable cross-thread retrieval of domain facts, solving the "entity amnesia" problem where agents repeatedly ask for the same domain context.

**Current architecture (after Phase A):**
- User Memory: `("memory", tenant, user, agent)` — long-term preferences
- Session Memory: `("memory_session", tenant, user, thread)` — thread-scoped facts
- Domain Memory (new): vector collection per tenant — entity-scoped semantic facts

**Constraints:**
- Must reuse existing RAG infrastructure (ChromaDB or pgvector, embedding models)
- Must support configurable decay policies (facts age over time)
- Must enforce tenant isolation (separate collections per tenant)
- Must not add significant latency to agent execution
- Must handle entity name normalization ("Pump A" vs "pump_a" vs "PUMP-A")

## Goals / Non-Goals

**Goals:**
- Provide entity-scoped semantic memory with cross-thread retrieval
- Extract domain facts automatically via LLM with entity recognition
- Support configurable decay policies (never/linear/exponential)
- Reuse RAG infrastructure (embedding models, vector store)
- Enforce tenant isolation via separate collections
- Maintain backward compatibility (domain memory is optional)

**Non-Goals:**
- Frontend UI for domain memory inspection/editing — deferred to Phase C
- Cross-tenant domain memory sharing
- Real-time domain memory streaming
- Automatic entity resolution across different naming conventions (deferred to future phase)
- Domain memory export/import
- GDPR compliance / right-to-be-forgotten (deferred)

## Decisions

### D1: Vector store backend — ChromaDB vs pgvector

**Decision:** Use the same vector store backend as RAG (configured via `rag.vector_store_backend`). If RAG uses ChromaDB, domain memory uses ChromaDB. If RAG uses pgvector, domain memory uses pgvector.

**Rationale:** Reusing the RAG backend avoids introducing a second vector store dependency. The PostgreSQL migration (already completed) supports pgvector, so domain memory automatically benefits from unified storage when `database.backend=postgres`.

**Alternatives considered:**
- Always use ChromaDB — rejected because it contradicts PostgreSQL migration goals
- Always use pgvector — rejected because some deployments still use ChromaDB for RAG
- Separate backend config for domain memory — rejected because it adds configuration complexity

**Implementation:**
```python
def get_domain_vector_store() -> VectorStore:
    rag_config = get_rag_config()
    if rag_config.vector_store_backend == "pgvector":
        return PgVectorStore(collection=f"domain_{tenant_id}")
    else:
        return ChromaVectorStore(collection=f"domain_{tenant_id}")
```

### D2: Collection naming — one per tenant vs one global

**Decision:** Use one vector collection per tenant: `domain_{tenant_id}`. Metadata fields (`domain`, `entity_id`, `user_id`, `thread_id`) filter within the collection.

**Rationale:** Tenant isolation is enforced at the collection level, preventing cross-tenant data leakage. Metadata filtering within a collection is faster than cross-collection queries.

**Alternatives considered:**
- One global collection with tenant_id in metadata — rejected because tenant isolation is weaker (relies on filter correctness)
- One collection per (tenant, domain) — rejected because it fragments data and complicates cross-domain queries

### D3: Entity name normalization

**Decision:** Normalize entity_id by lowercasing, replacing spaces/special chars with underscores, and stripping leading/trailing whitespace. Example: "Pump A" → "pump_a", "Reactor #1" → "reactor_1".

**Rationale:** Simple normalization handles 80% of cases (case variations, punctuation). More sophisticated entity resolution (e.g., "Pump A" vs "Main Feed Pump") is deferred to future phase.

**Alternatives considered:**
- No normalization — rejected because "Pump A" and "pump_a" would be treated as different entities
- LLM-based entity resolution — rejected due to latency and cost (deferred to future phase)

**Implementation:**
```python
import re

def normalize_entity_id(entity_name: str) -> str:
    normalized = entity_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")
```

### D4: Decay policy engine

**Decision:** Implement decay as a post-retrieval filter. Retrieve top-K facts by cosine similarity, then apply decay function to adjust scores based on age. Re-rank by adjusted score and return top-N.

**Rationale:** Applying decay at retrieval time (not storage time) avoids background jobs and keeps facts immutable. Decay parameters are configurable per domain.

**Alternatives considered:**
- Pre-compute decay at storage time — rejected because it requires background jobs to update scores
- No decay — rejected because old facts may become stale (e.g., "Pump A flow rate: 500 GPM" may be outdated after maintenance)

**Implementation:**
```python
def apply_decay(
    facts: list[DomainFact],
    policy: DecayPolicy,
    half_life_days: float,
) -> list[DomainFact]:
    now = datetime.now(UTC)
    for fact in facts:
        age_days = (now - fact.created_at).total_seconds() / 86400
        if policy == DecayPolicy.LINEAR:
            decay_factor = max(0, 1 - age_days / (2 * half_life_days))
        elif policy == DecayPolicy.EXPONENTIAL:
            decay_factor = math.exp(-0.693 * age_days / half_life_days)
        else:  # NEVER
            decay_factor = 1.0
        fact.adjusted_score = fact.similarity_score * decay_factor
    return sorted(facts, key=lambda f: f.adjusted_score, reverse=True)
```

### D5: Domain fact extraction prompt

**Decision:** Use a dedicated LLM prompt for domain fact extraction that focuses on entity recognition and domain classification. Prompt is simpler than User Memory prompt (no `user`/`history` sections to update).

**Rationale:** Domain extraction has different requirements than User Memory (entity-focused vs preference-focused). A dedicated prompt allows tuning for domain-specific patterns.

**Alternatives considered:**
- Reuse User Memory prompt — rejected because it's optimized for preferences, not entities
- No LLM, use regex-based extraction — rejected because it misses complex facts

### D6: Domain configuration — per-domain policies

**Decision:** Domain memory config includes a `domains` dict mapping domain names to their decay policies. Example: `domains: {equipment: {decay: linear, half_life_days: 90}, process: {decay: never}}`.

**Rationale:** Different domains have different aging characteristics. Equipment specs change over time (linear decay), while process definitions are stable (never decay).

**Alternatives considered:**
- Global decay policy for all domains — rejected because it's too coarse
- No decay configuration — rejected because some domains need aging, others don't

## Risks / Trade-offs

### R1: Entity recognition accuracy

**Risk:** LLM-based entity extraction may misidentify entities or assign wrong domains, leading to poor retrieval.

**Mitigation:** Use high confidence threshold (0.8) for domain facts. Log extraction results for monitoring. Future phase: add entity resolution UI for manual correction.

**Trade-off:** Accept 80% accuracy in exchange for automation.

### R2: Cross-tenant data leakage via vector embeddings

**Risk:** Embedding models may encode tenant-specific terminology that leaks across tenants via vector similarity.

**Mitigation:** Tenant isolation at collection level (separate ChromaDB/pgvector collections per tenant). No cross-collection queries.

**Trade-off:** None — this is a hard requirement.

### R3: Vector store latency for domain retrieval

**Risk:** Semantic search adds latency to prompt composition, especially for tenants with many domain facts.

**Mitigation:** Limit retrieval to top-20 facts by similarity. Use metadata filters (`domain`, `entity_id`) to narrow search. Cache frequent queries.

**Trade-off:** First retrieval is slow (~100ms), cached retrievals are fast (~10ms).

### R4: Entity name normalization collisions

**Risk:** Normalization may map different entities to same ID (e.g., "Pump A" and "Pump A (backup)" both become "pump_a").

**Mitigation:** Log normalization collisions. Future phase: add disambiguation UI.

**Trade-off:** Accept occasional collisions in exchange for simplicity.

### R5: Decay policy misconfiguration

**Risk:** Incorrect decay parameters may cause relevant facts to be buried (too aggressive) or stale facts to dominate (too lenient).

**Mitigation:** Provide sensible defaults (linear, 90-day half-life). Log decay statistics for monitoring.

**Trade-off:** Accept suboptimal decay in exchange for configurability.

## Migration Plan

**Deployment:**
1. Deploy code with Domain Memory disabled by default (`domain_memory.enabled: false`)
2. Enable on staging environment for one domain (e.g., `equipment`), monitor for 1 week
3. Enable on production for canary tenants (10%), monitor error rates, latency, retrieval relevance
4. Enable for all tenants, add additional domains incrementally

**Rollback:**
1. Set `domain_memory.enabled: false`
2. Restart Gateway pods
3. Domain memory extraction and retrieval are skipped
4. No data loss (User/Session Memory unaffected)

**Data migration:**
- No migration required. Domain memory is new capability.
- Existing threads work without domain memory.

## Open Questions

1. **Entity resolution:** Should we implement LLM-based entity resolution (e.g., "Pump A" = "Main Feed Pump") in this phase, or defer to future phase? Current design: deferred, use simple normalization.

2. **Cross-tenant domain sharing:** Should we support read-only domain memory sharing across tenants (e.g., shared equipment catalog)? Current design: no, deferred to future phase.

3. **Domain memory UI:** Should we build a basic UI for inspecting domain facts in Phase C, or defer entirely? Current design: deferred to Phase C.

4. **Decay policy granularity:** Should decay be configurable per entity (not just per domain)? Current design: per-domain only, per-entity deferred.

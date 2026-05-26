## ADDED Requirements

### Requirement: Entity-scoped storage with semantic search
The system SHALL store domain memory facts in a vector database (ChromaDB or pgvector) scoped to `(tenant_id, domain, entity_id)`. Each fact SHALL be embedded using the domain's configured embedding model and stored with metadata (timestamp, source_thread, confidence, domain, entity_id).

#### Scenario: New domain fact is embedded and stored
- **WHEN** user says "Pump A has a flow rate of 500 GPM" in a conversation
- **THEN** system extracts fact "Pump A flow rate: 500 GPM", generates embedding, stores at collection `domain_{tenant_id}` with metadata `{domain: "equipment", entity_id: "pump_a", confidence: 0.9}`

#### Scenario: Facts about same entity from different threads are linked
- **WHEN** thread T1 mentions "Pump A needs maintenance" and thread T2 mentions "Pump A was serviced in 2024"
- **THEN** both facts are stored in same entity scope and retrievable via semantic search

#### Scenario: Tenant isolation is enforced
- **WHEN** tenant A queries domain memory
- **THEN** only facts from tenant A's collection are returned, tenant B's facts are not accessible

### Requirement: Domain fact extraction with entity recognition
The system SHALL extract domain-specific facts from conversations using LLM-based analysis. Extracted facts SHALL be tagged with domain (e.g., "equipment", "process", "system") and entity_id (normalized entity name).

#### Scenario: Equipment domain fact is extracted
- **WHEN** user says "The reactor temperature is 350°C"
- **THEN** system extracts fact with domain="equipment", entity_id="reactor", content="Reactor temperature: 350°C"

#### Scenario: Process domain fact is extracted
- **WHEN** user says "The approval workflow requires 3 signatures"
- **THEN** system extracts fact with domain="process", entity_id="approval_workflow", content="Approval workflow requires 3 signatures"

#### Scenario: Ambiguous entity is not extracted
- **WHEN** user says "It's working fine"
- **THEN** system does NOT extract a domain fact (no identifiable entity)

### Requirement: Semantic retrieval with relevance scoring
The system SHALL retrieve domain facts using vector similarity search. Results SHALL be ranked by relevance score (cosine similarity) and filtered by minimum threshold (default 0.7). Retrieval SHALL be limited to configurable max tokens (default 2000).

#### Scenario: Relevant domain facts are retrieved
- **WHEN** agent asks "What is the flow rate of Pump A?"
- **THEN** system retrieves fact "Pump A flow rate: 500 GPM" with relevance score >= 0.8

#### Scenario: Irrelevant facts are filtered
- **WHEN** agent asks about "Pump A" but only facts about "Valve B" exist
- **THEN** retrieval returns empty list (no facts above relevance threshold)

#### Scenario: Large result set is truncated
- **WHEN** 50 facts match query with relevance >= 0.7
- **THEN** top 20 facts (by relevance) are returned, truncated to max_tokens

### Requirement: Configurable decay policies
The system SHALL apply decay policies to domain facts based on age and confidence. Supported policies: `never` (no decay), `linear` (linear decrease over time), `exponential` (exponential decrease). Decayed facts SHALL have reduced relevance scores during retrieval.

#### Scenario: Never decay policy preserves facts indefinitely
- **WHEN** domain is configured with `decay: never`
- **THEN** facts from 1 year ago have same relevance as facts from today

#### Scenario: Linear decay reduces old fact relevance
- **WHEN** domain is configured with `decay: linear, half_life_days: 90`
- **THEN** fact from 90 days ago has 50% relevance, fact from 180 days ago has 25% relevance

#### Scenario: Exponential decay with confidence weighting
- **WHEN** domain is configured with `decay: exponential, half_life_days: 30`
- **THEN** high-confidence fact (0.9) from 60 days ago may outrank low-confidence fact (0.5) from 10 days ago

### Requirement: MemoryMiddleware integration for domain extraction
MemoryMiddleware SHALL extract domain facts in parallel with User Memory and Session Memory updates. Domain extraction SHALL use entity recognition to identify domain and entity_id.

#### Scenario: Conversation triggers domain fact extraction
- **WHEN** user and AI discuss equipment specifications
- **THEN** MemoryMiddleware queues conversation for domain fact extraction alongside user/session memory updates

#### Scenario: Domain extraction failure does not affect other memory layers
- **WHEN** domain fact extraction fails (e.g., LLM error)
- **THEN** User Memory and Session Memory writes continue successfully, error is logged

### Requirement: Basic telemetry for domain memory
The system SHALL track domain memory operations via structured logs. Logs SHALL include tenant_id, domain, entity_id, operation type, relevance scores, and latency.

#### Scenario: Domain memory write is logged
- **WHEN** domain fact is successfully stored
- **THEN** system emits INFO log: "Domain memory saved: tenant=X domain=Y entity=Z latency=Xms"

#### Scenario: Domain memory retrieval is logged
- **WHEN** domain facts are retrieved for prompt composition
- **THEN** system emits DEBUG log: "Domain memory retrieved: tenant=X query=Y facts=N top_score=Z latency=Xms"

### Requirement: Backward compatibility
Existing threads without domain memory SHALL continue to work without modification. Domain memory SHALL be optional and disabled by default until configured.

#### Scenario: Domain memory disabled by default
- **WHEN** system starts with no domain memory configuration
- **THEN** domain memory extraction and retrieval are skipped, no errors occur

#### Scenario: Domain memory enabled for specific domains
- **WHEN** config specifies `domain_memory.domains: ["equipment", "process"]`
- **THEN** only facts matching those domains are extracted, other domains are ignored

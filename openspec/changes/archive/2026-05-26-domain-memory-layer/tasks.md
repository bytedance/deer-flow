# Tasks

## 1. DomainStorage Implementation

- [x] 1.1 Create `DomainStorage` class in `backend/packages/harness/deerflow/agents/memory/domain_storage.py`
- [x] 1.2 Implement vector store backend abstraction supporting ChromaDB and pgvector (reuse RAG config)
- [x] 1.3 Implement collection naming: `domain_{tenant_id}` with tenant isolation
- [x] 1.4 Implement `store_fact(tenant_id, domain, entity_id, content, metadata)` method with embedding generation
- [x] 1.5 Implement `search_facts(tenant_id, query, domain, entity_id, top_k, min_score)` method with vector similarity search
- [x] 1.6 Implement entity name normalization (`normalize_entity_id()`)
- [x] 1.7 Add `get_domain_storage()` function with singleton pattern and lazy initialization
- [x] 1.8 Write unit tests for DomainStorage (namespace isolation, store/search, normalization, tenant isolation)

## 2. Decay Policy Engine

- [x] 2.1 Create `DecayPolicy` enum: `NEVER`, `LINEAR`, `EXPONENTIAL`
- [x] 2.2 Implement `apply_decay(facts, policy, half_life_days)` function that adjusts relevance scores based on age
- [x] 2.3 Implement linear decay: `decay_factor = max(0, 1 - age_days / (2 * half_life_days))`
- [x] 2.4 Implement exponential decay: `decay_factor = exp(-0.693 * age_days / half_life_days)`
- [x] 2.5 Integrate decay into `search_facts()` as post-retrieval filter and re-rank
- [x] 2.6 Write unit tests for decay policies (never, linear, exponential, edge cases)

## 3. Domain Fact Extraction

- [x] 3.1 Create domain extraction prompt in `backend/packages/harness/deerflow/agents/memory/domain_prompt.py`
- [x] 3.2 Implement `extract_domain_facts(messages)` function using LLM to identify domain-specific facts
- [x] 3.3 Implement entity recognition: extract `domain` (e.g., "equipment", "process") and `entity_id` from each fact
- [x] 3.4 Implement confidence filtering (threshold 0.8 by default)
- [x] 3.5 Add `update_domain_memory()` method to `MemoryUpdater` class (similar to `update_session_memory()`)
- [x] 3.6 Write unit tests for domain extraction (equipment facts, process facts, ambiguous entities, confidence filtering)

## 4. Domain Memory Queue

- [x] 4.1 Create `DomainMemoryUpdateQueue` class in `backend/packages/harness/deerflow/agents/memory/domain_queue.py`
- [x] 4.2 Implement `add(thread_id, messages, user_id)` method with debounce (30s default)
- [x] 4.3 Implement `_process_queue()` that calls `extract_domain_facts()` and stores results
- [x] 4.4 Add `get_domain_memory_queue()` singleton accessor
- [x] 4.5 Write unit tests for domain queue (debounce, batching, processing)

## 5. MemoryMiddleware Integration

- [x] 5.1 Update `MemoryMiddleware.after_agent()` to queue conversations for Domain Memory extraction (parallel with User/Session Memory)
- [x] 5.2 Add `domain_memory_enabled` config check before queueing domain updates
- [x] 5.3 Ensure domain extraction failure does not affect User/Session Memory writes
- [x] 5.4 Write unit tests for middleware integration (triple queue, domain disabled, write failure isolation)

## 6. Domain Memory Retrieval

- [x] 6.1 Create `get_domain_context(query, domain, entity_id, max_tokens)` function
- [x] 6.2 Implement semantic retrieval via `DomainStorage.search_facts()`
- [x] 6.3 Implement relevance filtering (min_score threshold, default 0.7)
- [x] 6.4 Implement token budgeting (truncate to max_tokens, default 2000)
- [x] 6.5 Format domain context as string with header "Domain context:"
- [x] 6.6 Write unit tests for retrieval (empty results, relevance filtering, token budgeting)

## 7. Prompt Composition Integration

- [x] 7.1 Update `compose_memory_for_prompt()` to include Domain Memory context alongside User/Session Memory
- [x] 7.2 Allocate token budget: 1500 User, 1500 Session, 1000 Domain, 4000 total
- [x] 7.3 Format output with clear section headers ("User context:", "Session context:", "Domain context:")
- [x] 7.4 Add `domain_memory.injection_enabled` config check
- [x] 7.5 Write unit tests for prompt composition (all three layers, domain only, token overflow)

## 8. Configuration

- [x] 8.1 Add `DomainMemoryConfig` class in `backend/packages/harness/deerflow/config/domain_memory_config.py`
- [x] 8.2 Add fields: `enabled`, `domains` (dict mapping domain → decay policy + half_life_days), `model_name`, `debounce_seconds`, `fact_confidence_threshold`, `max_injection_tokens`, `min_retrieval_score`
- [x] 8.3 Add `get_domain_memory_config()` and `set_domain_memory_config()` functions
- [x] 8.4 Integrate domain memory config into main `AppConfig` (add `domain_memory` section)
- [x] 8.5 Write unit tests for config (defaults, validation, per-domain policies)

## 9. Telemetry

- [x] 9.1 Add structured logging for domain memory writes: "Domain memory saved: tenant=X domain=Y entity=Z latency=Xms"
- [x] 9.2 Add structured logging for domain memory retrieval: "Domain memory retrieved: tenant=X query=Y facts=N top_score=Z latency=Xms"
- [x] 9.3 Add error logging for domain memory failures
- [x] 9.4 Write unit tests verifying log output

## 10. Integration Tests

- [x] 10.1 Write integration test: new conversation → extract domain fact → verify stored in vector DB
- [x] 10.2 Write integration test: store facts about same entity from different threads → verify cross-thread retrieval
- [x] 10.3 Write integration test: domain memory with decay → verify old facts have lower relevance
- [x] 10.4 Write integration test: domain extraction failure → verify User/Session Memory still written
- [x] 10.5 Write integration test: prompt composition with all three memory layers

## 11. Documentation

- [x] 11.1 Create `docs/DOMAIN_MEMORY.md` explaining Domain Memory feature, configuration, and usage
- [x] 11.2 Document domain configuration (per-domain decay policies)
- [x] 11.3 Document entity normalization rules
- [x] 11.4 Update `config.example.yaml` with domain memory section and examples

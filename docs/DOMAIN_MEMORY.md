# Domain Memory

Domain Memory is the third layer in DeerFlow's layered memory system. It captures **entity-specific facts** that persist across threads and conversations, enabling cross-thread knowledge sharing.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Layered Memory System                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   User Memory           Session Memory          Domain Memory        │
│   (Long-term)           (Thread-scoped)         (Entity-scoped)      │
│                                                                      │
│   ┌─────────┐           ┌─────────┐           ┌─────────┐           │
│   │ User    │           │ Thread  │           │ Entity  │           │
│   │ Profile │           │ Summary │           │ Facts   │           │
│   │         │           │         │           │         │           │
│   │ - prefs │           │ - facts │           │ - specs │           │
│   │ - goals │           │ - ctx   │           │ - data  │           │
│   │ - style │           │ - errs  │           │ - hist  │           │
│   └─────────┘           └─────────┘           └─────────┘           │
│                                                                      │
│   Scope: User ID          Scope: Thread ID        Scope: Entity ID   │
│   Persists: Forever       Persists: Thread        Persists: Tenant   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Domain Scope

Domain facts are scoped to `(tenant_id, domain, entity_id)`:

- **tenant_id**: Isolates facts between tenants (multi-tenant support)
- **domain**: Category of the fact (e.g., `equipment`, `process`, `system`)
- **entity_id**: Normalized identifier for the entity (e.g., `pump_a`, `reactor_1`)

### Cross-Thread Retrieval

Unlike Session Memory (which is thread-scoped), Domain Memory enables cross-thread knowledge sharing:

```
Thread 1: "Pump A has a flow rate of 500 GPM"
         ↓ (extracted and stored)
         Domain Storage: {domain: "equipment", entity: "pump_a", fact: "..."}

Thread 2: "What's the flow rate of Pump A?"
         ↓ (semantic search)
         Retrieved: "Pump A flow rate is 500 GPM"
```

### Decay Policies

Domain facts can age based on configurable decay policies:

| Policy | Formula | Use Case |
|--------|---------|----------|
| `never` | No decay (default) | Equipment specs, design decisions |
| `linear` | `1 - age / (2 * half_life)` | Process parameters, calibration data |
| `exponential` | `exp(-0.693 * age / half_life)` | Incident reports, temporary conditions |

## Configuration

Add to `config.yaml`:

```yaml
domain_memory:
  enabled: true
  model_name: null  # Uses default model
  debounce_seconds: 30
  fact_confidence_threshold: 0.8
  injection_enabled: true
  max_injection_tokens: 1000
  min_retrieval_score: 0.7
  
  # Per-domain decay configuration
  domains:
    equipment:
      policy: never
      half_life_days: 365
    process:
      policy: linear
      half_life_days: 90
    incident:
      policy: exponential
      half_life_days: 30
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `false` | Enable domain memory |
| `model_name` | string | `null` | LLM for fact extraction (null = default) |
| `debounce_seconds` | int | `30` | Wait time before processing (1-300) |
| `fact_confidence_threshold` | float | `0.8` | Minimum confidence for storage (0-1) |
| `injection_enabled` | bool | `true` | Inject into system prompt |
| `max_injection_tokens` | int | `1000` | Token budget for injection (100-8000) |
| `min_retrieval_score` | float | `0.7` | Minimum similarity for retrieval (0-1) |
| `domains` | dict | `{}` | Per-domain decay configuration |

## Entity Normalization

Entity names are normalized for consistent lookup:

```python
"Pump A"        → "pump_a"
"Reactor #1"    → "reactor_1"
"Main Feed Pump" → "main_feed_pump"
"VALVE-123"     → "valve_123"
```

Normalization rules:
1. Lowercase
2. Replace non-alphanumeric with underscores
3. Strip leading/trailing underscores

## Domain Categories

The extraction prompt recognizes these domain categories:

| Domain | Examples |
|--------|----------|
| `equipment` | Pumps, valves, motors, sensors |
| `process` | Temperature, pressure, flow rates |
| `system` | Control systems, networks, protocols |
| `material` | Chemicals, raw materials, products |
| `location` | Buildings, rooms, coordinates |
| `specification` | Standards, tolerances, requirements |

## How It Works

### 1. Extraction (Write Path)

```
Conversation → MemoryMiddleware → DomainMemoryUpdateQueue
                                          ↓ (debounce 30s)
                                   extract_domain_facts()
                                          ↓
                                   LLM identifies:
                                   - Domain (equipment)
                                   - Entity (Pump A)
                                   - Fact (flow rate 500 GPM)
                                   - Confidence (0.95)
                                          ↓
                                   DomainStorage.store_fact()
                                          ↓
                                   Vector DB (domain_{tenant_id})
```

### 2. Retrieval (Read Path)

```
Query → get_domain_context()
              ↓
        DomainStorage.search_facts()
              ↓
        Vector similarity search
              ↓
        Apply decay policy
              ↓
        Filter by min_score
              ↓
        Truncate to max_tokens
              ↓
        "Domain context:\n- [equipment/pump_a | 0.92] Flow rate 500 GPM"
```

### 3. Prompt Composition

Domain Memory is combined with User and Session Memory:

```python
compose_memory_for_prompt(thread_id, domain_query="Pump A")
```

Returns:
```
User context:
- Software engineer, prefers Python

Session context:
- Thread summary: Debugging auth service

Domain context:
- [equipment/pump_a | 0.92] Flow rate is 500 GPM
- [equipment/pump_a | 0.88] Last maintenance: 2024-01-15
```

## Token Budget Allocation

Default allocation for prompt injection:

| Layer | Tokens | Purpose |
|-------|--------|---------|
| User Memory | 1500 | User preferences, goals |
| Session Memory | 1500 | Thread context, recent facts |
| Domain Memory | 1000 | Entity-specific knowledge |
| **Total** | **4000** | Combined memory context |

## Telemetry

Domain Memory emits structured logs:

```
# Write
Domain memory saved: tenant=acme domain=equipment entity=pump_a latency=45.2ms

# Read
Domain memory retrieved: tenant=acme query=Pump A facts=3 top_score=0.92 latency=12.5ms

# Errors
Failed to store domain fact: <stack trace>
```

## Storage

Domain facts are stored in the RAG vector store (ChromaDB or pgvector):

- **Collection name**: `domain_{tenant_id}`
- **Embedding**: Generated from fact content
- **Metadata**: `domain`, `entity_id`, `tenant_id`, `confidence`, `created_at`

### Using pgvector

When `database.backend=postgres`, domain memory automatically uses pgvector:

```yaml
database:
  backend: postgres
  # ... connection settings

rag:
  vector_store_backend: pgvector  # Auto-defaulted

domain_memory:
  enabled: true
```

## Testing

Run domain memory tests:

```bash
# All domain tests
pytest tests/test_domain_*.py -v

# Specific test files
pytest tests/test_domain_storage.py -v
pytest tests/test_domain_extraction.py -v
pytest tests/test_domain_queue.py -v
pytest tests/test_domain_retrieval.py -v
pytest tests/test_domain_memory_config.py -v
pytest tests/test_memory_middleware_domain.py -v
```

## Comparison: Session vs Domain Memory

| Aspect | Session Memory | Domain Memory |
|--------|---------------|---------------|
| Scope | Thread ID | Entity ID |
| Persistence | Thread lifetime | Tenant lifetime |
| Cross-thread | No | Yes |
| Use case | Conversation context | Entity knowledge |
| Decay | No | Optional |
| Storage key | `session_{thread_id}` | `domain_{tenant_id}` |

## Migration from Session Memory

If you're currently storing entity-specific facts in Session Memory, consider migrating to Domain Memory:

1. **Identify entity facts**: Facts about equipment, processes, systems
2. **Enable domain memory**: Set `domain_memory.enabled: true`
3. **Configure decay**: Set appropriate policies per domain
4. **Monitor**: Check telemetry for extraction quality

Session Memory remains ideal for:
- Thread-specific context
- Temporary debugging info
- User corrections within a conversation

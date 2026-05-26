# Session Memory

Thread-scoped memory that persists conversation context for the lifetime of a thread, surviving message summarization to maintain continuity in long conversations.

## Overview

Session Memory complements User Memory:

| | User Memory | Session Memory |
|---|---|---|
| **Scope** | Cross-thread, per-user | Per-thread |
| **Lifetime** | Persistent | Thread-bound |
| **Backend** | File or Store | Store only (PostgreSQL) |
| **Purpose** | Long-term preferences | Thread continuity |
| **Namespace** | `("memory", tenant, user)` | `("memory_session", tenant, user, thread)` |

## Architecture

```
Message arrives
    │
    ▼
MemoryMiddleware.after_agent()
    │
    ├── User Memory Queue (30s debounce)
    │       └── MemoryUpdater.update_memory()
    │               └── StoreMemoryStorage / FileMemoryStorage
    │
    └── Session Memory Queue (30s debounce)
            └── MemoryUpdater.update_session_memory()
                    └── SessionStorage (LangGraph Store)

Prompt composition
    │
    ▼
compose_memory_for_prompt()
    ├── User Memory (max 2000 tokens)
    └── Session Memory (max 2000 tokens)
```

## Data Structure

```json
{
  "version": "1.0",
  "lastUpdated": "2024-01-15T10:30:00Z",
  "session_context": {
    "summary": "Debugging JWT token expiration issue in staging",
    "updatedAt": "2024-01-15T10:30:00Z"
  },
  "facts": [
    {
      "id": "fact_abc123",
      "content": "JWT token expires after 1 hour in staging",
      "category": "context",
      "confidence": 0.95,
      "source": "thread_xyz",
      "createdAt": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### Fact Categories

- `context` — Thread-specific background (project name, environment, issue ID)
- `decision` — Choices made during this thread
- `constraint` — Limitations discovered (API rate limits, data format requirements)
- `correction` — Explicit agent mistakes or user corrections in this thread
- `progress` — Milestones reached, steps completed

## Configuration

```yaml
session_memory:
  enabled: false
  model_name: null
  debounce_seconds: 30
  max_facts: 100
  fact_confidence_threshold: 0.7
  injection_enabled: true
  max_injection_tokens: 2000
```

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | Master switch for session memory |
| `model_name` | `null` | LLM model for fact extraction (null = default model) |
| `debounce_seconds` | `30` | Wait time before processing queued updates |
| `max_facts` | `100` | Maximum facts stored per thread |
| `fact_confidence_threshold` | `0.7` | Minimum confidence for fact storage |
| `injection_enabled` | `true` | Whether to inject into system prompt |
| `max_injection_tokens` | `2000` | Token budget for prompt injection |

## Requirements

Session Memory requires the **StoreMemoryStorage** backend (LangGraph Store backed by PostgreSQL). It is automatically disabled when using `FileMemoryStorage`.

## Cache Invalidation

Session memory reads are cached in-memory with an LRU cache (max 256 entries). The cache is automatically invalidated when session memory is written to for the same thread.

## Integration Points

### Middleware

`MemoryMiddleware.after_agent()` queues conversations for both User Memory and Session Memory updates. Session memory queue failures are isolated and do not affect User Memory writes.

### Prompt Composition

`compose_memory_for_prompt()` merges User Memory and Session Memory into a single context block:

```
<memory>
User context:
- Work: Backend developer, working on API integration
- Current Focus: Debugging authentication issues

Session context:
Thread summary: Investigating JWT token expiration in staging
Session facts:
- [context | 0.95] JWT token expires after 1 hour in staging
- [decision | 0.90] Solution: extend token lifetime to 24 hours
</memory>
```

Both sections have independent `injection_enabled` toggles.

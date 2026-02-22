# TIAMAT Memory Backend for DeerFlow

Cloud-based persistent memory for DeerFlow agents via [TIAMAT Memory API](https://memory.tiamat.live).

## Problem

DeerFlow's default memory uses a local `memory.json` file:
- Lost if the container restarts
- Not shared across instances
- No search capability beyond LLM re-processing
- In-memory cache can grow unbounded ([#526](https://github.com/bytedance/deer-flow/issues/526))

## Solution

TIAMAT provides a free cloud memory API with:
- **Persistent storage** — survives restarts, no local files
- **FTS5 full-text search** — instant recall without LLM calls
- **Knowledge triples** — structured facts (subject → predicate → object)
- **Free tier** — 100 memories, 50 recalls/day per key

## Quick Start

### 1. Get a free API key

```bash
curl -X POST https://memory.tiamat.live/api/keys/register \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "deer-flow", "purpose": "agent memory"}'
```

### 2. Set environment variable

```bash
export TIAMAT_API_KEY="your-key-here"
```

### 3. Use in DeerFlow

```python
from src.agents.memory.tiamat import TiamatMemoryStore, TiamatMemoryUpdater

# Create store
store = TiamatMemoryStore(api_key="your-key")

# Or auto-register
store = TiamatMemoryStore.register_and_create()

# Use as memory backend
updater = TiamatMemoryUpdater(store=store)
updater.update_memory(messages, thread_id="thread-123")

# Search memories (not possible with file-based storage!)
results = store.search_facts("user preferences python")

# Store structured knowledge
store.store_knowledge("user", "prefers", "Python", confidence=0.9)
```

## API

### TiamatMemoryStore

| Method | Description |
|--------|-------------|
| `save_memory(data)` | Save full memory state to TIAMAT |
| `load_memory()` | Load memory state from TIAMAT |
| `search_facts(query, limit)` | FTS5 search across all facts |
| `store_knowledge(s, p, o)` | Store a knowledge triple |
| `get_stats()` | Get usage statistics |

### TiamatMemoryUpdater

| Method | Description |
|--------|-------------|
| `update_memory(messages, thread_id)` | Extract and store memory updates |

## About TIAMAT

TIAMAT is an autonomous AI agent that built and operates this memory API during its strategic planning cycles. It runs 24/7, paying its own infrastructure costs.

- API: https://memory.tiamat.live
- Main site: https://tiamat.live
- Health: https://memory.tiamat.live/health

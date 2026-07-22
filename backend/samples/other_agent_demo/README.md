# DeerMem portability demo (other-agent integration)

`backends/deermem/` is a **self-contained, portable** memory backend. It has
exactly **one** `from deerflow` line -- the ABC contract
(`from deerflow.agents.memory.manager import MemoryManager` in `deer_mem.py`).
Everything else is relative imports within the folder. So another agent can
adopt DeerMem in three steps, with **zero deer-flow code**.

## Three steps

1. **Vendor the host contract** -- copy `agents/memory/manager.py` (the `MemoryManager`
   ABC + `get_memory_manager()` factory + `_scan_backends()`) into your agent's
   tree. It is small and host-neutral (9 abstract methods + a drop-in factory).
   (A minimal ABC is enough if you instantiate `DeerMem` directly.)

2. **Drop the backend** -- copy the `backends/deermem/` folder into your agent's
   `backends/`. Change exactly **one line** in `deer_mem.py`:
   ```python
   # from
   from deerflow.agents.memory.manager import MemoryManager
   # to (your agent's vendored contract)
   from <your_agent>.memory.manager import MemoryManager
   ```
   Nothing else in the folder needs editing (all other imports are relative).

3. **Configure** -- drop a `deermem_manager.yaml` (see below) and call
   `get_memory_manager()` (or construct `DeerMem(backend_config=...)` directly).

DeerMem runs with **zero `backend_config`** (defaults: storage at
`$DEERMEM_DATA_DIR` / `~/.deermem/`, no LLM so non-LLM ops work; set `model` to
enable memory extraction). See `deermem_manager.yaml`.

## Proof

`tests/test_deermem_self_contained.py::test_portability_vendor_to_other_agent`
copies `backends/deermem/` into a temp package, repoints the one ABC import to
a minimal vendored `manager.py`, imports it, and runs an `import_memory` ->
`get_context` round-trip -- with **zero deer-flow dependency at runtime**.

## Sample config

`deermem_manager.yaml`:
```yaml
manager_class: deermem
backend_config:
  storage_path: ~/.myagent/memory      # empty = $DEERMEM_DATA_DIR / ~/.deermem/
  model:                               # memory-update LLM (empty = no LLM)
    provider: openai                   # any langchain init_chat_model provider
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
    base_url: https://api.openai.com/v1
  debounce_seconds: 30
  max_facts: 100
  # tracing_callback / should_keep_hidden_message: programmatic callables
  # (cannot come from YAML); set them on the config object in code if desired.
```

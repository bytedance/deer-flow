# Memory Backends

Each subfolder under `agents/memory/backends/` is a pluggable memory backend. Swap the active one by changing one line in `config.yaml` - no deer-flow core changes required.

- `deermem/` - the default backend (deer-flow's own: structured facts + JSON storage).
- `noop/` - an empty backend and the **template** to copy when adding a new one.

This guide tells you **which files to touch** when you change, swap, or add a memory system. Paths are relative to `backend/` unless noted.

---

## Table of Contents

- [Add a New Backend](#add-a-new-backend)
- [Switch the Active Backend](#switch-the-active-backend)
- [Backend Contract](#backend-contract)
- [Do Not Modify](#do-not-modify)
- [Common Pitfalls](#common-pitfalls)
- [Reference](#reference)

## Add a New Backend

Copy `noop/` to `backends/<yourname>/` and edit three files in this folder plus two outside it.

| File | What to change |
|---|---|
| `backends/<yourname>/config.py` | Declare your config fields + `from_backend_config` (parse `backend_config`; read `storage_path` from it - **do not import deer-flow path helpers**) |
| `backends/<yourname>/<yourname>_manager.py` | Rename the class; parse config in `__init__`; implement the 9 ABC methods; optionally implement fact CRUD (see [Backend Contract](#backend-contract)) |
| `backends/<yourname>/__init__.py` | `MANAGER_CLASS = YourManager` (relative import) |
| `config.yaml` (repo root, parent of `backend/`) | `memory.manager_class: <yourname>` + your knobs under `memory.backend_config` |
| `packages/harness/pyproject.toml` | **Only if the backend needs external libs**: declare the dependency; add `[tool.uv.sources]` for vendored source. Otherwise `uv sync` purges it (see [Common Pitfalls](#common-pitfalls)) |

See the docstring at the top of `noop/noop_manager.py` for the full 6-step walkthrough.

## Switch the Active Backend

Edit `config.yaml` (repo root) only:

```yaml
memory:
  manager_class: <name>        # deermem / noop / <yourname>
  backend_config: { ... }      # that backend's private config
```

Then **restart deer-flow** - the memory manager is a process-level singleton; a running process does not hot-reload config or backend code.

## Backend Contract

### 1. The 9 ABC methods

Implement every method on `MemoryManager` in `packages/harness/deerflow/agents/memory/manager.py`. Signatures must match (parameter names, keyword-only args). `noop` is the empty-implementation reference.

### 2. Return shape (critical, easy to get wrong)

`get_memory` / `export_memory` / `clear_memory` / `import_memory` return a dict that the gateway casts to the **DeerMem shape** (`MemoryResponse`: `version` / `lastUpdated` / `user` / `history` / `facts[]`). Your backend must return a dict this shape accepts, or:

- the data is silently dropped (pydantic ignores unknown fields);
- the frontend gets empty defaults and `lastUpdated=""` crashes the date formatter.

A non-DeerMem backend maps its native records (e.g. `{"results": [...]}`) into this shape via a small adapter helper.

### 3. Optional capabilities (DeerMem-internal, not on the ABC)

The gateway probes these with `hasattr(manager, "<name>")` and returns 501 when absent:

- `create_fact` / `delete_fact` / `update_fact` - the frontend's add/delete/edit-fact buttons. Signatures are in the commented block at the bottom of `noop/noop_manager.py`.
- `reload_memory` - the frontend's reload button (delegate to `get_memory` if your backend has no cache).
- `warm` - one-time warm-up at gateway startup (skipped if absent).

Implement the ones you support; leave the rest as 501.

### 4. Portability (the golden rule)

> [!IMPORTANT]
> A backend talks to the host through exactly **two channels**: (1) the ABC method arguments (`manager.py`), and (2) the `backend_config` dict. The **only** `from deerflow` import allowed anywhere in your backend folder is the ABC contract line in `<name>_manager.py`:

```python
from deerflow.agents.memory.manager import MemoryManager
```

Change that one line (and only that line) to port the backend to another agent. **Do not import deer-flow path helpers, config singletons, or models** - get `storage_path` and everything else from `backend_config`.

### 5. What the host injects into `backend_config`

The factory (`manager.py::get_memory_manager`) injects these for every backend:

- `storage_path` (str) - a writable state dir (the host's `runtime_home` by default, or whatever `config.yaml` sets). **Use this as your storage root.**
- `tracing_callback` (Callable | None) - trace your LLM calls (langfuse). Ignore if you don't trace.
- `should_keep_hidden_message` (Callable | None) - filter `hide_from_ui` messages. Ignore if not relevant.
- Plus whatever the user puts under `config.yaml::memory.backend_config` (your backend's own knobs).

## Do Not Modify

These are backend-agnostic. Don't touch them when swapping backends (unless you're changing the **shared contract**, which affects every backend):

| File | Role |
|---|---|
| `packages/harness/deerflow/agents/memory/manager.py` | ABC + factory + scanner |
| `packages/harness/deerflow/agents/middlewares/memory_middleware.py` | `after_agent` -> `manager.add` |
| `packages/harness/deerflow/agents/memory/summarization_hook.py` | summarization -> `manager.add_nowait` |
| `packages/harness/deerflow/agents/lead_agent/prompt.py` | `_get_memory_context` -> `manager.get_context` |
| `app/gateway/routers/memory.py` | HTTP endpoints -> `manager.*` (hasattr-probed) |
| `packages/harness/deerflow/config/memory_config.py` | shared 4 fields (`enabled` / `injection_enabled` / `manager_class` / `backend_config`) |
| `frontend/src/components/workspace/settings/memory-settings-page.tsx` | frontend memory page (assumes DeerMem shape) |

> [!NOTE]
> The gateway and frontend are currently hard-coded to the DeerMem shape - that's why backends must return DeerMem-shape data (contract #2). Making them fully backend-agnostic is a larger refactor; see `E:\deerflow\memory\plugin\00-插件兼容性矩阵.md`.

## Common Pitfalls

Lessons from integrating external backends:

1. **External deps must be declared in `pyproject.toml`.** A bare `uv pip install` is purged on the next `uv sync` / `langgraph dev`. Declare the dep (and `[tool.uv.sources]` for vendored source).
2. **Return the DeerMem shape.** Otherwise the frontend crashes with `Invalid time value` and your data is silently dropped. Build a small adapter helper to map your native records into it.
3. **Fact CRUD returns 501 if not implemented.** The frontend's delete-fact button reports `Operation 'delete fact' not supported`. Implement `delete_fact` (and friends) to fix it.
4. **Don't import `runtime_home`.** Read `storage_path` from `backend_config`. (The `noop` template shows the correct pattern; importing deer-flow path helpers breaks portability - contract #4.)
5. **Restart deer-flow after changes.** The manager is a process-level singleton; a running process does not hot-reload config or backend code.
6. **Cap `get_context` length yourself.** The host applies no token budget; the backend must truncate (DeerMem has `max_injection_tokens`; noop does not).

## Reference

- **Template**: `noop/` - empty implementation with full docstrings; copy and go.
- **Design proposal**: `E:\deerflow\memory\记忆系统方案.md`.
- **Plugin plans + compatibility matrix**: `E:\deerflow\memory\plugin\` (`00-插件兼容性矩阵.md` is the spine; defines the 9 shared contracts S1-S9).

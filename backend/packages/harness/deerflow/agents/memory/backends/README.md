# Memory Backends

Each subfolder under `agents/memory/backends/` is a pluggable memory backend. Swap the active one by changing one line in `config.yaml` - no deer-flow core changes required.

- `deermem/` - the default backend (deer-flow's own: structured facts + JSON storage).
- `noop/` - an empty backend and the **template** to copy when adding a new one.
- `openviking/` - optional remote backend using the official
  `langchain-openviking` package (single-user middleware mode).
- `honcho/` - optional remote Honcho backend over HTTP: user-model memory (representations built by Honcho's server-side deriver; no local LLM calls). Workspace-per-user isolation with per-user overrides.

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
| `backends/<yourname>/<yourname>_manager.py` | Rename the class; parse config in `model_post_init`; implement `from_config` + the tier-1 abstracts (`add`/`get_context`); override tier-2/3 methods as needed (see [Backend Contract](#backend-contract)) |
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

### 1. The three-tier contract

`MemoryManager` is a pydantic `BaseModel` (not a bare ABC). Methods are tiered:

- **Tier 1 (abstract)** -- `add` + `get_context`: every backend MUST implement (write + read-inject are the backend's fundamental duties; missing one is caught at instantiation).
- **Tier 2 (management, with defaults)** -- `add_nowait` (delegates to `add`), `search` / `get_memory` / `clear_memory` / `import_memory` / `export_memory` / `delete_memory` (default `raise NotImplementedError`), `shutdown_flush` (default `True`). Override the ones your backend supports.
- **Tier 3 (optional hooks, with defaults)** -- `warm` (default `True`), `reload_memory` / `create_fact` / `delete_fact` / `update_fact` (default raise), `on_pre_compress` / `on_turn_start` (default no-op).

A new backend implements `from_config` + `add` + `get_context` and overrides only what it supports; the rest inherits defaults. Signatures must match (parameter names, keyword-only args). `noop` is the minimal reference.

### 2. Return shape (critical, easy to get wrong)

`get_memory` / `export_memory` / `clear_memory` / `import_memory` return a dict that the gateway casts to the **DeerMem shape** (`MemoryResponse`: `version` / `lastUpdated` / `user` / `history` / `facts[]`). Your backend must return a dict this shape accepts, or:

- the data is silently dropped (pydantic ignores unknown fields);
- the frontend gets empty defaults and `lastUpdated=""` crashes the date formatter.

A non-DeerMem backend maps its native records (e.g. `{"results": [...]}`) into this shape via a small adapter helper.

### 3. Tier-3 hooks (contracted, no `hasattr` probing)

`create_fact` / `delete_fact` / `update_fact` / `reload_memory` / `warm` are tier-3 hooks ON the base contract (with defaults). Callers (gateway / client / tools) invoke them directly and catch `NotImplementedError` for unsupported backends -- no more `hasattr` probing.

- `create_fact` / `delete_fact` / `update_fact` - the frontend's add/delete/edit-fact buttons. Default raises (caller returns 501).
- `reload_memory` - the frontend's reload button (caller falls back to `get_memory` on `NotImplementedError`).
- `warm` - one-time warm-up at gateway startup (default `True` = nothing to warm).

Implement the ones your backend supports; the rest inherit the default raise.

### 4. Portability (the golden rule)

> [!IMPORTANT]
> A backend talks to the host through exactly **two channels**: (1) the ABC method arguments (`manager.py`), and (2) the `backend_config` dict. The **only** `from deerflow` import allowed anywhere in your backend folder is the ABC contract line in `<name>_manager.py`:

```python
from deerflow.agents.memory.manager import MemoryManager
```

Change that one line (and only that line) to port the backend to another agent. **Do not import deer-flow path helpers, config singletons, or models** - get `storage_path` and everything else from `backend_config`.

### 5. What the host provides

The factory (`manager.py::get_memory_manager`) resolves the backend class, injects `storage_path` into `backend_config`, then calls `cls.from_config(backend_config, mode=cfg.mode, **host_hooks)`. The host hooks (passed as `from_config` kwargs, NOT in `backend_config`):

- `backend_config["storage_path"]` (str) - a writable state dir (the host's `runtime_home` by default, or whatever `config.yaml` sets). **Use this as your storage root.**
- `callbacks` (`MemoryCallbacks` | None) - observability; `on_memory_llm_call` merges trace metadata before your LLM call (langfuse). Pass it to your LLM path; ignore if you don't trace.
- `should_keep_hidden_message` / `trace_context_manager` / `host_llm_factory` - other host hooks; consume in `from_config` if relevant.
- Plus whatever the user puts under `config.yaml::memory.backend_config` (your backend's own knobs).

Each backend's `from_config` consumes the hooks it needs (DeerMem does; noop ignores them).

## Do Not Modify

These are backend-agnostic. Don't touch them when swapping backends (unless you're changing the **shared contract**, which affects every backend):

| File | Role |
|---|---|
| `packages/harness/deerflow/agents/memory/manager.py` | ABC + factory + scanner |
| `packages/harness/deerflow/agents/middlewares/memory_middleware.py` | `after_agent` -> `manager.add` |
| `packages/harness/deerflow/agents/memory/summarization_hook.py` | summarization -> `manager.add_nowait` |
| `packages/harness/deerflow/agents/lead_agent/prompt.py` | `_get_memory_context` -> `manager.get_context` |
| `app/gateway/routers/memory.py` | HTTP endpoints -> `manager.*` (direct call + try/except `NotImplementedError`) |
| `packages/harness/deerflow/config/memory_config.py` | shared 4 fields (`enabled` / `injection_enabled` / `manager_class` / `backend_config`) |
| `frontend/src/components/workspace/settings/memory-settings-page.tsx` | frontend memory page (assumes DeerMem shape) |

> [!NOTE]
> The gateway and frontend are currently hard-coded to the DeerMem shape - that's why backends must return DeerMem-shape data (contract #2). Making them fully backend-agnostic is a larger refactor.

## Common Pitfalls

Lessons from integrating external backends:

1. **External deps must be declared in `pyproject.toml`.** A bare `uv pip install` is purged on the next `uv sync` / `langgraph dev`. Declare the dep (and `[tool.uv.sources]` for vendored source).
2. **Return the DeerMem shape.** Otherwise the frontend crashes with `Invalid time value` and your data is silently dropped. Build a small adapter helper to map your native records into it.
3. **Fact CRUD returns 501 if not implemented.** The frontend's delete-fact button reports `Operation 'delete fact' not supported`. Implement `delete_fact` (and friends) to fix it.
4. **Don't import `runtime_home`.** Read `storage_path` from `backend_config`. (The `noop` template shows the correct pattern; importing deer-flow path helpers breaks portability - contract #4.)
5. **Restart deer-flow after changes.** The manager is a process-level singleton; a running process does not hot-reload config or backend code.
6. **Cap `get_context` length yourself.** The host applies no token budget; the backend must truncate (DeerMem has `max_injection_tokens`; noop does not).

## Honcho Backend

The optional `honcho/` backend is a remote-only HTTP adapter for user-model memory over Honcho (self-hosted or via api.honcho.dev). Middleware mode is the default; tool mode is also supported (search is implemented) and retains passive writes via `MemoryMiddleware` (`requires_passive_writes_in_tool_mode = True`) so Honcho's server-side deriver keeps building representations from every turn (no local LLM calls).

**Configuration** (under `memory.backend_config`):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `base_url` | str | `http://localhost:8000` | Honcho instance URL (e.g., `http://localhost:8000` or `https://api.honcho.dev`) |
| `api_key` | str | optional | API key for hosted Honcho; required if `base_url` is `api.honcho.dev`. Can use `$HONCHO_API_KEY` env var syntax. Requires `allow_insecure_http: true` when using plain HTTP |
| `allow_insecure_http` | bool | false | Allow HTTP (non-HTTPS) connections; needed for localhost development with api_key |
| `timeout_seconds` | float | `10.0` | HTTP client timeout (seconds) for calls to Honcho — read/write/pool; see `connect_timeout_seconds` for the connect phase |
| `connect_timeout_seconds` | float | `3.0` | HTTP connect timeout (seconds) for establishing the connection to Honcho |
| `workspace_prefix` | str | `deerflow-u-` | Prefix for isolated workspaces; each user gets one workspace named `{prefix}{sanitized_id}` |
| `workspace_overrides` | dict | `{}` | Map specific user ids to custom workspace names; overrides the prefix-based derivation. Values must be non-empty (parse error otherwise). Mapping several users to one workspace shares its search index across them (see Workspace Resolution) |
| `user_peer_overrides` | dict | `{}` | Map specific user ids to custom names for the user's own peer; overrides the stable-id derivation. Values must be non-empty (parse error otherwise) |
| `assistant_peer` | str | `deerflow` | Default peer name for the assistant when storing messages |
| `message_char_limit` | int | `8000` | Character limit per message; longer messages are truncated |
| `max_injection_chars` | int | `6000` | Character limit for injected memory into the system prompt |
| `failure_policy.read` | str | `fail_open` | Recall failure handling: `fail_open` (log and return empty) or `fail_closed` (rethrow) |

**Workspace Resolution**: Each DeerFlow user maps to one Honcho workspace. The workspace name is derived as: `workspace_overrides[user_id]` (if present) else `workspace_prefix + sanitized_id`, where `sanitized_id` is a collision-resistant hash suffix (sanitize[:48]-sha256[:8]). Missing user fails closed to no memory. The default derivation is isolated per user; a `workspace_overrides` entry that maps several users to one workspace deliberately shares that workspace's **search index** across them (`search` uses Honcho's workspace-scoped `/search`, which has no peer filter), while `get_context` / `get_memory` remain peer-scoped.

**Tool Mode**: While tool-mode memory tools are not fully supported, the backend implements `requires_passive_writes_in_tool_mode = True` to retain passive writes via MemoryMiddleware while also enabling memory search through the `memory_search` tool.

## Reference

- **Template**: `noop/` - minimal implementation with full docstrings; copy and go.
- **Contract + factory**: `packages/harness/deerflow/agents/memory/manager.py` (`MemoryManager` base, `MemoryCallbacks`, `get_memory_manager` factory).

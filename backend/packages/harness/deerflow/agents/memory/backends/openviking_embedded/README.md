# OpenViking memory backend (embedded)

Adapts [OpenViking](https://github.com/volcengine/OpenViking) as a deerflow memory
backend, running **embedded** in the deerflow process (no separate server).

OpenViking is an agent-native context database. `add()` hands a conversation to
OpenViking's **session pipeline** (`create_session` + `add_message` +
`commit_session`); OpenViking then uses the VLM configured in `ov.conf` to
**extract structured memories** (preferences / entities / profile / ...) from the
conversation and stores them as files under `viking://user/{space}/memories/`. The
backend surfaces those distilled memories (not raw transcripts) to deerflow.

## Write strategy: session pipeline

`add()` / `add_nowait()` never store raw transcripts. Each call:

1. `create_session(session_id="{thread_id}-{nonce}")` — a fresh session per call
   keeps `add_message` idempotent, since the host passes the full (growing)
   history on each debounced `add`.
2. `add_message(session_id, role, content)` per turn (`human`→`user`,
   `ai`→`assistant`).
3. `commit_session(session_id)` — archives the session and runs **memory
   extraction** (the VLM). The extracted memories land under
   `memories/preferences/...`, `memories/entities/...`, `memories/profile.md`,
   etc. OpenViking consolidates duplicates across sessions.

`add()` returns immediately (extraction runs async on OpenViking's shared
background loop) when `wait_on_write: false`; `add_nowait()` (the
summarization-flush path) blocks until extraction finishes so memories are
captured before the source messages are dropped.

A **VLM is required** for extraction. Without one, `commit_session` archives but
extracts nothing, so `get_memory` will be empty.

## Install

The `plugin.yaml` in this folder declares `openviking` as the external
dependency. The factory auto-installs it on first selection (no `uv sync
--extra` needed, and deps land outside the venv so `uv sync` never wipes
them). Just set `memory.allow_lazy_installs: true` in `config.yaml` and
select `manager_class: openviking_embedded` -- the rest is automatic.

The `import openviking` inside the backend is lazy, so deerflow starts fine
without the dependency installed; only selecting `manager_class: openviking_embedded`
without it raises a clear `ImportError` (wrapped as `MemoryManagerError`).

## Configure OpenViking's providers

Two ways (pick one):

### Integrated (recommended — everything in deerflow's config.yaml)

Set `embedding` / `vlm` (or the raw `ov_conf`) under `backend_config` in
deerflow's `config.yaml`. The backend writes `<data_path>/ov.conf` from these
and points OpenViking at it via the `OPENVIKING_CONFIG_FILE` env var. No
separate `~/.openviking/ov.conf`, no `openviking-server init`.

See the `config.example.yaml` openviking block for the full annotated example.

- **embedding** — shortcut for `ov_conf.embedding.dense` (provider, model,
  api_base, api_key, dimension, input).
- **vlm** — shortcut for `ov_conf.vlm` (provider, model, api_base, api_key,
  etc.). Any OpenAI-compatible chat model works. `$ENV` refs in api_key are
  expanded by OpenViking at load time (deerflow's `load_dotenv` already set
  `os.environ`).
- **ov_conf** — a raw dict written verbatim as ov.conf. Full control over
  every OpenViking field (rerank, storage, parsers, encryption, search_mode,
  …). When present, it is the base; `embedding` / `vlm` are merged on top if
  set.
- `auto_generate_l0`, `auto_generate_l1`, `memory.version`,
  `memory.extraction_enabled` default to the backend's required values
  (`true`/`false`/`"v2"`/`true`); override them in `ov_conf` if needed.

### Legacy (standalone ov.conf)

Embedded mode reads the same config as the OpenViking server:
`~/.openviking/ov.conf`. Generate it interactively:

```bash
openviking-server init   # picks embedding / VLM / rerank / vector-db providers
openviking-server doctor  # validate connectivity
```

Required: **embedding provider** + **VLM** for extraction (`commit_session`).
`auto_generate_l0: true` and `memory.extraction_enabled: true` are also
needed. `$ENV` vars in `ov.conf` are expanded by OpenViking at load time
(deerflow's dotenv already set `os.environ`).

## Configure deerflow

In your `config.yaml` (copy from `config.example.yaml`):

```yaml
memory:
  enabled: true
  injection_enabled: true
  manager_class: openviking_embedded
  mode: middleware
  backend_config:
    # OpenViking store directory (passed as OpenViking(path=...)). Empty =
    # {storage_path}/openviking; {storage_path} is host-injected (deerflow's
    # runtime home). OpenViking owns its own storage layout.
    data_path: ""
    # User space in the viking URI tree -> viking://user/{user_space}/memories.
    user_space: "default"
    # Minimum semantic score for search() results; 0.0 = no filter.
    score_threshold: 0.0
    search_limit: 5
    # Character budget for get_context() injection text (backend truncates).
    max_injection_chars: 2000
    per_file_injection_chars: 500
    # Whether add() blocks on extraction. add_nowait() (summarization-flush
    # path) always blocks. false = fire-and-forget (extraction runs async).
    wait_on_write: false
    write_timeout: 60.0
```

Restart deerflow after switching backends — the memory manager is a
process-level singleton.

## How it maps to the MemoryManager contract

| MemoryManager method | OpenViking operation |
| --- | --- |
| `from_config` / `model_post_init` | `OpenViking(path=data_path, actor_peer_id=…)` (lazy `initialize()` on first use / `warm()`) |
| `add` / `add_nowait` | `create_session` + `add_message`(per turn) + `commit_session` (extraction); `add_nowait` waits via `get_task` |
| `get_context` | `ls(memories, recursive)` → `read()` each (distilled memory), joined + truncated |
| `search` | `find(query, target_uri=memories, limit, score_threshold, context_type="memory")` → `FindResult.memories` → fact dicts |
| `get_memory` | `ls` extracted memory files → `read()` + `stat()` → build `display: {sections: [...]}` (only derived helper files `.abstract.md` / `.overview.md` / `.relations.json` are filtered; identity/soul/profile are legitimate memory types shown as-is). `facts[]` stays empty — the memory panel renders display sections. |
| `clear_memory` | `rm(scope, recursive=True)` — ``agent_name=None`` clears **all** memories (ABC contract); an explicit ``agent_name`` clears only that agent's scoped facts |
| `import_memory` | 2-layer waterfall: Layer 1 restores native `data.files` via stat→replace upsert (lossless round-trip); Layer 2 feeds all text through `create_session` + `add_message` + `commit_session` so the VLM re-extracts memories in OpenViking's own format (cross-backend path, e.g. from DeerMem). |
| `create_fact` / `delete_fact` / `update_fact` | ``create_fact`` writes to ``memories/{agent}/{category}/`` (agent-scoped); ``delete_fact`` / ``update_fact`` operate on the specific encoded URI |
| `warm` | `initialize()` + `is_healthy()` |
| `shutdown_flush` | `close()` |

### Agent scoping

Manual facts (``create_fact``, ``import_memory`` Layer 1) are **agent-scoped**:
``agent_name=None`` resolves to ``"__default__"`` (matching DeerMem's
``DEFAULT_AGENT_BUCKET``), and explicit names are lowercased.  Facts are written
to ``viking://user/{space}/memories/{agent}/{category}/...``.

Extracted memories (the session pipeline) land at the root ``memories/`` level
because OpenViking's extraction engine does not accept a per-agent output path.
Reads stay at the root level so both scoped facts and shared extracted memories
are visible to every agent.

``clear_memory(agent_name=X)`` removes only agent X's scoped facts (extracted
memories at root level survive).  ``clear_memory(agent_name=None)`` clears
**all** memories (ABC contract: *"agent_name=None means all memory owned by the
user"*).

### Fact ids

Fact ids surfaced to the frontend are `base64url(viking_uri)`. The raw viking URI
contains `/` and `:`, which FastAPI's `/memory/facts/{fact_id}` route cannot
capture (Starlette decodes `%2F` back to `/` → 404). base64url has no `/`/`:`, so
ids survive a round trip through the URL path; `delete_fact` / `update_fact`
decode them back to URIs.

## Smoke test (standalone, no gateway)

```python
from deerflow.agents.memory.backends.openviking_embedded import OpenVikingMemoryManager

m = OpenVikingMemoryManager.from_config(
    {"data_path": "./runtime/openviking-smoke", "user_space": "default",
     "wait_on_write": True}
)
# Construction is lazy -- warm() opens the store + loads the embedding model.
# If it returns False, ov.conf is missing/misconfigured: run `openviking-server init`.
assert m.warm(), "warm() failed -- is ~/.openviking/ov.conf configured (embedding+VLM)?"
m.add("t1", [
    {"role": "user", "content": "I prefer answers with code examples."},
    {"role": "assistant", "content": "Got it -- I'll include code snippets."},
], agent_name="research")   # blocks on extraction (wait_on_write=True)
print(m.get_memory(agent_name="research"))   # extracted preferences/profile facts
print(m.search("answer style", top_k=3, agent_name="research"))
m.clear_memory(agent_name="research")
```

## Known limitations / follow-ups

- **Extraction cost** — each debounced `add()` (full history) triggers one VLM
  extraction call. The host's debounce bounds the frequency; `add_nowait()` is
  the one blocking flush. Incremental (per-new-message) extraction is a
  follow-up.
- **`abstract()` is directory-level** — OpenViking's `abstract(file_uri)`
  returns the parent directory's L0 abstract, not the file's. The backend
  therefore uses `read()` (the distilled memory body) for `get_memory` /
  `get_context`, and `find()`'s per-memory abstract for `search`.
- **HTTP client-server mode** — not yet wired (a thin alternative subclass or a
  `mode` config switch).
- **Extracted-memory isolation** — the session pipeline always writes extracted
  memories to the root ``memories/`` level (OpenViking's extraction engine does
  not accept a per-agent output path).  These memories are visible to every
  agent.  Manual facts are fully agent-scoped.
- **Re-extraction on re-add** — deleting an extracted memory does not stop a
  future `commit_session` (re-processing the same conversation) from
  re-extracting it. Acceptable for v1.

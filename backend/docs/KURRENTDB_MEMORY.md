# Event-Sourced Memory Storage on KurrentDB (Prototype)

Prototype for [deer-flow discussion #3796](https://github.com/bytedance/deer-flow/discussions/3796):
a `MemoryStorage` backend that appends every memory update as an immutable
event to a [KurrentDB](https://kurrent.io) stream instead of overwriting
`memory.json`. Current state is the newest event; the full update history
comes for free.

## Why

- **Durable, auditable memory writes** — every update is an immutable event.
- **Point-in-time replay** — "what did the agent know at turn N" is a stream
  read at a position (visible in the KurrentDB Admin UI with zero code).
- **Cross-agent handoffs** — any consumer (another agent, a projection, an
  analytics job) reads the same streams; one write, multiple capabilities.

## Design

- `deerflow/community/kurrentdb/memory_storage.py` implements the existing
  `MemoryStorage` ABC and is loaded through the existing
  `memory.storage_class` reflection hook. **No deer-flow core changes.**
- Stream per owner: `deerflow.memory-{user_id}` (global memory) and
  `deerflow.memory-{user_id}.agent.{agent_name}` (per-agent memory). The
  `$by_category` projection groups them all under `deerflow.memory`
  (`$by_category` is a KurrentDB system projection — the dev overlay enables
  it via `KURRENTDB_START_STANDARD_PROJECTIONS=true`).
- Each `save()` appends a `MemoryUpdated` event whose data is the full memory
  snapshot JSON (with `lastUpdated` stamped) and whose metadata carries
  `{user_id, agent_name, source, schema}`. `load()` only folds `MemoryUpdated`
  events — a newest event of any other type is ignored with a warning
  (sole-writer assumption, v0).
- Reads are cache-first per `(user_id, agent_name)` — after the first load no
  gRPC call happens on the hot path. `reload()` (or
  `POST /api/memory/reload`) forces a re-read.
- The sync `KurrentDBClient` is used because the `MemoryStorage` ABC is
  synchronous (memory updater timer threads + Gateway request paths).
- Missing configuration fails safe: if `KURRENTDB_CONNECTION_STRING` is not
  set, `get_memory_storage()` logs an error and falls back to
  `FileMemoryStorage`.

## Try it

1. Start KurrentDB (single-node dev mode, Admin UI on
   [http://localhost:2113](http://localhost:2113)):

   ```bash
   docker compose -f docker/docker-compose.kurrentdb.yaml up -d
   ```

2. Install the optional dependency and set the connection string:

   ```bash
   cd backend && uv sync   # dev group already includes kurrentdbclient
   export KURRENTDB_CONNECTION_STRING="kurrentdb://localhost:2113?tls=false"
   ```

3. Point `config.yaml` at the prototype backend:

   ```yaml
   memory:
     enabled: true
     storage_class: deerflow.community.kurrentdb.memory_storage.KurrentdbMemoryStorage
   ```

4. Run deer-flow (`make dev`), chat until the memory updater fires (default
   debounce 30s), then open the Admin UI → Stream Browser → category
   `deerflow.memory` and watch `MemoryUpdated` events accumulate per user.
   Every historical memory state is one click away — that is the replay demo.

## Known prototype limitations

- **First read per owner may hit gRPC on the event loop** (Gateway memory
  endpoints are `async def`). Follow-up: offload via `asyncio.to_thread` or
  an async storage path. Cache-first reads keep steady-state hot paths clean.
  Writes have the same shape: every `/api/memory` mutation appends via gRPC
  on the event loop (async handlers calling the sync `save()`).
- **Snapshot-per-event (schema v0)** — each event carries the full memory
  JSON. Fact-level deltas (`FactAdded`/`FactRemoved`/`ContextUpdated`) and the
  [`kurrent-agent-schema`](https://github.com/kurrent-io/kurrent-agents)
  canonical vocabulary are the planned v1.
- **`current_version=StreamState.ANY`** — no optimistic-concurrency guard;
  concurrent writers last-write-win, same as the file backend.
- Multi-process deployments share streams but not caches — and unlike the
  file backend's mtime-checked cache, external appends are not observed by
  `load()` until `reload()` is called (or the process restarts).
- **Writes are fail-closed after a failed read.** Read-modify-write callers
  (`create_memory_fact` and friends in `agents/memory/updater.py`) do
  `load()` → mutate → `save()`. If a transport or decode error is silently
  swallowed, the mutated (empty-derived) state would otherwise be appended as
  the new newest event, clobbering the real snapshot. To prevent this, a
  failed `_read_latest()` (transport/decode error, not the legitimate
  "stream does not exist yet" case) marks that `(user_id, agent_name)` key as
  degraded; `save()` refuses to persist and returns `False` while the key is
  degraded, logging why. A subsequent successful `reload()` (or `load()`) for
  that key clears the gate and saves resume normally. Reader-facing behavior
  is unchanged: `load()`/`reload()` still return empty memory on error and
  never raise.

## Tests

`backend/tests/test_kurrentdb_memory_storage.py` — pure unit tests against a
fake client (no KurrentDB required), plus reflection/fallback contract pins.

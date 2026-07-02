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
- **Snapshot-per-event (schema v0)** — each event on the primary
  `deerflow.memory-*` stream still carries the full memory JSON; deer-flow's
  own `load()`/`reload()` only ever fold this snapshot stream. A best-effort,
  write-only side-channel now additionally emits canonical
  [`kurrent-agent-schema`](https://github.com/kurrent-io/kurrent-agents)
  `FactRetained` events for new facts (see "Canonical schema events" below)
  for cross-framework readers — but deer-flow does not yet read them back.
  Full canonical adoption (reading and folding state from canonical events)
  is the planned v1.
- **`current_version=StreamState.ANY`** — no optimistic-concurrency guard;
  concurrent writers last-write-win, same as the file backend.
- Multi-process deployments share streams but not caches — and unlike the
  file backend's mtime-checked cache, external appends are not observed by
  `load()` until `reload()` is called (or the process restarts).
- **Reads raise on failure instead of masquerading as empty.** A transport
  error, an unexpected event type, or a corrupt (non-JSON/non-UTF-8) event on
  the memory stream makes `load()`/`reload()` raise
  `KurrentdbMemoryReadError` (defined in `memory_storage.py`, exported from
  `deerflow.community.kurrentdb`) instead of returning `create_empty_memory()`.
  A missing stream is still a clean, legitimate empty answer and does not
  raise. This intentionally diverges from `FileMemoryStorage`, which returns
  empty memory on read errors: for a network store, "unreadable" must not be
  indistinguishable from "empty" — a stale/failed reader that thinks the
  store is genuinely empty can go on to overwrite real data.
  Read-modify-write flows (`load()` → mutate → `save()`, e.g. the memory
  updater's fact extraction) therefore abort before ever obtaining a basis to
  save: the updater's sync and async update paths both wrap the whole
  operation in `try/except Exception` and log-and-skip on failure (no write
  happens), and `GET /api/memory` / `POST /api/memory/reload` let the
  exception surface as a Gateway 500 rather than silently rendering empty
  memory. The prompt-injection path (`lead_agent/prompt.py`) is unaffected —
  DeerFlow already wraps that memory-context load in a broad
  `except Exception` and degrades gracefully to no injected memory, same as
  any other injection failure. Explicit overwrite flows — import and clear —
  never read before they write, so they remain available as the repair path
  for a stream with a corrupt or unreadable newest event: `save()` appends
  unconditionally (module-level validation and serialization still apply),
  and a subsequent healed read returns the repaired snapshot.
- **All KurrentDB calls use a bounded timeout** (`timeout=` on both
  `get_stream` and `append_to_stream`) so a stalled server cannot pin a
  request path indefinitely. Default is 10 seconds; override with the
  `KURRENTDB_MEMORY_TIMEOUT_SECONDS` environment variable. An unset, invalid,
  non-positive, or non-finite (`inf`/`nan`) value falls back to the default
  with a logged warning.

## Canonical schema events (kurrent-agents)

deer-flow is the first LangGraph-family writer of the
[kurrent-agents](https://github.com/kurrent-io/kurrent-agents) canonical
schema. On every successful `save()`, NEW facts are additionally emitted as
canonical `FactRetained` events, so any other kurrent-agents integration
(Microsoft Agent Framework, Google ADK, Strands, OpenAI Agents, Claude Agent
SDK) can read deer-flow's retained facts without knowing anything about
deer-flow's own `MemoryUpdated` snapshot format.

- **What's emitted**: one canonical `FactRetained` event per fact that is new
  relative to the in-process basis (see "Delta computation" below). Identity
  is the fact's `id` when both the previous and current fact have one, else
  normalized `content`. `retained_at` is the fact's `createdAt` when
  parseable, else the current time. The event type is the
  `kurrent_agent_schema` registry's name for `FactRetained`; the payload is
  the package's own canonical JSON (`to_json`); metadata carries
  `{"schema_version": SCHEMA_VERSION}` since the wire payload itself does not
  embed a version.
- **The stream**: `AgentMemory-deerflow-{user_id}`, built via the package's
  own `agent_memory_stream("deerflow", user_id)` — never a hand-built string.
  It is discoverable in the KurrentDB Admin UI via the `$ce-AgentMemory`
  category projection alongside every other kurrent-agents-compliant writer.
- **Cross-framework readability**: because the stream name, event type, and
  payload shape all follow the published
  [kurrent-agents spec](https://github.com/kurrent-io/kurrent-agents), any
  other integration that reads canonical `AgentMemory-*` streams can consume
  deer-flow's retained facts with zero deer-flow-specific code.

### Delta computation and skip rules

The delta is computed against the **in-process memory cache**, i.e. the value
`self._memory_cache` held for `(user_id, agent_name)` immediately before this
`save()` call updated it — not a read of the canonical stream and not a read
of the snapshot stream. Three cases intentionally skip canonical emission:

- **Cold save** (no previous basis in the cache — e.g. the first save after a
  process restart): skipped entirely. Without this, every restart would
  replay the entire current fact list as "new" the first time `save()` runs,
  since the cache starts empty. The snapshot stream is unaffected — the
  cache-cold case only gates the canonical dual-write.
- **`user_id is None`**: skipped. The canonical v1 schema scopes
  `AgentMemory` streams per-app-per-user only; there is no canonical
  global-memory stream to target.
- **Empty delta** (no facts changed since the basis): skipped — no append
  call is made at all.

### Honest limits

- **Dual-write is not atomic.** The snapshot append (to
  `deerflow.memory-{user_id}[.agent.{agent}]`) is the authoritative write and
  already completed by the time canonical emission runs. Canonical emission
  is a second, independent `append_to_stream` call: it can fail (network,
  serialization, missing `kurrent_agent_schema` package) without affecting
  `save()`'s return value, the snapshot stream, or the cache. A failed
  canonical append is not retried and is not queued — it is simply lost,
  logged as a warning. There is no reconciliation job today; a restart plus a
  fresh cold save will not "catch up" the canonical stream for facts that
  were already present before the failure (see delta computation above).
- **The delta basis is the in-process cache, not a durable cursor.** Two
  processes/instances writing the same `(user_id, agent_name)` do not share a
  canonical-emission basis, so both may (correctly, from their own
  perspective) treat the same fact as "new" the first time they see it after
  a restart — except cold saves are skipped entirely, so in practice a
  restarted instance emits nothing for facts already known before the
  restart, and starts computing deltas only from its next warm save onward.
- **This is schema v0 snapshot storage plus a v1-shaped side-channel, not
  full canonical adoption.** deer-flow's own reads (`load()`/`reload()`)
  never touch the canonical stream — they still fold only `MemoryUpdated`
  snapshot events, completely untouched by this feature. Full canonical
  adoption (reading and folding state from canonical events instead of the
  proprietary snapshot) is the planned v1; today the canonical stream is
  write-only from deer-flow's perspective, intended purely for external
  consumers.

### Try it

Requires the `kurrent-agent-schema` package (declared alongside
`kurrentdbclient` in the `deerflow-harness[kurrentdb]` extra and the backend
dev group — `uv sync` installs both). If it is not importable, the storage
still works normally: canonical emission logs one warning per process and
skips silently on every subsequent `save()`.

After a save with new facts, open the Admin UI → Stream Browser and either
browse `AgentMemory-deerflow-{user_id}` directly or the `$ce-AgentMemory`
category to see every canonical `AgentMemory-*` stream across writers.

## Tests

`backend/tests/test_kurrentdb_memory_storage.py` — pure unit tests against a
fake client (no KurrentDB required), plus reflection/fallback contract pins.
`TestCanonicalFactEvents` covers the canonical dual-write: new-fact emission,
cold-save/`user_id=None`/unchanged-fact skips, best-effort isolation on
canonical-append failure, and that the stream name always comes from the
package's own `agent_memory_stream()` builder.

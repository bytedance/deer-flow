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

## Demo: ask the agent about its own memory (KurrentDB MCP server)

The [KurrentDB MCP server](https://github.com/kurrent-io/mcp-server) is a
separate, stdio-based Python MCP server for exploring KurrentDB streams. It
has no special knowledge of deer-flow — it just reads whatever streams the
connection string can see. Wired in as an MCP tool, it lets the agent read
its own memory event streams back: both the `deerflow.memory-*` snapshot
streams this backend writes on `save()` and the canonical
`AgentMemory-deerflow-{user_id}` `FactRetained` streams described above. This
is an "art of the possible" demo, not a productized integration — see
"Demo scope" below for the caveats.

### Setup

The example entry in `extensions_config.example.json` ships **disabled** (like
every example MCP server there) and with a placeholder path — you must enable
it in your live `extensions_config.json` before the agent gets the tools:

1. Prerequisite: [`uv`](https://docs.astral.sh/uv/) installed on the host —
   the server is launched via `uv run`, which resolves its dependencies on
   first start (see the server's own README).
2. Clone the server: `git clone https://github.com/kurrent-io/mcp-server`.
3. Enable the entry in `extensions_config.json` (created from the example by
   `make config`). Either edit it by hand — copy the `kurrentdb` block from
   `extensions_config.example.json`, set the second `args` element to your
   absolute checkout path, and set `"enabled": true` — or run this from the
   repo root:

   ```bash
   MCP_SERVER_PATH="$HOME/src/mcp-server" jq \
     '.mcpServers.kurrentdb = (input.mcpServers.kurrentdb
        | .enabled = true
        | .args[1] = env.MCP_SERVER_PATH)' \
     extensions_config.json extensions_config.example.json \
     > extensions_config.json.tmp && mv extensions_config.json.tmp extensions_config.json
   ```

4. Make sure `KURRENTDB_CONNECTION_STRING` is set in the Gateway's
   environment (same variable used by `KurrentdbMemoryStorage` — see "Try
   it" above).

**No restart needed**: the Gateway watches the config file's modification
time and reloads MCP servers on the next message after an edit.

**Enforcement nuance**: deer-flow's stdio command allowlist (`npx`, `uvx` by
default) is enforced by the Gateway config API — direct edits to
`extensions_config.json` load without it, but enabling/editing this server
through the web UI or `PUT /api/mcp/config` requires
`DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST=npx,uvx,uv`.

### Demo prompts

- "Using the KurrentDB tools, list the streams in the `deerflow.memory`
  category and summarize how my memory has changed over time."
- "Read the `AgentMemory-deerflow-default` stream — which facts have you
  retained about me, and when was each retained?"

If `tool_search` (deferred tools) is enabled, the agent may first need to
promote the KurrentDB tools by searching for them.

### Demo scope — to be solved if productized

- The MCP server holds the full connection string and can read every
  stream, including other users' memory — acceptable in single-user dev
  mode (`default`), but per-user scoping is a product decision for a real
  integration.
- The server is currently unpublished (clone + absolute path) — publishing
  it to PyPI would make it a `uvx` one-liner needing no allowlist change.
- Stdio sessions are pooled per (user, thread), so each new thread pays
  subprocess startup.

## Pairing with Kurrent's agent skills

[kurrent-io/skills](https://github.com/kurrent-io/skills) is Kurrent's skills
marketplace for AI coding assistants — six `SKILL.md`-format skills covering
everyday KurrentDB work. deer-flow's own skills system consumes the same
`SKILL.md` format (drop into `skills/custom/` or install via
`POST /api/skills/install`), so these can give the deer-flow agent KurrentDB
*knowledge* to pair with the MCP server's *hands* above.

| Skill | Purpose |
|-------|---------|
| `kurrent-docs` | Everyday router for SDK/server/cloud work |
| `kurrentdb-connection` | gRPC client configuration across all six SDKs |
| `kurrentdb-client-detection` | Inventories the client surface in a codebase |
| `kurrentdb-server-detection` | Inventories a deployed server |
| `kurrent-upgrade` | Legacy-client migration and EventStoreDB→KurrentDB rebranding |
| `kurrent-capacitor-cli` | Operating the kcap session-recording CLI |

**Not bundled here, on purpose.** These six skills are currently packaged for
coding assistants (Claude Code, Cursor, Codex), not for deer-flow. **If this
integration is accepted, Kurrent will provide stripped-down versions packaged
for deer-flow** — frontmatter adapted to deer-flow's validated set,
coding-agent-specific tool references removed — pushed and properly
integrated into the skills system. They are deliberately NOT bundled in this
PR to keep its footprint minimal.

## Derived observability (projections over the memory streams)

This is observability the Kurrent way: derived from the event log deer-flow
already writes, not a second telemetry pipeline bolted alongside it. The dev
overlay already runs with projections enabled
(`KURRENTDB_RUN_PROJECTIONS=All`, set in
`docker/docker-compose.kurrentdb.yaml`), so user-defined continuous
projections work out of the box, not just the standard `$by_category`/`$ce-`
projections used elsewhere in this doc.

Because every memory update and every retained fact is already an event,
observability views are just server-side projections over the existing
streams — nothing new is instrumented, and nothing new is shipped.

### Worked example: fact retention over time, across all users

Canonical `FactRetained` events live in category `AgentMemory` (streams
`AgentMemory-deerflow-{user_id}`), with data JSON shaped
`{"fact": "...", "retained_at": "2026-07-02T18:12:27.166131Z"}` (snake_case,
ISO-8601 `Z`) — see "Canonical schema events" above. A continuous projection
folding that category gives total fact-retention counts, a per-day
breakdown, and a rolling window of recent facts, across every user:

```js
fromCategory('AgentMemory')
  .when({
    $init: () => ({ total: 0, byDay: {}, recentFacts: [] }),
    FactRetained: (state, event) => {
      state.total += 1;
      const day = (event.data.retained_at || '').slice(0, 10);
      state.byDay[day] = (state.byDay[day] || 0) + 1;
      state.recentFacts = state.recentFacts.concat(event.data.fact).slice(-10);
      return state;
    }
  })
  .outputState();
```

**Register it, two ways:**

- **Admin UI**: [http://localhost:2113](http://localhost:2113) → Projections
  → New Projection (continuous), paste the JS above, then read the result
  from the projection's State view.
- **Conversationally, via the MCP server demo above**: "Using the KurrentDB
  tools, create a continuous projection named `memory-fact-activity` over the
  `AgentMemory` category that counts FactRetained events per day, then query
  its state and summarize my memory activity." — the same MCP server's
  projection-prototyping capability, no Admin UI required.

**Variants**: swap `fromCategory('AgentMemory')` for
`fromCategory('AgentMemory').foreachStream()` to get independent per-user
state instead of one combined total. The same pattern over category
`deerflow.memory` counting `MemoryUpdated` events gives memory-churn-per-day
for the snapshot streams instead of fact-retention-per-day for the canonical
ones.

**Honest scope**: these are demo projections over the POC's memory streams.
Run-level observability (token usage, tool latency, error rates) belongs to
the run-event streams, not the memory streams — that is the planned next
phase, not something this PR addresses.

## Tests

`backend/tests/test_kurrentdb_memory_storage.py` — pure unit tests against a
fake client (no KurrentDB required), plus reflection/fallback contract pins.
`TestCanonicalFactEvents` covers the canonical dual-write: new-fact emission,
cold-save/`user_id=None`/unchanged-fact skips, best-effort isolation on
canonical-append failure, and that the stream name always comes from the
package's own `agent_memory_stream()` builder.

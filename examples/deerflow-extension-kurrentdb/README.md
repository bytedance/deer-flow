# KurrentDB

Optional extension that keeps DeerFlow memory and run events in
[KurrentDB](https://kurrent.io) streams:

- **Memory**: a DeerMem storage provider. Each user's memory is a stream of
  change events, and the state DeerFlow reads is a fold of that stream
- **Run events**: a run-event store selected as `run_events.backend: kurrent`,
  one stream per thread
- **Canonical events** (off by default): a copy of facts and conversations as
  [kurrent-agents](https://github.com/kurrent-io/kurrent-agents) schema events,
  which other agent frameworks read without DeerFlow-specific code

Memory and run events can be enabled independently.

## Enable

Install from the repository root. This also adds the `plugins:` entry:

```sh
make extension-install SOURCE=/absolute/path/to/examples/deerflow-extension-kurrentdb
```

Then select the backends in `config.yaml` and restart the Gateway:

```yaml
plugins:
  - name: kurrentdb
    package: deerflow-extension-kurrentdb
    use: deerflow_extension_kurrentdb:install
    enabled: true
    required: true          # a startup without KurrentDB support stops instead of falling back

memory:
  backend_config:
    storage_class: deerflow_extension_kurrentdb.memory.KurrentdbMemoryStorage

run_events:
  backend: kurrent

database:
  backend: sqlite           # or postgres; run and thread metadata stay in this database
```

Keep the plugin enabled even when only memory uses KurrentDB: the plugin's
recovery service finishes deletions that a crash interrupted.

Requirements:

- **A persistent `database.backend`** (`sqlite`, the default, or `postgres`)
  with `run_events.backend: kurrent`. Run and thread metadata live in that
  database; with `database.backend: memory` they vanish on restart while the
  events stay in KurrentDB
- **One Gateway process.** The run-event store serializes writes per thread
  inside one process, like the JSONL store. Multi-worker mode and
  `scheduler.multi_instance` still require `run_events.backend: db`, and the
  Gateway refuses to start otherwise
- **The environment variables below in every process that uses DeerMem**,
  including processes that never load the plugin, such as the embedded client

## Settings

All settings come from environment variables (see `.env.example`), because
DeerMem builds the storage from its dotted path without the plugin's config:

| Variable | Default | Meaning |
| --- | --- | --- |
| `KURRENTDB_CONNECTION_STRING` | required | KurrentDB connection string, for example `kurrentdb://localhost:2113?tls=false`. Without it the memory storage fails at construction and the run-event store at Gateway startup |
| `KURRENTDB_TIMEOUT_SECONDS` | `10` | Deadline of every KurrentDB call; finite and greater than zero |
| `KURRENTDB_CANONICAL_EVENTS` | off | `1`, `true`, `yes` or `on` also writes canonical kurrent-agents events |

## Streams

User and thread ids are percent-encoded in DeerFlow's own stream names: every
byte outside `[A-Za-z0-9_]` becomes `%XX`, so a name never gains a dash and
distinct ids never share a stream. KurrentDB derives a stream's category from
the text before its first dash.

| Stream | Category | Holds |
| --- | --- | --- |
| `deerflow.memory-global`, `deerflow.memory-user.{user}` | `deerflow.memory` | Memory per scope: `deerflow.memory.SummariesUpdated`, `FactUpserted`, `MemorySnapshot` (a deletion writes only a snapshot) |
| `deerflow.memory-meta-global`, `deerflow.memory-meta-user.{user}` | `deerflow.memory` | Memory sidecar: fact usage, capacity evictions, extraction watermarks |
| `deerflow.run-events-{thread}` | `deerflow.run` | Run events (`deerflow.run-events.RunEvent`) and deletion boundaries (`RunsCompacted`, `ThreadCleared`) |
| `deerflow.kurrent-deletions` | `deerflow.kurrent` | Deletion intents and their progress |
| `AgentMemory-deerflow-{user}` | `AgentMemory` | Canonical `FactRetained` events |
| `AgentSession-{thread}` | `AgentSession` | Canonical session events |

Memory and sidecar streams share the `deerflow.memory` category, so a category
reader selects the event types it needs. Canonical stream names come from
`kurrent-agent-schema`'s own builders and use raw ids. A stream may also hold
`deerflow.Fence` events, which settle an append whose outcome was unknown;
readers skip them. Run-event `seq` numbers live in the event data and are never
reused, also after a deletion.

## Guarantees

### Deletions

Deleting facts, clearing memory, deleting a run or deleting a thread writes a
**boundary** event that holds the surviving state, then raises the stream's
truncate-before (`$tb`) to that boundary. Every step is recorded in
`deerflow.kurrent-deletions`, so another process or the next Gateway start
finishes a deletion that a crash interrupted.

- **Primary streams: immediate for DeerFlow.** Once the call returns, DeerFlow
  no longer serves the deleted content. Readers of the named streams or their
  categories stop seeing it once `$tb` is raised, which normally happens before
  the call returns. Raw reads keep returning deleted content after the call
  returns when a crash or a failing step (for example a failed `$tb` write)
  interrupts the deletion, or when an earlier deletion of the same stream is
  still unfinished, for example during a sidecar-stream outage, because `$tb`
  is raised in deletion order. Recovery raises it on the next deletion of that
  stream, at Gateway startup, or in the recovery service's next pass
- **Editing a fact keeps its old text in the stream.** Earlier revisions stay
  readable in the memory stream, and in canonical `FactRetained` events, until
  a deletion of that scope truncates them. Use a deletion, not an edit, to
  remove content
- **Canonical streams: eventual.** A cleanup rewrites the canonical stream with
  the surviving events and truncates it, or deletes it when nothing survives.
  A deletion is complete for canonical readers once
  `deerflow.deletions.CanonicalCleanupVerified` is written. Verification waits
  for the canonical writers' 60-second lifetime plus one timeout, so a late
  write cannot bring deleted content back. While KurrentDB is unreachable or
  the cleanup keeps failing, a canonical copy stays readable; the recovery
  service retries every 30 seconds and logs a warning on each failure.
  Cleanup and verification run whether or not `KURRENTDB_CANONICAL_EVENTS` is
  on, so turning it off stops new canonical events but still removes what was
  written while it was on. They read the canonical streams on every deletion
- **`$all` keeps deleted events until a scavenge.** Reads of `$all`, and
  `fromAll()` projections, bypass stream metadata. Run a scavenge to remove
  truncated and deleted events from disk, and in a secured deployment keep
  `$all` readable by `$admins` only, the default ACL for system streams.
  Insecure dev mode has no ACLs
- **Derived state does not forget.** A projection or consumer that already
  processed an event keeps what it derived. Reset or rebuild it after a
  deletion
- **Run-event deletions ignore `user_id`**, like the memory and JSONL stores: a
  thread has one owner

### Concurrency and errors

- **Every append carries an expected version.** An append whose outcome is
  unknown (for example a lost acknowledgement) is settled by appending a fence
  at the same position, never by a read alone. A concurrent memory write
  surfaces as DeerMem's revision conflict, as with the file storage
- **Several processes share memory safely**: every `load()` and `reload()`
  checks the stream head and folds only new events. The recovery service owns
  its own storage instances, so a recovery pass that fences an in-flight
  deletion surfaces in the Gateway as a revision conflict
- **Read failures** (KurrentDB unreachable, a timeout) raise
  `KurrentdbMemoryReadError`, a `MemoryReadError`, and the Gateway answers a
  plain 500, as it does for other remote memory backends. A memory read waits
  at most one timeout for a write to the same scope to finish, then raises the
  same error. Beyond that wait, a read spends only its own call deadlines (the
  head check and the reads; a full read pages with one deadline per page), and
  a sidecar read takes the sidecar stream's lock with the same one-timeout
  wait. A memory write whose outcome stays unknown because the fence also
  failed raises the same error; reload before retrying
- **Undecodable or unexpected stored data is corruption**, not an empty
  answer: memory raises `MemoryStorageCorruption` (the Gateway answers 500,
  `Stored memory data is corrupted.`), run-event reads raise
  `KurrentRunEventStoreCorruption`, and writes to that thread fail as not
  committed. Write to DeerFlow's streams only through DeerFlow
- **Sidecar records are best-effort**: a failed sidecar read or write logs a
  warning and never fails a memory call. Clearing one agent's memory, clearing
  selected facts' sidecar records on their own, or clearing an already-empty
  scope is a deletion of its sidecar records and
  moves the scope's revision once, so a sidecar write that another process
  started before the clear stays hidden after it

### Canonical events

With `KURRENTDB_CANONICAL_EVENTS` on, events are written in the background
after the primary commit; a failure is logged and never fails a turn.

- **Memory**: `FactRetained` for each created fact and each update that changes
  a fact's content. The global memory scope (`user_id` `None`) has no
  canonical stream and emits nothing
- **Sessions**: one canonical session per thread. User messages, assistant
  text, assistant tool calls and tool results map to `UserMessageReceived`,
  `AssistantTextGenerated`, `AssistantToolCallsGenerated` and
  `ToolResultReceived`. `SessionStarted` is written only when the session
  stream is created; runs have no start or end events, and a session that
  restarts after a thread deletion may lack `SessionStarted`
- **Metadata**: payloads are pure schema messages. Event metadata (JSON)
  carries `$schema_version` (the key the schema package documents),
  `schema_version` (the same value), `deerflow.origin`, and
  `deerflow.fact_id`, `deerflow.fact_revision`, `deerflow.agent` on memory
  events or `deerflow.run_id`, `deerflow.seq` on session events. Session
  metadata is redacted with the rules of DeerFlow's run evidence reader
- **At-least-once**: event ids are deterministic, and a cleanup re-appends
  survivors as copies with new ids and `deerflow.intent_id`. Consumers dedupe
  on `deerflow.fact_id` + `deerflow.fact_revision` or `deerflow.run_id` +
  `deerflow.seq`

### Costs and limits

- Each memory `load()` reads the stream head; each write also reads the
  deletions index and the head before appending
- Every memory deletion writes a snapshot of the scope's full resulting state.
  DeerMem deletes facts on most extraction turns once a user reaches
  `max_facts`, so deletions are frequent
- **The deletions index grows without bound.** Every deletion appends an
  intent and its completion, plus `CanonicalCleanupDone` and
  `CanonicalCleanupVerified` even with canonical events off. Nothing compacts
  it: each process reads it from the start on first use and keeps every
  intent in memory
- **Canonical memory cleanup rewrites the user's canonical history** on each
  fact deletion: every surviving `FactRetained`, including earlier revisions,
  is copied in one append. A very large history can exceed `MaxAppendSize`;
  that cleanup then fails on every pass and the deletion never verifies, so
  the deleted fact stays readable in the canonical stream
- `delete_by_run` copies every surviving event of the thread in one append. On
  a very long thread that append can exceed the server's maximum append size
  (`MaxAppendSize`), and the deletion fails
- Recording a run's terminal event reads the thread back to its newest
  deletion boundary
- The memory storage caches each user scope it has seen for the life of the
  process
- Stream names have no deployment prefix: use one KurrentDB per DeerFlow
  deployment
- While KurrentDB is unreachable, Gateway startup waits up to one timeout for
  each of memory and run-event recovery. A `kurrentdb+discover://` connection
  string runs gossip discovery when the client is created, which
  `KURRENTDB_TIMEOUT_SECONDS` does not bound
- Fact search uses DeerMem's substring fallback over `load()`
- Run-event values that are not JSON are stored as their string form

## Local KurrentDB

`docker/docker-compose.kurrentdb.yaml` runs a single insecure node with
projections enabled, published on `127.0.0.1:2113` (Admin UI at
<http://localhost:2113>):

```sh
# With the Docker stack: KURRENTDB_CONNECTION_STRING=kurrentdb://kurrentdb:2113?tls=false
docker compose -f docker/docker-compose.yaml -f docker/docker-compose.kurrentdb.yaml up -d
# Next to `make dev`: KURRENTDB_CONNECTION_STRING=kurrentdb://localhost:2113?tls=false
docker compose -f docker/docker-compose.kurrentdb.yaml up -d
```

## Demo: the agent reads its own streams

Extensions cannot contribute MCP servers, so the
[KurrentDB MCP server](https://github.com/kurrent-io/mcp-server) ships as a
disabled `kurrentdb` entry in `extensions_config.example.json`. It is not on
PyPI yet, so it runs from a checkout:

1. `git clone https://github.com/kurrent-io/mcp-server`, then inside it
   `uv venv && uv pip install -r requirements.txt`
2. In `extensions_config.json`, copy the `kurrentdb` entry, set the
   `--directory` argument to the checkout's absolute path and set
   `"enabled": true`. The Gateway reloads MCP servers when the file changes
3. The entry passes `$KURRENTDB_CONNECTION_STRING` from the Gateway's
   environment. To enable or edit the server through the web UI or
   `PUT /api/mcp/config` instead, start the Gateway with
   `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST=npx,uvx,uv`: the default allowlist
   has no `uv`

Prompts that stay on named streams and categories:

- "Using the KurrentDB tools, read `deerflow.memory-user.default` and explain
  how my memory changed over time."
- "Read the stream `AgentMemory-deerflow-default`: which facts have you
  retained about me, and when?"

Point the tools at named streams and categories, never at `$all`, which still
returns deleted events until a scavenge. The server can read every stream and
can also write events: give it a read-only user in any shared deployment, and
never let it write to `deerflow.*` streams, whose unknown events DeerFlow
treats as corruption.

## Demo: derived observability

User-defined continuous projections turn the streams into live views without
new instrumentation. Register one in the Admin UI (Projections, New
Projection, Continuous) or ask the agent to through the MCP server's
`create_projection` tool. Use `fromCategory` or `fromStreams`, never
`fromAll`.

Facts retained per day, across users, counting each fact version once:

```js
fromCategory('AgentMemory')
  .when({
    $init: () => ({ total: 0, byDay: {}, seen: {} }),
    FactRetained: (state, event) => {
      const key = event.metadata['deerflow.fact_id'] + ':' + event.metadata['deerflow.fact_revision'];
      if (state.seen[key]) return state;
      state.seen[key] = true;
      state.total += 1;
      const day = (event.data.retained_at || '').slice(0, 10);
      state.byDay[day] = (state.byDay[day] || 0) + 1;
      return state;
    }
  })
  .outputState();
```

Tool calls per tool, across conversations:

```js
fromCategory('AgentSession')
  .when({
    $init: () => ({ byTool: {}, seen: {} }),
    ToolResultReceived: (state, event) => {
      const key = event.metadata['deerflow.run_id'] + ':' + event.metadata['deerflow.seq'];
      if (state.seen[key]) return state;
      state.seen[key] = true;
      state.byTool[event.data.tool_name] = (state.byTool[event.data.tool_name] || 0) + 1;
      return state;
    }
  })
  .outputState();
```

`.foreachStream()` after `fromCategory(...)` keeps one state per user or
thread. Without canonical events, the same pattern works over the
`deerflow.memory` category with a `deerflow.memory.FactUpserted` handler; the
handler list is what filters out the sidecar events in that category. These
views keep counting what a later deletion removes; reset the projection to
rebuild it from what is still readable.

## Pairing with Kurrent's skills

[kurrent-io/skills](https://github.com/kurrent-io/skills) holds `SKILL.md`
skills for KurrentDB work (documentation routing, client connection, server
and client detection, upgrades). They give the agent KurrentDB knowledge to
pair with the MCP server. Package a skill directory as a `.skill` archive and
install it with **Install .skill** in the Capability Center or
`POST /api/skills/install/upload` (`POST /api/skills/install` takes an archive
already in a thread's user-data directory). They are written for coding
assistants, so frontmatter DeerFlow does not accept must be adapted first.

## Tests

The behaviour suites live in `backend/tests/test_kurrentdb_*.py` and use an
in-memory fake server (`backend/tests/kurrentdb_fake.py`):

```bash
cd backend && uv run --frozen pytest tests -q -m bundled_extension -k kurrentdb
```

`test_kurrentdb_extension_live.py` runs the same stream semantics and round
trips against a real server when `KURRENTDB_LIVE_CONNECTION_STRING` is set; its
docstring has the command. It passes on the amd64 image
`docker.kurrent.io/kurrent-latest/kurrentdb:latest`, natively or on arm64 hosts
under Docker Desktop's Rosetta emulation (under qemu emulation the server
segfaults), and on the arm64 experimental image
`kurrentplatform/kurrentdb:26.2.0-experimental-arm64-10.0-noble`.

# Memory (`deerflow/agents/memory/`)

Memory capture, storage, retrieval, prompt injection and the model-driven memory
tools. `manager.py` defines the backend-neutral `MemoryManager` contract.
`backends/deermem/` is the default local backend. `backends/mem0/`,
`backends/openviking/` and `backends/honcho/` are optional remote adapters.
Configuration fields are defined in the config models; they are not repeated here.

## Verify

```bash
cd backend
python -m pytest tests -q -k "memory or deermem or mem0 or honcho or openviking"
make test-blocking-io
```

Queue tests use a fake monotonic clock. Backend tests go through the real HTTP
client or the real storage, because the payload shape is the contract.

## Identity

- **Resolve the user with `resolve_runtime_user_id(runtime)`** in middleware and
  tools. Gateway runs and standalone LangGraph runs then land in the same user
  scope. The server-owned auth identity wins over anything a client sends.
- **Capture the identity when work is queued.** Extraction runs later on a timer,
  where no request context exists.
- **Agent-scoped management is opt-in per backend.** A backend that does not set
  `supports_agent_scoped_management` answers a scoped request with 501. Silently
  operating on user-wide data would clear or export the wrong facts.
- **A scoped import replaces one agent's facts only.** The user's shared summaries
  stay, even when the payload carries empty summary defaults.

## What may be written

- **Tool-call intent is not memory.** Every backend excludes assistant tool-call
  content in all of its representations. A message with an attempted call is not a
  final response, even when the parsed call list is empty.
- **Checkpoint messages are never changed.** Locale and other capture metadata are
  stamped on the queued copies, after PII redaction.
- **Invalid extraction output is dropped per item.** Filter a bad fact before the
  storage validation can abort the whole batch. A removal that is paired with a
  replacement applies only when the replacement passes every write gate.
- **Keep project extraction scoped to the captured membership.** User edits
  fence queued writes, and project injection follows memory opt-outs. After
  the user pool commits, a project write failure consumes the batch. See
  [project memory](../../../../../../docs/guide/projects.md#project-memory).
- **Confirmation needs human evidence.** Extraction must not raise confirmation
  counters from lexical or model hints. Search raises access heat only for the
  facts it returns.
- **One eviction path.** Automatic, manual, tool and import writes all use
  `deermem/core/eviction.py`.
- **Emergency snapshots and normal updates stay separate.** Normal updates for one
  conversation coalesce. Snapshots taken before compaction do not, because
  successive compactions remove different messages.

## DeerMem storage

- **Facts are one Markdown file each.** `memory.json` holds shared summaries and
  revision data only. It never holds facts or a fact index.
- **Writes take the user lock and check revisions.** A snapshot operation reloads
  and recomputes after a manifest conflict. The Gateway maps the conflict to
  HTTP 409.
- **An unreadable file is corruption, not absence.** Skip an entry that was deleted
  after listing; raise for one that exists and cannot be read. A partial cache is
  never presented as the complete memory document.
- **The v1-to-v2 migration is one-way and backs up first.** Delete legacy agent
  JSON only after the summaries were adopted or shown equal.
- **The retrieval index is derived data.** It can be rebuilt from the Markdown
  files at any time. Storage updates it after the durable locks are released, and
  search falls back to substring matching until a rebuild succeeds. Recreate index
  files only for SQLite corruption codes; an operational error is not corruption.
- **Sidecars do not touch canonical files.** Usage, audit and watermark data must
  not change a fact's timestamps or revisions. User delete and clear remove them.

## Remote backends

- **The read policy covers every read path.** Search, injection, management and
  export convert provider records inside the same policy boundary. An unknown
  policy fails closed.
- **Diagnostics carry no memory content.** Provider payload errors are re-raised
  with values redacted. Programming errors still propagate.
- **Do not deduplicate by text.** Honcho capture is incremental by stable source
  ID. Two messages with the same text and different IDs are both stored.
- **Reject another owner before any remote call.**
- **Shutdown drains active work** before it closes a client.

## Injection

- Gateway input handling removes forged dynamic-context markers. Only output of
  the current `DynamicContextMiddleware` establishes what memory a run saw.
- `memory.injection_enabled: false` and the per-agent opt-out remove the injected
  block completely. Date reminders and real user messages stay.
- Gateway startup schedules retrieval warm-up without delaying readiness.

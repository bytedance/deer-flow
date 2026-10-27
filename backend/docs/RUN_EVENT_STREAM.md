# Run Event Stream

The run event stream is DeerFlow's append-only record of what happened during
an agent run. Producers write through `RunEventStore`; history, debug, subtask,
memory-audit, and workspace-review consumers read projections of the same rows.

The machine-readable contract is
`contracts/run_event_stream_contract.json`. Canonical event names and
categories live in `deerflow.runtime.events.catalog`; conformance tests require
the runtime catalog and JSON contract to match exactly.

## Record Envelope

Every persisted event has these required fields:

| Field | Meaning |
| --- | --- |
| `thread_id` | Thread that owns the event. |
| `run_id` | Run that produced the event. |
| `seq` | Store-assigned sequence, strictly increasing within a thread. |
| `event_type` | Fixed event name or documented dynamic pattern. |
| `category` | Consumer-routing bucket. |
| `content` | Event payload, normally a string or JSON object. |
| `metadata` | Filterable or audit metadata. |
| `created_at` | Timezone-aware ISO-8601 timestamp. |

Backends may return additional fields. `DbRunEventStore`, for example, returns
`user_id` and may add serialization markers such as `content_is_json` to
metadata. Consumers must ignore unknown envelope and metadata fields.

`event_type` is limited to 32 characters and `category` to 16 characters by the
database schema. Catalog-backed definitions enforce the same limits before
writing so they cannot emit values that only the memory or JSONL store accepts.

`seq` is thread-global, not run-local. Memory and database stores assign it
monotonically for their supported deployment modes. JSONL only provides this
guarantee within one process; shared multi-process deployments must use the
database store.

The database store additionally keeps a per-thread high-water mark
(`run_event_thread_seq`) that is independent of the event rows. Deleting a run
therefore never lowers the next allocated `seq`: values are not reused within a
thread, and a consumer whose `after_seq` cursor already advanced past a deleted
run does not miss later events. Thread deletion drops the mark only when no
events remain for the thread across every owner and category; surviving rows
retain the allocation floor.

## Categories

`category="message"` means an event is eligible for a message projection; it
does not guarantee that the row is visible in the UI. Thread-history APIs also
filter middleware model calls, subagent AI responses, and superseded regenerate
runs, and the frontend honors message-level visibility markers such as
`hide_from_ui`. Subagent events remain available through the run-events
endpoint; parent `task` ToolMessages remain in thread history so subtask cards
can restore their terminal status after reload.

All other categories are excluded from message projections and are available
through run-event or specialized APIs:

| Category | Purpose |
| --- | --- |
| `trace` | Execution evidence. |
| `outputs` | Root graph completion output. |
| `error` | Callback-observed failure evidence. |
| `middleware` | Middleware state-change audit evidence. |
| `context` | Effective hidden-context identity. |
| `subagent` | Subagent lifecycle and step history. |
| `workspace` | Workspace/output file-change evidence. |

## Authoritative Run Outcome

`run.terminal` (`trace`) records the owning Worker's confirmed final business
outcome. It is a singleton identified by `(thread_id, run_id, event_type)` and
confirmed through `put_if_absent()`. Content contains only `status`:
`success`, `error`, `interrupted`, or `timeout`; graph outputs and error details
are excluded. Metadata requires `protocol_version: 1` and a boolean `recovered`.
Owner Workers emit `recovered: false`; a confirmed recovery takeover emits
`recovered: true` only when it creates a missing terminal. An existing matching
event retains its original marker. The marker describes evidence origin and
grants no publication authority. Field definitions remain in the
[JSON contract](../../contracts/run_event_stream_contract.json).

`run.start` and `run.end` retain their root-invocation producers, counts,
categories, callback timing, and opaque output contract. A Run may produce
several `run.end` events with success metadata before its business outcome
becomes error. Use `run.terminal` for the confirmed Run outcome.

### Publication Authority

Only the current local Run owner's attributable final Terminal Commit ACK may
authorize normal publication, with the acknowledged outcome still matching.
Graph completion, a same-status RunRow read, a store-only hydrated record,
a legacy `None` write result, or a truthy store response cannot replace that
proof. Without a backing RunStore, a confirmed local Manager transition is
authoritative only within that process lifetime.

Rollback's `interrupted` ACK is intermediate while restoration remains pending;
publication waits for restoration and the final `error` ACK. Ownership loss,
rejected or unconfirmed commits, and unknown predecessor writes fail closed.
Reading a historical terminal row does not create local publication authority.
Recovery publication requires the boolean result of a successful atomic takeover
claim, with the target bound to the claimed Run identity and its committed
`error` outcome. The target is one-shot and cannot be reconstructed with another
Run identity. A later same-status RunRow read cannot create that authority.
Recovery receipts and terminal confirmation re-check the Run lifecycle inside
the Event Store's mutation fence; a completed thread deletion wins,
so a stale target cannot recreate an orphan event.
When SQL Run and Event stores share an engine, the built-in guard reads the Run
through the active event transaction, so recovery needs only one available pooled
connection. It retains the mutation fence through the check and event commit.
Different engines and custom Run lookups keep their normal read path. Memory
guard/deletion fences are per-thread; a slow guard does not block unrelated threads.

### Evidence Ordering

The Worker holds its finalizing barrier through this sequence:

1. Finish callback-producing completion hooks and lifecycle observers.
2. Freeze Journal producers and drain accepted writes through the existing
   `_stop_evidence_producers()` / `_drain_evidence()` machinery.
3. Validate final commit authority and confirm the terminal singleton.
4. Capture the Evidence Receipt's sequence boundary and event count.
5. Persist the Evidence Seal.
6. Release the finalizing barrier, then publish SSE END.

`finish_evidence(before_receipt=...)` holds the Journal operation lock through
freeze/drain, terminal confirmation, and Receipt capture, serializing normal
flush/close. All accepted, confirmed Journal evidence precedes a new terminal
event. Unfinished or UNKNOWN writes prohibit publication and complete sealing;
only proven-not-committed Journal batches may be retried. Force close invalidates
bounds even during Receipt capture. Preserve the existing cancellation and
quarantine behavior rather than replaying an unsettled batch.

The confirmed event must lie inside the Seal's captured boundary. An event
appended later cannot be claimed as covered by an earlier Seal; an event alone
does not prove complete evidence. Barrier release before END preserves immediate
next-message admission, including when later cleanup is slow.

Recovery publishes its zero-delivery receipt before `run.terminal`, matching the
normal delivery-before-terminal order. Receipt failure remains non-fatal and does
not prevent the terminal confirmation attempt. Both recovery writes are fenced
by the current Run lifecycle.

### Idempotence and Failure Semantics

Confirmation validates the returned event's identity, category, status, version,
required field types, positive sequence, and database user ownership:

| Outcome | Observation and behavior |
| --- | --- |
| `CONFIRMED_NEW` | Insertion is confirmed and the returned event matches; Receipt capture may proceed. |
| `CONFIRMED_EXISTING` | The existing event itself matches; accept idempotently and preserve its sequence and original source marker. |
| `CONFLICT` | Identity or protocol fields contradict expectations or are malformed, or the guarded Run lifecycle no longer admits publication; record the conflict, do not overwrite, and do not seal as complete. |
| `UNKNOWN` | The operation outcome cannot be established; preserve uncertainty and do not seal as complete. |

`created=False` alone proves neither success nor conflict. Additional optional
metadata may differ without conflicting. At most two atomic singleton attempts
resolve a lost ACK while final authority remains valid; this bounded confirmation
never replays a quarantined Journal batch. Cancellation cannot authorize a Receipt.

Publication or Seal failure cannot rewrite the acknowledged Run business status.
A confirmed event may remain stored with partial evidence if sealing fails.
Event-write failure must preserve normal SSE completion and existing `/stream`
and `/wait` missing-stream fallbacks, including Memory Event Store loss after
restart. Terminal singleton confirmation does not deduplicate Redis END.

### Compatibility and Storage Guarantees

Historical sealed evidence without `run.terminal` remains valid under its original
coverage contract. Consumers claiming this protocol must validate the event
inside the captured boundary; a code upgrade or Seal state alone is insufficient.
Later recovery appends do not silently upgrade that historical coverage.

Confirmation is limited to the Store's declared failure and concurrency model:

| Backend | Guarantee boundary |
| --- | --- |
| Memory | One event loop/process lifetime; no persistence across restart. |
| JSONL | File-backed within the declared single-process mutation boundary; no multi-process guarantee. |
| SQLite | Database-backed confirmation with per-thread in-process serialization; this does not establish PostgreSQL or multi-Gateway concurrency semantics. |
| PostgreSQL | Database-backed confirmation with per-thread transaction advisory locking across independent connections/processes; concurrency validation requires real sessions. |

Singleton insertion and RunRow terminal commit are separate transactions.
`RecoveryTerminalPublisher` backfills an error terminal only after a successful
takeover claim. A crash between a normal terminal commit and event confirmation
can still leave a terminal Run without an event when no later takeover claim
exists; closing that remaining gap requires durable outbox/reconciliation and
is outside this implementation. Historical migration is also out of scope.
Later recovery appends do not upgrade an earlier Evidence Seal's coverage, and
terminal singleton confirmation does not deduplicate Redis END. Eventual
evidence after every terminal commit is not yet guaranteed. Missing events must
not gate SSE recovery.

## Producers

`RunJournal` emits callback-derived events:

| Event type | Category | Producer |
| --- | --- | --- |
| `run.start` | `trace` | Root `on_chain_start()` |
| `run.end` | `outputs` | Root `on_chain_end()` |
| `run.error` | `error` | `on_chain_error()` |
| `llm.human.input` | `message` | First persisted lead-agent human input |
| `llm.ai.response` | `message` | `on_llm_end()` |
| `llm.tool.result` | `message` | `on_tool_end()` |
| `llm.error` | `trace` | `on_llm_error()` |
| `context:memory` | `context` | `record_memory_context()` |
| `middleware:{tag}` | `middleware` | `record_middleware()` |

Current middleware tags are `guardrail`, `loop_detection`,
`safety_termination`, `skill_activation`, `skill_secrets`, `tool_promotion`,
`tool_progress`, and `summarize`. The pattern is intentionally open so new middleware tags
are additive. Because the full event type is limited to 32 characters and
`middleware:` uses 11, a tag must contain 1-21 characters.

`middleware:loop_detection` records transitions into the warned state (first
per call hash or per tool-frequency burst) and each hard stop produced by
`LoopDetectionMiddleware` in lead-agent and ordinary task-tool subagent runs.
Task-tool subagents forward the append to the parent loop because `RunJournal`
and its event store must not cross the isolated-loop boundary. Durable batch
subagents have no parent run journal and do not emit these events. The event's
`action` is `warn` or
`hard_stop`. The `changes` object identifies the detection layer, affected tool
names, observed count, effective threshold, whether the producer was a
subagent, and its agent id when applicable. Tool arguments, prompts, message
content, tool results, and argument-derived hashes are not persisted in this
event.

`middleware:tool_progress` records effective result-quality state transitions
from `ToolProgressMiddleware`: `warn` for ACTIVE → WARNED, `block` for a
transition to BLOCKED, `recover` for WARNED → ACTIVE after a useful result,
and `reset` when a later agent invocation (for example, goal continuation)
deliberately clears a prior WARNED/BLOCKED phase.
The bounded `changes` object contains the tool name, source and destination
phases, consecutive-problem count, normalized result status, error
classification and recovery advice, effective count threshold (null when no
count threshold fired), and
subagent attribution. Tool
arguments, prompts, message content, tool results, and content-derived hashes
are never copied into this event. Producer-supplied metadata is projected onto
fixed error/action vocabularies and a strict boolean-or-null before persistence,
so a custom tool cannot smuggle arbitrary values through its result stamp.
Recorder calls happen after the state lock is released, so a slow custom
recorder cannot stall unrelated tool-state updates. Recorder failures are
fail-open and do not change guard behavior. These events are emitted only when
`tool_progress.enabled` is true (the default is false).

`middleware:tool_promotion` records deferred MCP schemas newly promoted for
the active catalog. `changes.source` distinguishes automatic `routing_hint`
promotion from an explicit `tool_search`; the remaining fields contain sorted
new tool names, their count, `is_subagent`, and the optional subagent
`agent_id`. Explicit-search events observe the final `Command` returned by the tool middleware chain.
Automatic promotion records the graph state transition; promotion is scoped to
the agent's admitted deferred catalog and never bypasses the independent
assembly or execution authorization. Repeated model passes or searches that add
no names emit no event. Queries, routing keywords, catalog hashes, tool schemas
and descriptions, arguments, and results are not copied into this middleware
event. Other event types retain their existing payload contracts.

`middleware:summarize` records each successful summary result from
`SummarizationMiddleware` with `action` `summary_result`, including results
reused from the no-op cache. The `changes` object carries the no-op and
cache-skip flags, summary and previous-summary lengths, the number of
summarized messages, and the middleware's cumulative counters; see
[summarization.md](summarization.md). Summary text and message content are
never copied into this event.

Ordinary task-tool subagents forward loop-detection, tool-promotion, and
tool-progress appends to the parent run loop through dedicated recorder context
keys. The loop-bound `RunJournal` itself never enters the isolated subagent
loop.

### Opaque Run Outputs

`run.end.content` is the root graph output and is intentionally opaque. Its
nested representation is not currently identical across storage backends:

- `MemoryRunEventStore` retains the original Python container and nested
  values.
- `JsonlRunEventStore` and `DbRunEventStore` serialize through
  `json.dumps(default=str)`, so nested values that are not directly JSON
  serializable are read back as strings.

Consumers may use `run.end` as root-invocation completion evidence, but must
not infer the final Run outcome or depend on backend-identical nested output
values. Normalizing those values would be a separate runtime compatibility
change rather than part of this current-state contract.

`subagents/step_events.py::subagent_run_event()` maps streamed `task_*` chunks
to persisted events. The worker batches them through `put_batch()`:

| Event type | Source chunk | Required content |
| --- | --- | --- |
| `subagent.start` | `task_started` | `task_id`, `description` |
| `subagent.step` | `task_running` | `task_id`, `message_index`, `kind`, `text`, `truncated`; AI steps add `tool_calls`, tool steps add `tool_name` |
| `subagent.end` | terminal `task_*` | `task_id`, `status`; optional model, usage, result/error, and truncation fields |

Terminal subagent status is one of `completed`, `failed`, `cancelled`, or
`timed_out`.

Malformed lifecycle chunks are not persisted. Every chunk requires a non-empty
string `task_id`; `task_running` additionally requires a non-negative integer
`message_index` and a message object.

`workspace_changes.record_workspace_changes()` writes `workspace_changes` in
category `workspace` when a run changed files. Its string content is a summary;
the structured versioned summary, file list, and limits live in
`metadata.workspace_changes`.

The JSON contract defines required and optional payload fields using JSON
Schema. It is the authoritative field-level reference.

## Consumers

| Consumer | Read path and behavior |
| --- | --- |
| Frontend thread history | `GET /api/threads/{thread_id}/messages/page` scans `list_messages()`, removes middleware rows, subagent AI responses, and superseded regenerate runs, then applies frontend message visibility rules. |
| Per-run message clients | Thread-scoped and stateless run message endpoints call `list_messages_by_run()`. |
| Run debug/audit | `GET /api/threads/{thread_id}/runs/{run_id}/events` calls `list_events()` and supports `event_types`, `task_id`, `limit`, and `after_seq`. |
| Historical subtask cards | Fetch `subagent.step` through the run-events endpoint, filtered and paginated by `task_id`. |
| Memory audit | Filters run events to `context:memory` and compares `content_sha256`; full memory text is not duplicated into the event store. |
| Workspace review | `GET /api/threads/{thread_id}/runs/{run_id}/workspace-changes` projects the latest `workspace_changes` payload. |

Token and cost summaries are not reconstructed by reading event rows.
`RunJournal` accumulates usage while callbacks fire, and the worker writes the
aggregates to `RunRow`.

External Langfuse/LangSmith tracing is a parallel callback pipeline, not a
`RunEventStore` consumer. It is correlated through trace metadata rather than
being derived from these rows.

Evaluation consumers discussed in #4243 are planned rather than present in
this tree. They should read evidence through `list_events()` and treat the
compatibility and terminal-state limits below as part of that integration.

## Compatibility

The existing mixture of dot-separated, colon-separated, and bare-word names is
frozen. This contract documents current behavior; it does not normalize names.
A rename, removal, category change, required-field removal, or required-field
type change is breaking and needs an explicit versioned migration or dual-write
period.

Adding a new event type or optional field is additive. Consumers must ignore
unknown event types and unknown optional fields. Producers must add a catalog
entry, update the JSON contract and this document, and extend the conformance
tests in the same change.

`ai_message` is a read-only legacy alias for `llm.ai.response`. Current
producers never emit it. Category-based message projections and store queries
for the last visible AI message recognize previously persisted alias rows, so
the `/messages/page` endpoint also attaches feedback correctly. The legacy
`/messages` endpoint still returns those rows but only enriches feedback for the
canonical name. Legacy aliases live outside the canonical catalog and must not
be used by new producers.

## Known Gaps

- Tool-call intent is embedded in `llm.ai.response.content.tool_calls`; it is
  not a first-class event. A missing or timed-out result may have no dedicated
  outcome event.
- `run.end.metadata.status` is only a root graph completion marker and is
  always `success`. `RunRow.status` remains authoritative for lifecycle state,
  and worker loss may leave no terminal event.
- Nested non-JSON values in `run.end.content` have backend-dependent
  representations: memory retains Python values, while JSONL and database
  stores read them back as strings.
- Durable batch subagent loop detection, deferred-tool promotion, and
  tool-progress transitions do not emit middleware events because those runs
  have no parent run journal.
- Journal attribution, token accounting, and external tracing metadata still
  depend on manual instrumentation at several LLM call sites.

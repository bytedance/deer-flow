### Checkpoint Cache Concurrency

The memory history cache is shared by sync saver wrappers. Its threading lock
serializes lookup/LRU promotion, population/eviction, thread purge, close, and
statistics snapshots. Keep cache critical sections free of awaits and saver I/O;
immutable histories do not make the mutable LRU registry thread-safe.
Memory entries own deep copies of write payloads and snapshot seeds on ingest
and read. Clone payloads outside the registry lock: user-defined copy callbacks
can re-enter the cache. Preserve sync/async state isolation through
`CheckpointStateAccessor`; tests live in `tests/test_checkpoint_cache_payload_isolation.py`.

Copies run synchronously on the caller's thread, including `aget_many` and
`aset_many` on the event loop. Each ingest or cache hit copies the whole
entry, so CPU and allocation costs grow with payload size. A warm scan of
N checkpoints can repeatedly copy growing snapshot seeds, reaching O(N²)
total copied data. The LRU entry cap bounds entry count, not payload bytes
or scan cost. Profile long-thread history reads before offloading copies
to worker threads; preserve payload isolation and copy callbacks outside
the registry lock.

### Redis Checkpoint Cache Purge

Thread purge escapes Redis glob metacharacters in the complete literal key stem
before SCAN, and checks returned byte/string keys against that stem before UNLINK.
Do not interpret operator `key_prefix` text as a pattern or widen thread deletion
to sibling namespaces. Keep the cursor loop and outage/TTL fallback unchanged.

### Stream Bridge Heartbeats

Observed Redis streams removed during replay yield `StreamGap` with empty bounds; initially empty streams still wait. After this gap, `/wait` refreshes store-only status and completes only for a terminal run with no retained stream.

Memory stream cleanup retires the captured stream generation, clears its retained
payloads and wakes its Condition. Established readers emit one empty-bound
`StreamGap` and stop if replay is unfinished, including on bridge close. Fully
consumed terminal streams keep END, using the retired generation's tail offset;
readers never attach to a recreated stream. An unpublished stream without explicit
cleanup still heartbeats.
New readers that capture a generation but acquire its Condition only after
retirement always receive a gap, including cursor-less terminal reattachments.

Memory/Redis bridges keep startup-only `stream_bridge.heartbeat_interval_seconds`; explicit `subscribe(..., heartbeat_interval=...)` overrides it. Provider contexts drain owned cache/bridge/checkpointer/Store teardown across cancellation. `close_agent_stream()` shields close to completion: preserve counts, defer host cancellation, balance repeats, keep active errors, log attached close failures at callers, map close cancellation to failure, never time out.

Reconnect cursor parsing requires ASCII digits and must treat integer-conversion failures as malformed input. Redis cursors additionally require unsigned 64-bit components; use the same parser before sending a cursor to `XREAD` and when detecting replay gaps. Preserve malformed-cursor policy: memory replays retained events, Redis tails active streams and replays ended streams through `end`. `tests/test_stream_bridge.py` directly tests both parsers offline, including oversized sequences, Redis component overflow, non-ASCII digits, and valid uint64 boundaries; integration tests also exercise malformed cursors against real Redis.

### Memory Stream Replay

Memory keeps the exact last evicted event ID as bounded per-run metadata. A
reconnect from that known predecessor replays all retained successors and END,
matching a live subscriber at the same position. Older or unverifiable evicted
cursors still emit `StreamGap`; Redis replay policy is unchanged. Coverage in
`tests/test_memory_stream_reconnect_boundary.py` includes the Gateway SSE consumer
with real ASGI requests and LangGraph SDK decoding.

### Checkpoint Channel Modes (`full` / `delta`)

Keep mode and delta snapshot cadence process-frozen; only the accessor graph
cache cap is hot-reloadable. Full-mode readers reject delta checkpoints.
Use `CheckpointStateAccessor` with the thread's effective schema for state reads
and mutations; preserve mode gates, parentage and pending writes. State replacement
uses `Overwrite`. Delta resume/rollback rewrites the current head rather than
forking; reject missing selected/head tuples and pending Sends before writing.
`Command(resume=...)` also rejects pending nodes except `__start__` on both;
`CheckpointResumeRejected` skips pre-write rollback. Resume at head.

Before changing checkpoint modes, caches, replay lookup, state replacement or
rollback, read the [checkpoint contracts](../../../../docs/runtime-guidance-details.md#checkpoint-channel-modes-and-replay).

**Message sequence placement:** Keep backend and frontend message identity rules aligned. Details: `backend/docs/runtime-guidance-details.md`.

**Thread message cursors:** `list_messages` applies both exclusive bounds before `limit`, paging forward whenever `after_seq` is supplied.

**Journal capture**: Image-only input stops batch scans and later human-event
capture despite an empty summary. AI summaries strip leading think sections
before the 2000-character cap, preserving events, literal answer tags, and
prior useful summaries. When an admitted run is interrupted after root assistant
text was published but before `on_llm_end`, the worker records the accumulated
visible text as an interrupted partial `llm.ai.response` feed event after the
agent stream closes. Completed responses win cancellation races by message ID;
hidden, subgraph, unpublished, and ID-less chunks are not recovered. Partial
events never enter authoritative checkpoint state. Tests: `test_run_journal*.py`
(callbacks, full/delta) and `test_run_worker_rollback.py` (interruption recovery).

**Per-call LLM telemetry** (`runtime/journal.py`): `RunJournal` adds observation-only keys
to `llm.ai.response` metadata and to `llm.error` metadata (previously empty): `langchain_run_id`,
`langchain_parent_run_id`, `caller_category` (`lead_agent` / `middleware` / `subagent` /
`fallback` / `other`), `provider`, `model`, `stop_reason`, `status`, provider-reported token counts,
and the rendered request size measured at `on_chat_model_start` (`request_chars`,
`request_message_chars`, `request_tools_chars`, `request_message_count`, `request_started_at`).
Sizes count string-leaf characters without serializing the request (the callback runs inline on
the event loop); there is no pre-call token count, so `input_tokens` is the provider's figure.
Unavailable values are `None` or absent, never estimated. Every helper fails soft: a telemetry
error is logged and must not change the call, the staged events' existing fields, or token
accounting. The contract lists the optional keys in `contracts/run_event_stream_contract.json`.
Retries are not distinguishable from first attempts.

**LLM response callback coalescing** (`runtime/journal.py`): a provider may fire
`on_llm_end` twice for one LangChain run id, first without usage (or with all token
counts zero) and immediately again with usage populated. The first callback's generation
set is always canonical: `RunJournal` stages only its response events and immutable
message-summary fields while retaining the first caller, and applies that callback's
fallback state and tool-call bookkeeping immediately; those effects remain canonical.
It must not retain provider-owned message objects because a provider may mutate and
reuse the same response for the usage replay. Usage metadata is deep-snapshotted,
including nested token-detail mappings, before it enters a staged or buffered event.
An adjacent same-id positive-usage replay may enrich only each corresponding staged
event's metadata/content usage fields, including the `input_tokens`, `output_tokens`,
and `total_tokens` aliases derived from the accepted usage snapshot. Request size,
identity, caller, stop reason, and status retain their canonical values. Replay
generation-count differences never add, remove, or replace canonical messages. The next
unrelated event, an effective buffer size (committed plus pending events) reaching the
flush threshold, or an explicit flush commits the staged unit and updates the message
summary. Once that ordering boundary is crossed, a late usage replay can still update the
authoritative run token summary, but it cannot mutate the append-only message event,
caller attribution, fallback state, or tool-call bookkeeping. Closed journals return
from `on_llm_end` before inspecting the response or touching any run state.

**Skill history:** `record_skill_usage` saves lead-run snapshots on terminal
answers for paginated history. See `docs/skill-usage-ui.md`.

**Run delivery receipts:** Finalize artifact evidence and terminal status before clearing an ordinary satisfied goal, under a checkpoint-write reservation. Delivery failure retains the goal without continuing. Only that clear writes `goal_outcome`; other goal writes remove it. Historical replay keeps the current goal and budget, and drops the old outcome. Scheduled exception below; details: `backend/docs/runtime-guidance-details.md`.

**Workspace change detection:** Truncated snapshots cannot prove absence. Mark skipped delivery verification in the receipt. Details: `backend/docs/runtime-guidance-details.md`.

Unmet goals stand down on run-level token/loop hard stops and retain the original stop reason; hidden continuations must not re-enter that run's shared safety state. Operation-based no-progress counting: `backend/docs/runtime-guidance-details.md`.

**Deferred terminal commit:** Keep terminal commit authority on the owning
Worker's confirmed ACK; row reads never grant it. Renew leases through receipt,
rollback and finalization barriers; lost or expired authority fences writes.
Drain owned finalizers across cancellation. Read the [terminal ownership contract](../../../../docs/runtime-guidance-details.md#deferred-terminal-commits-and-lease-ownership)
before changing terminal commits, renewal, rollback or shutdown.

**Deferred-tool promotion event deduplication** (`runtime/journal.py`): one
`RunJournal` owns the lead graph's run-scoped atomic promotion claim. Parallel
`tool_search` Sends read the same pre-step state, so state diffing alone can
label the same schema as new more than once even though the `promoted` reducer
unions it once. Producers claim sorted candidate names before appending
`middleware:tool_promotion`; later overlapping decisions emit only their
unclaimed remainder. Ordinary task-tool subagents use an equivalent claim on
their per-execution parent-loop proxy, preserving separate events when two
different delegated agents promote the same tool. The active catalog is fixed
for one graph execution, so the claim needs no persisted catalog hash.

**Tool-progress phase events** (`agents/middlewares/tool_progress_middleware.py`):
effective ACTIVE → WARNED, WARNED/ACTIVE → BLOCKED, WARNED → ACTIVE recovery,
and later-invocation WARNED/BLOCKED → ACTIVE resets append
`middleware:tool_progress` through `RunJournal`. Recorder calls happen after
the middleware releases its state lock, matching LoopDetectionMiddleware, so a
slow recorder cannot stall tool-state updates. Cross-thread middleware
producers (currently slash-skill activation via `asyncio.to_thread`) schedule
journal mutation directly onto its owning event loop; they never mutate or
flush `RunJournal._buffer` from the worker thread. The task-tool subagent proxy
rejects a loop that differs from the journal owner, so its close fence always
drains the only scheduling hop. `flush()` yields to the loop once before
draining: since Python 3.13 an awaited executor future can complete without a
loop iteration, so a hop queued by a worker that already returned may still be
pending when flush starts.
The persisted projection accepts
only framework-defined error/action values and strict booleans (using null for
invalid values) from the producer-supplied tool stamp; tool content, args,
prompts, and derived hashes do not enter the event. Ordinary task-tool subagents use the narrow parent-loop
recorder proxy, never the journal itself; durable batch runs have no parent
journal and emit no such event. Recorder failures are fail-open.

**RunJournal write ownership** (`runtime/journal.py`): a batch handed to `store.put_batch()` is owned by a journal task until its outcome settles, so a cancelled `flush()`/`close()` caller detaches the waiter and re-raises `CancelledError` only after the owned write is drained — never abandon or replay the in-flight batch. A generic `put_batch` exception is an ambiguous outcome: it is quarantined, blocks every successor write, and makes `flush()`/`close()` report non-success instead of replaying the batch. Only `RunEventStoreNotCommittedError` means the store proved none of the batch committed and may be deliberately retried; stores must raise it instead of a bare exception for that case. Explicit `flush()` and `close(flush=True)` share one per-journal operation lock, so a successor batch can never overtake an unsettled predecessor, every waiter observes the same settlement, and a normal close detaches only after the whole buffer has settled. `close(flush=False)` is a separate abort path that never queues on that lock: it revokes write ownership before its first await and makes any in-flight flush report non-success rather than a late success. A cancelled event write or pending progress snapshot waits a bounded time to settle; `Task.cancelled()`/a clean return does not prove an uncooperative backend's I/O actually stopped, so this is a bound on waiting, not a termination guarantee. A task that outlives that bound stays supervised until it settles, so its late result is retrieved and logged rather than dropped while lease-loss finalization continues. Background-write and progress-reporter warnings log the exception type and message, whose text is backend-controlled and may echo driver-level parameters, so log consumers must not treat it as payload-free.

**JSONL record boundaries** (`runtime/events/store/jsonl.py`): thread reads,
run reads, and sequence recovery split on physical newlines. Do not use
`str.splitlines()`: U+0085/U+2028/U+2029 inside valid JSON strings must remain
part of the record. Preserve existing UTF-8 files and the writer format.
`tests/test_jsonl_event_store_unicode.py` covers Unicode values, reopening,
idempotent writes, LF/CRLF, blank lines, and malformed records.
Reads and deletes treat a run ID writes reject as an unknown run (routes pass
URL IDs through); writes still raise.

**JSONL sequence watermark:** before deleting a non-empty run, save the thread's
allocation floor with atomic replacement of `runs/.seq-watermark`, off-loop under
the existing mutation fence. Recovery takes the maximum of that floor and surviving
run files, including legacy directories without a watermark. Copy the deleted run's
permission bits onto the temporary watermark before publication, preserving both
shared-read and restrictive modes. Failed permission setup or publication must leave
the run intact; unreadable/corrupt watermarks fail closed. Complete
thread deletion removes the watermark only after deleting all run files, including
when no events remain. This does not add multi-process JSONL support. Coverage:
`tests/test_jsonl_event_store_seq_watermark.py` and the mutation cancellation suite.

**Targeted run-event attribution** (`runtime/events/store/`):
`RunEventStore.find_latest_ai_message_run_ids()` has a complete-or-error
contract. Its default implementation walks `list_messages()` backward in
1000-row pages, preserves the first page's high-watermark through the exclusive
`before_seq` cursor, and raises when a full page has no safe progressing `seq`.
Memory and database stores use that bounded path; the JSONL store overrides it
with one complete thread-log read because each JSONL page would otherwise
rescan every run file. That JSONL snapshot task is named `jsonl-snapshot:{thread_id}` for
asyncio task dumps and retains the per-thread lock until its off-thread full-log
read settles even through caller cancellation. It deliberately has no drain
timeout: releasing ownership while the worker can still read files would let a
writer enter the supposedly stable snapshot. The default and JSONL paths share the public
`normalize_message_ids()` and `match_ai_message_run_id()` helpers from
`events/store/base.py`. Database owner filtering is inherited on every page.

**Run-event read identity**: `list_messages`, `list_events` and
`list_messages_by_run` accept `user_id` on every backend (DB filters;
memory/JSONL accept it for parity). `start_run` stamps rows with the raw trusted
owner, but `AUTO` resolves to the internal user's `make_safe_user_id` form, so
Gateway thread/run reads (including run-row lookups) must pass
`_run_scope_user_id()` explicitly.

**Event-store mutation fence** (`runtime/events/store/`): every thread mutation —
`put`, `put_batch`, `put_if_absent`, `delete_by_thread`, `delete_by_run` — shares
one serialization domain: the per-thread `asyncio` lock, plus (on PostgreSQL) the
transaction-scoped advisory lock keyed by `thread_id` that
`DbRunEventStore._acquire_thread_mutation_fence()` takes before any read or write.
Deletion therefore cannot interleave with an admitted writer and re-create rows for
a deleted thread, and all backends accept the same owner-scoped delete signature
(`user_id` filters on the DB store; memory/JSONL accept it for parity). This is
serialization, not an incarnation fence: a mutation already admitted before a
deletion may still run afterwards, and preventing old-incarnation resurrection
needs a separate durable generation contract. `JsonlRunEventStore` keeps its own
equivalent guarantee through `_run_mutation`.
Callers may use a missing key as proof that no valid AI event exists only after
an ordinary return, never after an exception. A caller that crosses a run or
checkpoint-write admission boundary must repeat the complete audit after
admission; a pre-admission exact hit can be superseded by a later event just as
a pre-admission miss can become an exact hit.

**DB run-event sequence watermark:** Run deletion retains `run_event_thread_seq`.
Thread deletion removes it in the same mutation-fenced transaction only when no
events remain for the thread, including owner-scoped and zero-row deletions.
Check all owners and categories; surviving rows retain the allocation floor.
`tests/test_run_event_store.py` pins cleanup, recreation and cursor visibility.

**Changed-run discovery:** Use the durable `(change_seq, run_id)` cursor and repeat history audits after admission. Details: `backend/docs/runtime-guidance-details.md`.

**Terminal run cleanup:** Close streams, journals, and graph references even on cancellation. Details: `backend/docs/runtime-guidance-details.md`.

Clear both the terminal worker's journal and message-sequence stamper references;
the stamper's generation callback captures the journal. Diagnostic tracebacks may
retain finalizer frames, so config/callback removal alone is insufficient. Keep
the DEBUG checkpoint-inspection failure regression in `test_run_worker_rollback.py`.

**`RunManager._runs` holds only records this worker admitted.** A cross-worker idempotent reuse returns the `store_only` row from `_record_from_store()` unregistered: the peer never finalizes or `cleanup()`s it, so a registered copy stays `pending`/`running`, 409s later same-thread admissions, hides the owner's orphan from reconciliation, and sends a peer `cancel()` down the local-owner path. Pinned by `test_peer_idempotent_reuse_*` and `test_peer_cancel_of_reused_run_*` (`tests/test_multi_worker_run_ownership.py`) plus `tests/test_gateway_services.py::test_start_run_peer_idempotent_reuse_*`.

**A `RunRecord` owner matches its durable row.** HTTP admissions omit `user_id` and the SQL store stamps the ambient user, so `create()` and `_admit_thread_operation()` resolve an omitted owner from the contextvar, keeping `None` without one — never `get_effective_user_id()`'s `default` bucket. A `None` record made SQL keyed retries on a peer or after `cleanup()` return 500, hid HTTP runs from owner-scoped history, and skipped their MCP `background_tasks` projection. Pinned by `test_run_record_owner_matches_row_stamped_from_context`, `test_keyed_retry_without_explicit_user_*`, the `sql` case of `test_start_run_peer_idempotent_reuse_*`, `test_run_manager_*_admitted_without_explicit_user`, and `test_run_manager_keeps_omitted_owner_unset_without_user_context`.

**Checkpoint implementation map:** Module ownership and regression suites are in the [checkpoint reference](../../../../docs/runtime-guidance-details.md#checkpoint-implementation-map).

**Checkpoint benchmarks:** Paired full/delta cases and production-shaped runs are documented in `backend/docs/runtime-guidance-details.md`.

# Client capability context

Client capability hints are request-only. `redact_config_secrets` excludes
`client` from both `context` and `configurable` in saved configs and historical
run API responses, without mutating the input. The live run keeps its sanitized
client; later or server-started runs do not inherit it from thread history.

# Referenced conversation capability

`RunContext.conversation_reader` is a host-provided per-run callback. The worker
rejects caller-supplied `__conversation_reader` values in both context carriers,
installs only the host value, and releases it during terminal cleanup. The
callback is not checkpoint state and must never be recovered from an earlier
run or serialized into run kwargs.

## Scheduled run capabilities and goal outcomes

`RunContext.scheduler_capability` is another per-run host capability. The worker
installs it under `__scheduler_capability`, rejects caller copies in both context
carriers, and releases it during terminal cleanup. `scheduled_task_runtime` is a
separate private occurrence snapshot: its owner, task ID, occurrence ID, and goal
objective must match the admitted record before the worker may install a goal.
Run metadata and hidden conversation-reference messages are display data and
never confer either capability. An interactive grant manages the owner's tasks
created in its thread plus tasks that ran an occurrence there (re-checked per
call); a scheduled grant only stops its own occurrence's task. The Gateway
grants neither while its scheduler poller is stopped. The scheduled prompt's
`deerflow_scheduled_origin` message metadata is server-owned display data.

A scheduled goal is installed before the first turn, only in a fresh thread,
using the existing goal writer and default continuation budgets. Terminal
cleanup clears only that occurrence's goal instance, through the ordinary
goal lock and expected-checkpoint guard while its own durable run slot is still
active, before terminal status commits. A process-local scheduled cleanup barrier
defers local cancel persistence and refuses premature replacement admissions;
lease renewal continues through this barrier. This scheduled-only exception closes
the handoff race where a peer could inherit the occurrence's goal. No ORM writer
transaction spans a checkpointer write. Ordinary user goals retain terminal-first
completion and delivery cleanup.
Accepted cancellation during cleanup is applied again after the saver returns,
including rollback, before terminal persistence; later requests arbitrate through
the existing durable `cancel_action` compare-and-set.

Scheduled goal `created_at` is the admitted run's timestamp, canonicalized to UTC
with six microsecond digits. Recovery and ordinary-worker preflight match only an
exact owner/thread/timestamp/normalized-objective terminal scheduled run, using
`RunStore.list_by_thread_created_at` without bounded history pagination. Ambiguous
or unavailable identity fails closed; source metadata must remain server-stamped
at Gateway admission. `clear_recovered_scheduled_goal` uses the existing idle-thread
checkpoint-write reservation; a busy thread defers to the next worker's preflight.
Preflight source-resolution errors stop before graph execution with an explicit
recovery error and preserve the goal; do not copy idle recovery's catch-and-defer
behavior into an executing run. Cancellation continues to propagate unchanged.
Newer user goals and ownership/lease loss always win. Failed cleanup remains
recoverable through this durable instance tuple without new GoalState fields.

`RunRecord.goal_verdict` / nullable `runs.goal_verdict` preserve the final
evaluator outcome, including strict boolean `relied_on_assumption`. Persist it
in the same terminal-status update, including durable cancellation arbitration,
so recovery need not inspect mutable thread state. All non-interactive policies
allow disclosed, low-risk reversible assumptions only with achievement evidence;
their evaluator responses must explicitly provide the assumption boolean.

Goal evidence stays within 12,000 characters. Keep the selected recent work and
omission labels intact; use remaining space to restore shortened user input
rather than treating the 2,000-character request reservation as a hard cap.

Only a malformed verdict from an explicitly normal model completion may retry,
once, with the original evidence. Recheck cancellation, Goal identity and
checkpoint/messages first. Each complete evaluator invocation keeps its own usage
ID and observer call; one final decision updates Goal counters. Valid verdicts,
length/safety stops, and transport/configuration errors are not format retries.

Goal evaluator usage crosses a JSON-safe sink into
`RunJournal.record_external_llm_usage_records` before response parsing or observer
notification can fail. Critic tokens/cache reads and distinct calls belong to
`middleware:goal_evaluator`; critic responses never enter visible history and
graph journal callbacks are withheld to prevent double counting. External
`count_call`/`usage_missing` flags default off for existing subagent consumers;
missing critic usage adds `missing_usage_calls` to the model bucket, making the
run's full cost unpriced instead of reporting a partial total as complete.
Accounting includes critic usage, while the graph token-budget middleware does
not gate standalone critic calls. A graph token limit is not a strict billing cap.

## JSONL mutation cancellation

`JsonlRunEventStore._run_mutation` acquires the per-thread lock before admitting
an operation, then drains the shielded operation through filesystem I/O, rollback,
and sequence/lock bookkeeping before releasing the lock or re-raising caller
cancellation. Repeated cancellation must not detach an active disk worker; a failed
mutation remains the cause of the propagated cancellation. There is deliberately
no drain timeout that would release ownership while a worker can still modify files.
A queued caller can cancel before admission, and unrelated threads remain independent.
Drain tasks are named `jsonl-mutation:{thread_id}` for asyncio task dumps. Multi-thread
`put_batch` drains its current group on cancellation and never starts later groups;
the admitted group keeps its records on success or completes rollback on failure.
This is a store-local guarantee, not a change to RunJournal cancellation policy or
JSONL's single-process deployment constraint. Regression coverage is in
`tests/test_jsonl_event_store_cancellation.py`.

## Completed-evidence provenance

Gateway admission and RunManager validate host-owned evidence origin against the shared `EVIDENCE_ORIGINS` in `runtime/runs/schemas.py`. Preserve the string values and reject client metadata as provenance; only trusted Python entry points set the admission argument.

Idempotent resume reuse preserves both the private request identity and the original evidence origin/agent across worker and store boundaries. A retry must not relabel existing evidence. Memory/SQLite parity is covered in `tests/test_completed_evidence_admission.py`.

Completed-evidence finalization obeys the journal write-ownership contract:
unknown or cancelled write outcomes cannot yield a receipt or be replayed. Only
proven-not-committed batches may be retried. Normal close stops new evidence
producers and drains already admitted cross-thread callbacks inside its operation
lock before flushing and detaching; do not reacquire that lock through `flush()`.

The Worker requires its own final terminal ACK for `run.terminal`; rollback's
intermediate ACK and matching row reads grant no authority. Keep hooks → Journal
freeze/drain → singleton confirmation → Receipt → Seal → barrier release → END.
Force close invalidates Receipt bounds. Preserve ownership checks, four-state
confirmation, and partial evidence on failure without changing business status
or SSE liveness. See [Run outcome protocol](../../../../docs/RUN_EVENT_STREAM.md#authoritative-run-outcome).
Recovery uses a non-replaceable one-shot target, writes the zero-delivery receipt
before `run.terminal`, and passes a Run-lifecycle guard into both singleton
writes. Stores evaluate that guard under the same store mutation fence as
event deletion; completed thread deletion wins over a stale recovery target.
DB recovery guards use `RunRepository.get_in_session` when both stores share
an engine, retaining that fence without a second pool checkout. Different engines
and overridden Run lookups retain their ordinary read path. Plain callable guards
remain supported; they must not acquire another connection from the writer's pool.
Memory guard/deletion locks are per-thread, so a slow guard cannot block another
thread. Coverage: `tests/test_recovery_terminal_pool.py` (PostgreSQL via
`TEST_POSTGRES_URI`).

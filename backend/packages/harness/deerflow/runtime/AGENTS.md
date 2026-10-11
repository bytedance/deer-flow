### Stream Bridge Heartbeats

Memory/Redis bridges keep startup-only `stream_bridge.heartbeat_interval_seconds`; explicit `subscribe(..., heartbeat_interval=...)` overrides it. Provider contexts drain owned cache/bridge/checkpointer/Store teardown across cancellation. `close_agent_stream()` shields close to completion: preserve counts, defer host cancellation, balance repeats, keep active errors, log attached close failures at callers, map close cancellation to failure, never time out.

### Checkpoint Channel Modes (`full` / `delta`)

Checkpointer storage runs in one of two channel modes, selected by `checkpoint_channel_mode` in `config.yaml` (default `full`). `delta` mode adopts LangGraph 1.2's `DeltaChannel` for `messages`: checkpoints store a sentinel + per-step writes instead of the full message list, so storage/serde grows O(N) instead of O(N²) in turns. All checkpointer backends (memory/sqlite/postgres) serve both modes unchanged — the semantics live in the compiled graph's channel table, not in the saver.

**Mode is process-frozen and restart-required.** `make_lead_agent` and the embedded `DeerFlowClient` freeze the resolved mode (`runtime/checkpoint_mode.py::freeze_checkpoint_channel_mode`) before compiling the graph with the mode-matched schema (`agents/thread_state.py::get_thread_state_schema`, plus `adapt_state_schema_for_mode` / `normalize_middleware_state_schemas` for middleware state). Adapted middleware schemas are cached by schema, mode, and resolved snapshot frequency so a pre-freeze ephemeral graph cannot leave a stale default-frequency schema behind. A second, different mode or frequency in the same process raises `CheckpointModeReconfigurationError`. To switch: edit config, restart.

**Delta snapshot cadence is configurable but frozen with the mode.** `database.checkpoint_delta.snapshot_frequency` (default `10`) sets the `DeltaChannel` snapshot cadence. It is frozen alongside the mode (`freeze_checkpoint_snapshot_frequency`; non-positive direct inputs raise `ValueError`, while a frozen-value mismatch raises `CheckpointModeReconfigurationError`), restart-required, and must match across every process sharing one checkpoint database — the cadence lives in each compiled graph's channel table and is deliberately NOT stamped into checkpoint metadata, so the mode-compatibility marker and full -> delta migration semantics are unchanged. Schema helpers resolve it explicit-arg -> frozen -> default, and every schema/graph cache (`_delta_thread_state_schema`, `_adapt_state_schema_for_delta`, the client agent-config key, the gateway accessor-graph cache) keys on the resolved value.

**Compiled-graph cache cap is configurable and hot-reloadable.** `database.checkpoint_graph_cache.accessor_graph_max` (default `64`) bounds the gateway accessor-graph cache, which clears wholesale at the cap. The cap is re-read on every eviction check (`resolve_checkpoint_graph_cache_max`), so a config.yaml reload takes effect without a restart — a size change never affects graph semantics, only eviction timing.

**Compatibility is asymmetric and fail-closed.** Every checkpoint written in delta mode carries metadata marker `deerflow_checkpoint_channel_mode: "delta"` (injected via `inject_checkpoint_mode`; absence of marker = full, so pre-feature checkpoints need no migration). Before any state read/write, `ensure_checkpoint_mode_compatible` rejects a full-mode process opening a delta thread with `CheckpointModeMismatchError` (surfaced as HTTP 409 with the cause and thread id by the threads router; `CheckpointModeReconfigurationError` maps to 503) — a full-mode raw read of a delta blob would silently return empty/partial `messages`. The reverse direction is allowed: delta-mode processes read full checkpoints transparently (old full checkpoints seed the delta channel), so full → delta is the smooth migration path; delta → full requires materializing/converting the data first. Detection also honors upstream's `counters_since_delta_snapshot.messages` metadata, and an explicit config marker takes precedence over any ambient context value.

**Never bypass `CheckpointStateAccessor` (`runtime/checkpoint_state.py`) for thread-state access.** It is the single choke point binding graph + checkpointer + mode: it injects the mode marker into configs, runs the compatibility check before every `get`/`update`/`history`, and returns materialized state (delta checkpoints lack `channel_values.messages` — raw `get_tuple` reads see a sentinel). For metadata-only reads, use `get_metadata` / `aget_metadata` to retain the mode gate without materialization. Thread-owned reads must use `build_thread_checkpoint_state_accessor` so the recorded assistant schema materializes every channel. Sync checkpoint mutations must drain off-thread commits before cancellation propagates; sync `get_tuple` reads remain cancellable. `history(limit)` semantics: `0` means zero items (explicit empty), `None` means unlimited — do not pass `limit=0` through to `graph.get_state_history`. Assistant metadata lookup is fail-closed for mutation accessors so a store outage cannot silently select the default schema and discard extension channels. In `full` mode the read path degrades to a raw checkpointer read (`_RawCheckpointReadAccessor`) when the agent factory cannot build the graph (bad model config, MCP outage) — full checkpoints carry complete `channel_values`, so reads don't need the graph; degraded snapshots take `created_at` from the standard checkpoint `ts` field, falling back to metadata only for compatibility. The delta gate still applies on the degraded path; `next`/`tasks` degrade to empty and thread status falls back to the stored status because task presence is not derivable, while delta mode has no fallback (materialization needs the channel table).

**Replay checkpoint lookup prefers lineage and degrades only for an explicitly missing legacy parent link.** Branch and regenerate paths first walk `parent_config`, which prevents a global chronological scan from selecting a sibling created by regeneration. `CheckpointParentMissingError` alone enables the bounded newest-first history fallback in `app/gateway/checkpoint_lineage.py`; cycles, dangling/non-addressable parents, target mismatches, and depth exhaustion raise `CheckpointLineageIntegrityError` and fail closed instead of selecting a sibling. The compatibility scans request 400 raw checkpoints so up to 200 duration-only entries do not consume the effective branch-history budget; the fallback scans oldest-to-newest internally, skips duration-only checkpoints, and accepts only checkpoints with an addressable id as the replay base. A source history with no discoverable pre-user checkpoint preserves the historical single-checkpoint branch behavior instead of rejecting the branch; regeneration remains unavailable for that inherited response. Existing single-checkpoint branches are not mutated by regenerate preparation, and no raw checkpoint tuple is copied across threads because delta state depends on ancestry and pending writes. Regenerate source-run lookup uses the current thread's exact event, then the server-stamped `run_id` on the copied human message, then verified RunManager content matching; it does not read parent-thread events. When an interrupted response was streamed but never checkpointed, regeneration accepts only the latest visible human message's server-stamped `run_id` after verifying that it belongs to the same thread and still has `interrupted` status. Storage or checkpoint-mode failures are not treated as a missing base and still fail closed.

**A delta-mode run cannot fork; `runtime/runs/worker.py` linearizes the resume instead.** Resuming from an older checkpoint (regenerate, or any client-supplied `checkpoint`) forks the lineage, and delta state for a fork is not materializable: `BaseCheckpointSaver.get_delta_channel_history` — and the bespoke overrides in `InMemorySaver`/`PostgresSaver` — collect **every** `pending_writes` entry stored on each on-path ancestor, but a shared parent also carries the writes of the sibling child that was abandoned. Those writes replay into the fork, so the run starts from a message list still containing the answer it was supposed to replace (#4458: regenerating in a branched thread showed the superseded assistant message beside the new one after a reload; reproduced on postgres, sqlite, and the in-memory saver). Write-to-child ownership belongs to the upstream delta contract, so DeerFlow does not reimplement the walk: `_linearize_delta_checkpoint_resume` materializes the requested checkpoint's complete state and writes every channel onto the **current head** (which has no siblings) through the state mutation graph, using `Overwrite` for reducer channels and resetting newer head-only channels to their schema default (or `None` when no constructible default exists); it then drops the `checkpoint_id` selector and lets the run proceed linearly, while the abandoned turn stays in history as the rewritten head's ancestry. The worker holds `_checkpoint_thread_lock` across `_capture_rollback_point` and the optional linear rewrite, making the rollback snapshot and rewrite atomic with graph streaming and the preceding run's duration-metadata checkpoint write. Capture preserves the complete real pre-run state; cancel-with-rollback then linearly replaces the current delta head with that captured state rather than forking the now-shared pre-run checkpoint, so the abandoned turn is restored without replaying the resume sibling's writes. The worker also recomputes the current-run message boundary from the rewritten state and fails closed (an unreadable resume checkpoint raises rather than falling back to the corrupt fork). `full` mode keeps forking — its checkpoints carry complete `channel_values` and need no replay — so LangGraph branching semantics are unchanged there. Root namespace only; subgraph namespaces are left alone.

**Wholesale state replacement uses a state-only mutation graph + `Overwrite`.** `update_state` values pass through channel reducers (`add_messages` merge in full, append in delta), so replacing reducer values requires `Overwrite` rather than an ordinary update. Full-mode rollback and context compaction replace `messages`; delta resume and delta rollback replace every materialized channel and reset current-head-only channels to their schema default (or `None`). These writes go through `build_state_mutation_graph(as_node, mode, state_schema)`, and `state_schema` MUST be the thread's effective schema (`graph_state_schema(assistant_graph)`), because the base-ThreadState fallback silently discards written channels contributed by custom `AgentMiddleware.state_schema`. Channels absent from a full-mode fork write inherit the parent's channel blobs, so middleware channels survive rollback/compaction (locked by `test_rollback_preserves_middleware_contributed_channels` and `test_compact_thread_context_preserves_middleware_contributed_channels`). The compiled mutation graph has one no-op node (entry = finish) whose checkpoint machinery (channels/versions/metadata) is identical to the agent graph's but schedules no pending tasks, so the restored/compacted head stays idle instead of re-triggering the agent. Never hand-write checkpoints via `checkpointer.aput` for this; raw writers elsewhere must preserve checkpoint parentage — severed ancestry breaks delta replay (see `runtime/runs/worker.py` writer parenting and `checkpoint_patches.py`).

**Run rollback flow** (`runtime/runs/worker.py`): `_capture_rollback_point` materializes the complete pre-run state via the accessor and captures raw `pending_writes` via `aget_tuple` into an immutable `RollbackPoint` before the run starts — capture failure, including cancellation delivered before or during the capture await, disables rollback (fail-closed), never restores partial state, and never deletes the thread; only a capture that completes and finds no checkpoint may reset the thread to empty. In `full` mode, cancel-with-rollback forks from the pre-run checkpoint via the mutation graph and inherits non-message channels from that parent. In `delta` mode, forking is unsafe once the cancelled path has attached sibling writes to the pre-run checkpoint, so rollback replaces every captured channel on the current head, using `Overwrite` for reducers and schema defaults for current-head-only channels. Resume and rollback state rewrites copy only the selected/captured checkpoint's server-authored agent binding; missing or malformed bindings remain unbound. Both modes reattach only the captured pre-run pending writes to the restored checkpoint. Edit replay runs (`metadata.replay_kind="edit"`) also restore the pre-run checkpoint on failed, timed-out, or interrupted completion and publish the restored `values` snapshot to the stream before `end`, so clients do not remain on a transient edited branch when the replay did not produce a successful replacement.

**Message sequence placement:** Keep backend and frontend message identity rules aligned. Details: `backend/docs/runtime-guidance-details.md`.

**Thread message cursors:** `list_messages` applies both exclusive bounds before `limit`, paging forward whenever `after_seq` is supplied.

**Journal capture**: Image-only input stops batch scans and later human-event
capture despite an empty summary. AI summaries strip leading think sections
before the 2000-character cap, preserving events, literal answer tags, and
prior useful summaries. Tests: `test_run_journal*.py` (callbacks, full/delta).

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

**Run delivery receipts:** Journal artifact evidence and terminal status must finalize before an ordinary satisfied goal is cleared. That cleanup uses a durable checkpoint-write reservation; delivery failure retains the ordinary goal without another continuation. Only that clear passes `outcome` to `write_thread_goal`, which removes `goal_outcome` on every other goal write. The scheduled-only exception is described below. Details: `backend/docs/runtime-guidance-details.md`.

**Deferred terminal commit:** With an event store, the worker stages its terminal
status locally and commits it only after finalization's receipt and duration
writes. `RunRecord.terminal_commit_pending` keeps `_renew_leases()` renewing that
still-active row until the commit is attempted; a renewal rejected by the worker's
own commit is confirmed by re-reading the row, while a peer claim fences the run.
Never select runs for renewal by local status alone. Shutdown's drain treats the
same state as active: such runs are awaited (never cancelled — cancellation would
skip their terminal tail) so the duration checkpoint and terminal commit land
before checkpointer teardown. A drain timeout leaves staged statuses and commit
barriers intact without persisting `interrupted`. A finalizer that raises is
logged with its run ID, staged status and exception while the other runs continue
draining. Coverage: `tests/test_gateway_run_drain_shutdown.py`.

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

**`RunManager._runs` holds only records this worker admitted.** A cross-worker idempotent reuse returns the `store_only` row from `_record_from_store()` unregistered: the peer never finalizes or `cleanup()`s it, so a registered copy stays `pending`/`running`, 409s later same-thread admissions, hides the owner's orphan from reconciliation, and sends a peer `cancel()` down the local-owner path. Pinned by `test_peer_idempotent_reuse_*` and `test_peer_cancel_of_reused_run_*` (`tests/test_multi_worker_run_ownership.py`) plus `tests/test_gateway_services.py::test_start_run_peer_idempotent_reuse_*`.

**A `RunRecord` owner matches its durable row.** HTTP admissions omit `user_id` and the SQL store stamps the ambient user, so `create()` and `_admit_thread_operation()` resolve an omitted owner from the contextvar, keeping `None` without one — never `get_effective_user_id()`'s `default` bucket. A `None` record made SQL keyed retries on a peer or after `cleanup()` return 500, hid HTTP runs from owner-scoped history, and skipped their MCP `background_tasks` projection. Pinned by `test_run_record_owner_matches_row_stamped_from_context`, `test_keyed_retry_without_explicit_user_*`, the `sql` case of `test_start_run_peer_idempotent_reuse_*`, `test_run_manager_*_admitted_without_explicit_user`, and `test_run_manager_keeps_omitted_owner_unset_without_user_context`.

**Where things live**:
- `runtime/checkpoint_mode.py` — mode + snapshot-frequency freeze, marker injection, delta detection, compatibility gate, both error types
- `runtime/checkpoint_state.py` — `CheckpointStateAccessor`, `build_state_mutation_graph`, `RollbackPoint`
- `checkpoint_patches.py` (package root) — the one remaining patch: `BinaryOperatorAggregate` unwrapping an `Overwrite` first write into an empty channel (#4380; probe-guarded). The `InMemorySaver` delta-history patch is gone: `langgraph-checkpoint` 4.2.0 fixed that write loss upstream (#8526) while keeping its override, so the dependency floor plus the full → delta migration contract test are the gate — never re-add a version-guarded saver patch.
- `agents/thread_state.py` — `ThreadState`/`DeltaThreadState`, `delta_messages_field` / `DELTA_MESSAGES_FIELD` (`DeltaChannel` at the configured `snapshot_frequency`, default 10), schema adaptation helpers
- `runtime/context_compaction.py` — compaction via accessor + mutation graph (reference consumer). Runs stamp their effective agent into server-owned checkpoint metadata; manual compaction uses that binding—not request `agent_name`—for memory policy and bucket. Missing/invalid legacy bindings and unreadable agent configs fail closed by skipping the optional flush while compaction may continue with the default model; a missing pre-binding checkpoint emits a warning so the skipped write is observable.
- `runtime/checkpoint_cache/` + `runtime/checkpointer/cached_saver.py` — delta-mode checkpoint history cache; checkpoint state reads MUST go through `CheckpointStateAccessor`, and the checkpointer may be a `CachedHistorySaver` wrapper — never rely on concrete saver types
- `runtime/checkpointer/thread_spans.py` — thread enumeration for `DeerFlowClient.list_threads`, ordered by `checkpoint_id` (goal writes keep the old `ts`). SQLite/Postgres savers (unwrapped from `CachedHistorySaver`) use the primary-key index; any other saver walks `list(None)`. Saver type selects speed, never correctness
- `runtime/goal.py` `_call_checkpointer_method` — tries the async saver method and falls back to the sync one only on `NotImplementedError`: every saver defines the async methods, but the sync TUI/embedded `SqliteSaver`/`PostgresSaver` (also behind `CachedHistorySaver`) raise from them. Sync writes stay in `await_drained`
- Tests: `tests/test_checkpoint_mode.py` (freeze/detect/gate), `tests/test_checkpoint_state.py` (accessor/mutation graph), `tests/test_delta_channel_checkpointers.py` (saver parity), `tests/test_threads_checkpoint_mode.py`, `tests/test_gateway_checkpoint_mode.py` (dual-mode e2e parity), `tests/test_context_compaction.py` (mutation-graph write, no scheduling), `tests/test_run_worker_rollback.py`, `tests/test_cached_history_saver.py` + `tests/test_cached_history_saver_integration.py` (history cache)

**Checkpoint benchmarks:** Paired full/delta cases and production-shaped runs are documented in `backend/docs/runtime-guidance-details.md`.

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

# Runtime implementation details

The runtime AGENTS.md indexes these detailed contracts. Preserve their behavior when changing the corresponding code.

**Goal no-progress counting** (`runtime/goal_progress.py`): pair actual tool calls
with their results in the current human/hidden-continuation interval. Normalize
success/error metadata without mutating checkpoint messages. Retain only exact
successful-operation hashes in the active Goal's `last_evaluation`; no global
cache, arbitrary operation-count cutoff, file inspection or extra model call.
Repeated results, UI-only sandbox descriptions, failed commands, receipt IDs and
timestamps alone do not reset the counter. Validate receipts against the original
arguments before excluding narration from operation identity. Shared shell-result
classification recognizes nonzero exit markers, correcting older generic success
metadata while preserving explicit producer stamps. A successful new operation is
activity, not proof of usefulness or completion. Pure-text turns retain the
existing reply comparison.

Already evaluated hashes survive checkpoint restart and compaction. Results
removed before observation cannot be reconstructed; do not claim complete tool
history capture. Goal replacement/clearing drops the active set, while historical
checkpoints retain their existing lifecycle. Storage grows with observed work;
measure it rather than reintroducing a silent fallback to text after a fixed
number of operations. Preserve old counters on first migration, merge against
freshly read Goal state when persisting, and leave all existing stop, durability,
cancellation and racing-user checks unchanged.

**JSONL tail recovery** (`runtime/events/store/jsonl.py`, #6520): every append
path goes through `_append_records`. A nonempty file whose last byte is not LF
gets a separator written first, so a crash that left either valid JSON without
its newline or a partial record cannot glue the next event onto that tail.
`_iter_records` reads physical byte lines and decodes each one on its own;
`JSONDecodeError` and `UnicodeDecodeError` skip only that line, so an
incomplete UTF-8/JSON tail cannot hide intact records or block sequence
recovery. Existing bytes, Unicode separators inside JSON strings, and
per-thread mutation ownership stay as they are. Batch rollback restores the
pre-append byte size, including removal of a newly inserted separator. Tests
live in `tests/test_jsonl_event_store_tail_recovery.py`. This does not add
multi-process support or crash-atomic batches.

**Message feed seq stamping** (#4666): a checkpoint carries no position of its
own and loses messages to summarization, so a client merging a `values` frame
with the seq-ordered `run_events` feed cannot place a checkpoint-kept message
once the feed's loaded page window no longer reaches back to it.
`RunEventStore.get_message_seqs(thread_id, identities)` resolves the seq the
store already assigned, keyed by
`runtime/events/message_identity.py::message_identity` — the backend half of
the identity rule `frontend/src/core/threads/hooks.ts::messageIdentity` applies
(tool messages by `tool_call_id`; `X` / `X__user` human copies collapse to
one). The two halves must stay in sync: a mismatch is silent, degrading
placement rather than raising. `runs/worker.py::_MessageSeqStamper` attaches
the result as `additional_kwargs.deerflow_seq` on root `values` frames only —
subgraph frames are not part of the thread feed's ordering, and nothing is
written back to the checkpoint. The run-scoped cache makes the compaction frame
the only one that costs a lookup, and the stamper soft-resolves the user id
once at build time — like the worker's write paths beside it — so a launch path
that never inherits the auth contextvar (a null-owner scheduled task) still
stamps instead of the db store's strict `AUTO` default raising per frame. A
resolved seq is cached for the run (earliest-seq-wins makes it final), but a
miss is not: a message this run produces reaches a frame before `RunJournal`
flushes it, so it misses and is persisted moments later. Misses are re-asked
when `RunJournal.feed_generation` — bumped once per successful event-store
write, never while the buffer merely fills — shows the feed gained rows, which
keeps the retry bounded by writes rather than by frames and makes a failed
lookup cost one generation instead of the run. REST
reads (`GET /threads/{id}/state`, `POST /threads/{id}/history`) stamp through
`events/message_seq.py::stamp_messages_with_seq`, the request-scoped
counterpart: everything a checkpoint still holds is already persisted, so one
batched lookup resolves the whole list. The db store prefilters candidate rows
in SQL (a LIKE clause per wanted raw id, wildcards escaped; an id `json.dumps`
would escape falls the set back to the full scan) so a wanted identity absent
from the feed — a message still streaming — does not force a full
fetch-and-decode of every message row's tool outputs on long threads.
`deerflow_seq` is server-owned display metadata: the gateway strips it from
client input, because a welded-in seq goes stale when a fork re-seeds the feed
(#4380).

**Run delivery receipts** (`runtime/journal.py` + `runs/worker.py`):
`RunJournal` records each non-empty artifact update once per tool `Command` for
the terminal `run.delivery` event. When a command contains multiple messages, a
unique tool name resolved from matching `ToolMessage` entries supplies
attribution; additional command messages do not duplicate artifact paths or
counts. If multiple different tool names resolve for one flat artifact update,
the paths remain counted but unattributed because the command does not carry a
per-path mapping. `RunJournal` callbacks set `run_inline=True`: they do only
in-memory bookkeeping or schedule async writes, and staying on the run's
event-loop thread serializes parallel tool callbacks before terminal delivery
recording and flushing. Each worker creates a separate journal per run before
cancellable/fallible preflight work, so checkpoint compatibility failures and
cancellation while waiting for prior finalization still emit a zero-delivery
receipt. The worker flushes ordinary journal events, idempotently persists the
run-scoped receipt, and only then persists the staged terminal run status. A
receipt failure is retried on a short bounded schedule while the owning worker
still knows the real outcome and holds the lease; `terminal_commit_pending` keeps
heartbeat renewal running until the staged status is committed. Delivery candidates are every
regular file created or modified under `/mnt/user-data/outputs`; internal
process-feedback files are excluded (the scanner's `EXCLUDED_DIR_NAMES` plus
the configured `tool_output.storage_subdir`), so a run that only externalized
oversized tool outputs does not fail delivery. At least one candidate must be
covered by a path attributed by the journal to `present_files`; presenting only
an unrelated pre-existing path does not satisfy delivery. Receipts for such
runs add `produced_paths`, `presented_paths`, `matched_paths`, `verification`,
`stage`, and `satisfied` to the Slice 1 fact fields. Missing a matching
presentation becomes a run error; a successful presentation is also downgraded
to error if its receipt cannot be durably verified. Runs without changed
outputs preserve ordinary chat behavior and the original receipt shape. Orphan
recovery first atomically claims an expired lease, then uses the same singleton
write to backfill a zero-delivery receipt — a stale recovery scan cannot
overwrite a live run's later detailed receipt, an event-store outage does not
undo the terminal takeover, and an existing detailed receipt is preserved when
a worker crashed after writing it. Event stores serialize `put_if_absent` with
ordinary thread writers: memory and JSONL provide the documented
single-process guarantee, while the DB store adds per-thread in-process locks
and PostgreSQL advisory locks for cross-process writers. Moving journal
construction ahead of preflight is receipt-only on early failure paths: a
separate boundary flag preserves the previous completion-data semantics, so
checkpoint incompatibility or cancellation while waiting for an older
finalizing run does not persist an empty completion snapshot. Worker tests pin
one accumulated receipt across multiple goal-continuation `_stream_once` calls;
journal tests drive LangChain's real async callback dispatcher against a single
journal to pin serialized, deduplicated parallel tool callbacks.

A satisfied goal evaluation remains a run-local completion candidate until
delivery, receipt persistence and terminal cancellation arbitration finish.
The worker confirms successful status persistence before clearing the goal;
delivery failure leaves goal state and continuation counters unchanged. Final
clearing holds the goal lock and the existing durable `checkpoint_write`
reservation, rechecks the complete goal snapshot and visible conversation,
then guards the write with the latest checkpoint ID. If another run has already
been admitted, the old completion leaves the goal alone. This allows duration
bookkeeping while preserving newer goal or conversation changes. Delivery
failure does not itself queue a hidden continuation.

**Workspace change detection** (`workspace_changes/diff.py`, `scanner.py`):
`get_changed_paths()` owns change filtering for summaries, text capture, and
output delivery detection. Absence from a truncated snapshot is unknown:
require a complete before snapshot to infer creation and a complete after
snapshot to infer deletion. Keep comparing files observed in both snapshots and
preserve the summary's truncation flag. The scanner walks directories and files
in sorted order so the truncation boundary is reproducible across the before
and after scans. Its budget is shared and consumed root by root (workspace
before outputs), so a workspace at the limit starves outputs.
`get_changed_output_paths()` inherits this uncertainty: newly observed outputs
are suppressed when the before snapshot was truncated, while modifications
observed in both snapshots remain eligible. The worker passes this list through
`_produced_output_paths()` to its delivery check; an empty list leaves
`produced_paths` and `verification` absent from the delivery receipt, and
`_delivery_error()` returns no error. When that empty list accompanies a truncated
pre-run snapshot, the receipt includes
`verification_skipped: "truncated_pre_run_snapshot"` on both normal completion and
failure/cancellation cleanup. This marker explains the skipped check without
asserting that no outputs were produced. Observed modifications still receive the
ordinary verification verdict, without a skip marker. A missing snapshot or
capture error alone does not imply this skip reason. These cases are pinned
through real snapshot capture and `run_agent()` in
`tests/test_run_worker_delivery.py`.

**Extension changed-run discovery** (`runtime/runs/store/` and
`extensions/run_evidence.py`) orders public run-record changes by the
backend-owned `(change_seq, run_id)` key rather than timestamps or per-thread
event sequence numbers. The singleton SQL clock allocates positions in the same
transaction as each public record mutation; memory uses a process-local counter.
The clock row serializes position-bearing SQL mutations globally until their
transactions commit, so every mutator must acquire it before any run-row lock.
An atomic thread operation uses one position for its interrupted rows and new
row, with `run_id` ordering ties. High-frequency progress snapshots and lease
heartbeats do not advance this position: they are not lifecycle-discovery
signals, progress evidence remains available from the event stream, and
excluding them bounds clock contention. A later lifecycle change exposes the
run row's latest `updated_at` and accumulated progress fields to internal readers.
Rows from before the migration retain `change_seq=0` and page deterministically
by run id. Because a later mutation only moves a row forward, concurrent paging
may replay a run but cannot move an unseen run behind the committed cursor.
Deletes produce no tombstone and therefore do not advance the cursor; consumers
that require deletion reconciliation must poll authoritative status for known
runs and treat a missing result as absent.
The extension-facing cursor is versioned, opaque, and bound to the reader's
fixed user scope. `RunEventStore.list_events()` accepts the same explicit
`user_id` override as `list_messages()`; evidence readers must propagate their
bound scope (including global `None`) rather than resolving an ambient request
user. The adapter deep-copies event content and redacted metadata before
exposing them, detaching nested mutable payloads from host storage.

Gateway `POST /api/threads/{id}/history` uses that lookup to migrate legacy AI
messages. An exhaustive miss preserves the human-boundary fallback; an
incomplete lookup removes unproven synthesized IDs. Its metadata-only
write-on-read cache stores `run_message_ids` for every audited AI ID (including
exhaustive misses) plus required `run_durations`; duration presence alone does
not prove attribution. Historical `body.before` reads write the audit to the
head, and the merge may retain IDs no longer in materialized history, which
readers ignore. Migration must acquire the durable `checkpoint_write`
reservation, then repeat the whole message audit and batch-reload required run
rows before persisting. Post-admission exact hits replace foreground exact or
boundary mappings, and recomputed final durations replace foreground snapshots.
Successful workers keep their durable run row active through the final duration
checkpoint write, so a peer migration cannot enter during terminalization.
The first `RunManager.list_by_thread()` hydration page uses a 100-row floor or
the number of required IDs, whichever is larger; missing exact runs use targeted
`get()` calls.

**Terminal run cleanup explicitly breaks graph-scoped references while preserving the existing `RunRecord` grace period.** Every `agent.astream()` iterator is closed in `_stream_once`, including abort/exception/early-break paths. A close failure after an abort is warning-only and cannot replace the user-requested `interrupted` outcome; normal-completion close failures still surface, and an in-flight stream exception remains authoritative over a secondary close failure. Journal construction and cancellable preflight work (including MCP task projection and the prior-finalization wait) live inside the worker's guarded body, so cancellation before agent startup still terminalizes the run and closes its stream. `run_agent()` wraps the complete terminal-finalization sequence in an outer teardown guard, so cancellation or failure from any terminal-stage await cannot skip `RunJournal.close()`, removal of the journal, `__pregel_runtime`, and internal runtime-context values from every runnable config, or release of local graph/payload references. That guard schedules bridge cleanup, run-record cleanup, and cyclic GC even when interruption happens before the terminal stream marker or terminal publication itself fails, so neither a cancelled observer nor a delivery-backend outage can strand process-local run state. The registered worker owns a named `run-finalization-<run_id>` task through the whole terminal sequence and resource teardown. Every host wait shields and drains that same task across repeated cancellation; there is no per-step cancellation deadline that can detach a write. Backend operations must provide their own I/O bounds. The first host cancellation stays in the worker, independent of step results, and is re-raised after finalization settles; an escaping finalizer failure is retained as its cause. The optional completion hook runs in an owned child task and still receives host cancellation, including one deferred before the hook starts; the finalizer awaits its settlement before task-stop observers and END. Task-stop fan-out retains its existing observer timeout and rogue-cancellation containment. Clearing the finalizing barrier and publishing END preserve their ordering: a barrier-clear failure prevents END, while END failure surfaces after the barrier is clear. Shutdown includes every terminal worker whose task is still active, even after its durable status commits. Its existing bounded drain logs pending workers and retains their ownership; expiry is not permission to cancel or retire a finalizer. `RunJournal.flush()` clears its `_pending_progress_task` after awaiting or cancelling it; ordinary `close()` detaches the event store/progress reporter and clears callback bookkeeping only after that flush succeeds, preserving the buffer for retry on a transient store failure. A fenced worker instead calls `close(flush=False)`, which cancels pending journal work and detaches without initiating another event-store write after lease ownership is lost; its final detach runs even if a second cancellation interrupts pending-task shutdown. `RunManager.cleanup(run_id)` retains the process-local `RunRecord`, completed task, and request payload for its default 300-second local join/status window before releasing them, and evicts only when a `RunStore` backs the manager — without one there is no hydration fallback, so the record is retained rather than silently dropping the run's history. Durable history remains in `RunStore`; `StreamBridge` data keeps its separate 60-second late-subscriber window, and both cleanup coroutines run in a fresh empty `contextvars.Context`. A contextless full cyclic-GC pass, coalesced to at most once every 10 seconds and dispatched through the default executor, bounds the lifetime of unreachable LangGraph callback/loop cycles without synchronously walking the heap in the event-loop timer; passes taking at least 100 ms are logged at INFO because CPython GC may still impose interpreter-level pauses.

**Checkpoint channel benchmark**: `scripts/benchmark/checkpoint/bench_channels.py`
runs paired `full`/`delta` message-only StateGraphs in a fresh child process per
case, using sync `InMemorySaver` or `SqliteSaver` so reducer, serialization, and
saver costs stay separate from Gateway/async scheduling. Optional
`AsyncPostgresSaver` cases are enabled only when `TEST_POSTGRES_URI` is set.
Postgres cases use a unique thread and remove only that benchmark thread through
the saver's public `adelete_thread` API after measurement. It reports deterministic
correctness digests, write windows/percentiles, warm and graph-rebuilt cold reads,
backend-neutral checkpoint/blob/write row and byte fields, aggregate logical
checkpoint/write bytes, SQLite DB/WAL/SHM footprint, reducer replay time, and
peak RSS as versioned JSONL. SQLite embeds channel blobs in its checkpoint
payload, so its separate blob metrics are zero; Postgres reports its
`checkpoint_blobs` table separately. Byte fields describe each saver's serialized
representation and should not be treated as identical encodings across backends.
The controller alternates mode order and rejects
performance data when paired modes materialize different state. Its default 1 GiB
estimated cumulative full-payload cap skips both modes of an oversized pair when
`full` is selected, including every delta cadence in a `--snapshot-frequencies`
sweep; intentional `--modes delta` diagnostics bypass this full-payload cap, so
size those runs explicitly. Use `--allow-large-cases` only
on a provisioned machine. Duplicate CSV matrix values are ignored with a warning;
use `--repetitions` for repeated samples. Summarize paired successful repetitions
with `scripts/benchmark/checkpoint/summarize_channels.py` (all ratios are
`delta/full`). `--profile-dir /tmp/checkpoint-profiles` writes one cProfile
artifact per case for attribution. Profiled rows carry `profiled: true`, and the
summarizer automatically excludes them from baseline summaries with a warning.
Storage-size collection relies on saver-specific diagnostic layouts; if those
layouts change, the timing/correctness row remains successful while storage
fields become `null` and `storage_stats_error` records the diagnostic failure.
Example:

```bash
cd backend
PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_channels.py \
  --backends sqlite --updates 100,500,999,1000,1001 --payload-bytes 128 \
  --repetitions 7 --output /tmp/checkpoint-bench.jsonl
TEST_POSTGRES_URI=postgresql://... \
PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_channels.py \
  --backends sqlite,postgres --updates 100 --payload-bytes 128 \
  --output /tmp/checkpoint-cross-backend.jsonl
PYTHONPATH=. uv run python scripts/benchmark/checkpoint/summarize_channels.py \
  /tmp/checkpoint-bench.jsonl
```

The production-shaped layer lives in
`scripts/benchmark/checkpoint/bench_production.py`: per-case child processes
run graph-level `ainvoke` turns through the real lead-agent graph (scripted
deterministic model, real `AsyncSqliteSaver`), then measure
`GET /threads/{id}/state` and `POST /threads/{id}/history` through the real
Gateway route stack in the same event loop (httpx ASGITransport), split into
cold/warm accessor-graph-cache samples. It sweeps `snapshot_frequency`
(config: `checkpoint_delta.snapshot_frequency`, process-frozen like the mode),
pairs every delta frequency against the same full row, and fails both
rows of a pair when materialized or wire digests diverge. Each case must have
more than the two discarded warm-up turns, and SQLite DB/WAL/SHM sizes are
captured while the saver is still open so they represent the online storage
footprint. Summarize with
`scripts/benchmark/checkpoint/summarize_production.py` (ratios are
`delta/full`; it also emits `snapshot_write_spike` and `cache_effect_ms`,
the decision inputs for the production snapshot-frequency and accessor-cache
defaults). Harness tests live in `tests/test_bench_checkpoint_production.py`
and `tests/test_summarize_checkpoint_production.py`; timing thresholds are
not CI gates. The matrix test pins that every `(repetition, turns)` group
contains both modes and that their execution order flips between consecutive
groups, including across repetition boundaries.

Operational limits learned from the first runs (the default matrix is too
large to run blindly):

- The default `--timeout-seconds 900` is insufficient for delta mode at
  `snapshot_frequency=1000` once turns reach 500 (measured: delta-500 takes
  ~1100-1200s; delta-2000 takes ~45min). Pass an explicit
  `--timeout-seconds` for any large matrix, and treat the turns=2000 corner
  as practical only at small snapshot frequencies.
- Full-mode 2000-turn runs produce a ~33GB sqlite DB. Point `TMPDIR` at real
  disk, not tmpfs (the benchmark uses `tempfile.TemporaryDirectory`, which
  honors `TMPDIR`), or the run dies mid-case.
- The history route clamps `limit` to 100 (`le=100` on
  `ThreadHistoryRequest.limit`), so `--history-limits` values above 100 are
  measured and reported by their effective (clamped) limit.

Example:

```bash
cd backend
PYTHONPATH=. uv run python scripts/benchmark/checkpoint/bench_production.py \
  --turns 10,100,500,1000,2000 --payload-bytes 128 \
  --snapshot-frequencies 10,50,100,500,1000 \
  --repetitions 7 --output /tmp/production-bench.jsonl
PYTHONPATH=. uv run python scripts/benchmark/checkpoint/summarize_production.py \
  /tmp/production-bench.jsonl
```

## Checkpoint channel modes and replay

Reject missing selected/head tuples or pending Sends before delta rewrites.
Null input and `Command(resume=...)` also reject pending nodes except `__start__` on both.
Use `CheckpointResumeRejected` to skip pre-write rollback; resume at head.

Checkpointer storage runs in one of two channel modes, selected by `checkpoint_channel_mode` in `config.yaml` (default `full`). `delta` mode adopts LangGraph 1.2's `DeltaChannel` for `messages`: checkpoints store a sentinel + per-step writes instead of the full message list, so storage/serde grows O(N) instead of O(N²) in turns. All checkpointer backends (memory/sqlite/postgres) serve both modes unchanged — the semantics live in the compiled graph's channel table, not in the saver.

**Mode is process-frozen and restart-required.** `make_lead_agent` and the embedded `DeerFlowClient` freeze the resolved mode (`runtime/checkpoint_mode.py::freeze_checkpoint_channel_mode`) before compiling the graph with the mode-matched schema (`agents/thread_state.py::get_thread_state_schema`, plus `adapt_state_schema_for_mode` / `normalize_middleware_state_schemas` for middleware state). Adapted middleware schemas are cached by schema, mode, and resolved snapshot frequency so a pre-freeze ephemeral graph cannot leave a stale default-frequency schema behind. A second, different mode or frequency in the same process raises `CheckpointModeReconfigurationError`. To switch: edit config, restart.

**Delta snapshot cadence is configurable but frozen with the mode.** `database.checkpoint_delta.snapshot_frequency` (default `10`) sets the `DeltaChannel` snapshot cadence. It is frozen alongside the mode (`freeze_checkpoint_snapshot_frequency`; non-positive direct inputs raise `ValueError`, while a frozen-value mismatch raises `CheckpointModeReconfigurationError`), restart-required, and must match across every process sharing one checkpoint database — the cadence lives in each compiled graph's channel table and is deliberately NOT stamped into checkpoint metadata, so the mode-compatibility marker and full -> delta migration semantics are unchanged. Schema helpers resolve it explicit-arg -> frozen -> default, and every schema/graph cache (`_delta_thread_state_schema`, `_adapt_state_schema_for_delta`, the client agent-config key, the gateway accessor-graph cache) keys on the resolved value.

**Compiled-graph cache cap is configurable and hot-reloadable.** `database.checkpoint_graph_cache.accessor_graph_max` (default `64`) bounds the gateway accessor-graph cache, which clears wholesale at the cap. The cap is re-read on every eviction check (`resolve_checkpoint_graph_cache_max`), so a config.yaml reload takes effect without a restart — a size change never affects graph semantics, only eviction timing.

**Compatibility is asymmetric and fail-closed.** Every checkpoint written in delta mode carries metadata marker `deerflow_checkpoint_channel_mode: "delta"` (injected via `inject_checkpoint_mode`; absence of marker = full, so pre-feature checkpoints need no migration). Before any state read/write, `ensure_checkpoint_mode_compatible` rejects a full-mode process opening a delta thread with `CheckpointModeMismatchError` (surfaced as HTTP 409 with the cause and thread id by the threads router; `CheckpointModeReconfigurationError` maps to 503) — a full-mode raw read of a delta blob would silently return empty/partial `messages`. The reverse direction is allowed: delta-mode processes read full checkpoints transparently (old full checkpoints seed the delta channel), so full → delta is the smooth migration path; delta → full requires materializing/converting the data first. Detection also honors upstream's `counters_since_delta_snapshot.messages` metadata, and an explicit config marker takes precedence over any ambient context value.

**Never bypass `CheckpointStateAccessor` (`runtime/checkpoint_state.py`) for thread-state access.** It is the single choke point binding graph + checkpointer + mode: it injects the mode marker into configs, runs the compatibility check before every `get`/`update`/`history`, and returns materialized state (delta checkpoints lack `channel_values.messages` — raw `get_tuple` reads see a sentinel). An async unpinned delta read verifies that its resolved checkpoint still exists after materialization and retries once from the new head when retention removed that target mid-read; explicit historical selections never silently move. For metadata-only reads, use `get_metadata` / `aget_metadata` to retain the mode gate without materialization. Thread-owned reads must use `build_thread_checkpoint_state_accessor` so the recorded assistant schema materializes every channel. Sync checkpoint mutations must drain off-thread commits before cancellation propagates; sync `get_tuple` reads remain cancellable. `history(limit)` semantics: `0` means zero items (explicit empty), `None` means unlimited — do not pass `limit=0` through to `graph.get_state_history`. Assistant metadata lookup is fail-closed for mutation accessors so a store outage cannot silently select the default schema and discard extension channels. In `full` mode the read path degrades to a raw checkpointer read (`_RawCheckpointReadAccessor`) when the agent factory cannot build the graph (bad model config, MCP outage) — full checkpoints carry complete `channel_values`, so reads don't need the graph; degraded snapshots take `created_at` from the standard checkpoint `ts` field, falling back to metadata only for compatibility. The delta gate still applies on the degraded path; `next`/`tasks` degrade to empty and thread status falls back to the stored status because task presence is not derivable, while delta mode has no fallback (materialization needs the channel table).

**Replay checkpoint lookup prefers lineage and degrades only for an explicitly missing legacy parent link.** Branch and regenerate paths first walk `parent_config`, which prevents a global chronological scan from selecting a sibling created by regeneration. `CheckpointParentMissingError` alone enables the bounded newest-first history fallback in `app/gateway/checkpoint_lineage.py`; cycles, dangling/non-addressable parents, target mismatches, and depth exhaustion raise `CheckpointLineageIntegrityError` and fail closed instead of selecting a sibling. The compatibility scans request 400 raw checkpoints so up to 200 duration-only entries do not consume the effective branch-history budget; the fallback scans oldest-to-newest internally, skips duration-only checkpoints, and accepts only checkpoints with an addressable id as the replay base. A source history with no discoverable pre-user checkpoint preserves the historical single-checkpoint branch behavior instead of rejecting the branch; regeneration remains unavailable for that inherited response. Existing single-checkpoint branches are not mutated by regenerate preparation, and no raw checkpoint tuple is copied across threads because delta state depends on ancestry and pending writes. Regenerate source-run lookup uses the current thread's exact event, then the server-stamped `run_id` on the copied human message, then verified RunManager content matching; it does not read parent-thread events. When an interrupted response was streamed but never checkpointed, regeneration accepts only the latest visible human message's server-stamped `run_id` after verifying that it belongs to the same thread and still has `interrupted` status. Storage or checkpoint-mode failures are not treated as a missing base and still fail closed.

**A delta-mode run cannot fork; `runtime/runs/worker.py` linearizes the resume instead.** An older-checkpoint resume creates siblings whose pending writes can replay into the fork, retaining a superseded answer. Write-to-child ownership belongs to the upstream delta contract, so DeerFlow does not reimplement the walk: `_linearize_delta_checkpoint_resume` materializes the requested checkpoint's complete state and writes every channel onto the **current head** (which has no siblings) through the state mutation graph, using `Overwrite` for reducer channels and resetting newer head-only channels to their schema default (or `None` when no constructible default exists); it then drops the `checkpoint_id` selector and lets the run proceed linearly, while the abandoned turn stays in history as the rewritten head's ancestry. The worker holds `_checkpoint_thread_lock` across `_capture_rollback_point` and the optional linear rewrite, making the rollback snapshot and rewrite atomic with graph streaming and the preceding run's duration-metadata checkpoint write. Capture preserves the complete real pre-run state; cancel-with-rollback then linearly replaces the current delta head with that captured state rather than forking the now-shared pre-run checkpoint, so the abandoned turn is restored without replaying the resume sibling's writes. The worker also recomputes the current-run message boundary from the rewritten state and fails closed (an unreadable resume checkpoint raises rather than falling back to the corrupt fork). `full` mode keeps forking — its checkpoints carry complete `channel_values` and need no replay — so LangGraph branching semantics are unchanged there. Root namespace only; subgraph namespaces are left alone.

**Wholesale state replacement uses a state-only mutation graph + `Overwrite`.** `update_state` values pass through channel reducers (`add_messages` merge in full, append in delta), so replacing reducer values requires `Overwrite` rather than an ordinary update. Full-mode rollback and context compaction replace `messages`; delta resume and delta rollback replace every materialized channel and reset current-head-only channels to their schema default (or `None`). These writes go through `build_state_mutation_graph(as_node, mode, state_schema)`, and `state_schema` MUST be the thread's effective schema (`graph_state_schema(assistant_graph)`), because the base-ThreadState fallback silently discards written channels contributed by custom `AgentMiddleware.state_schema`. Channels absent from a full-mode fork write inherit the parent's channel blobs, so middleware channels survive rollback/compaction (locked by `test_rollback_preserves_middleware_contributed_channels` and `test_compact_thread_context_preserves_middleware_contributed_channels`). The compiled mutation graph has one no-op node (entry = finish) whose checkpoint machinery (channels/versions/metadata) is identical to the agent graph's but schedules no pending tasks, so the restored/compacted head stays idle instead of re-triggering the agent. Never hand-write checkpoints via `checkpointer.aput` for this; raw writers elsewhere must preserve checkpoint parentage — severed ancestry breaks delta replay (see `runtime/runs/worker.py` writer parenting and `checkpoint_patches.py`).

**Run rollback flow** (`runtime/runs/worker.py`): `_capture_rollback_point` materializes the complete pre-run state via the accessor and captures raw `pending_writes` via `aget_tuple` into an immutable `RollbackPoint` before the run starts — capture failure, including cancellation delivered before or during the capture await, disables rollback (fail-closed), never restores partial state, and never deletes the thread; only a capture that completes and finds no checkpoint may reset the thread to empty. In `full` mode, cancel-with-rollback forks from the pre-run checkpoint via the mutation graph and inherits non-message channels from that parent. In `delta` mode, forking is unsafe once the cancelled path has attached sibling writes to the pre-run checkpoint, so rollback replaces every captured channel on the current head, using `Overwrite` for reducers and schema defaults for current-head-only channels. Resume and rollback state rewrites copy only the selected/captured checkpoint's server-authored agent binding; missing or malformed bindings remain unbound. Both modes reattach only the captured pre-run pending writes to the restored checkpoint. Edit replay runs (`metadata.replay_kind="edit"`) also restore the pre-run checkpoint on failed, timed-out, or interrupted completion and publish the restored `values` snapshot to the stream before `end`, so clients do not remain on a transient edited branch when the replay did not produce a successful replacement.

### Checkpoint implementation map

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

## Deferred terminal commits and lease ownership

**Deferred terminal commit:** With an event store, the worker stages its terminal
status locally and commits it only after finalization's receipt and duration
writes. `RunRecord.terminal_commit_pending` keeps `_renew_leases()` renewing that
still-active row until its own terminal write is acknowledged or ownership is
lost. Manager-owned attempts register separate futures before Store I/O and
publish an immutable outcome proof only on explicit successful commit results;
matching row fields and legacy `None` results cannot confirm a commit. Atomic
replacement registers attempts before admission I/O and acknowledges only the
returned claimed rows, using their committed outcome fields. It does not repeat
the interrupted update. An interrupted ACK is intermediate while a live Worker
still owes rollback: keep a separate rollback barrier and explicitly renew that
interrupted row under the same live-owner/lease predicates until the final error
ACK. An active-only renewal that was already in flight across atomic rollback
admission is retried once with `allow_interrupted=True` only after this Worker's
interrupted ACK is available, and only while that same per-run decision remains
inside its original deadline. An in-flight admission ACK is awaited; row state is
never reread as attribution. Peer takeover, an expired lease, a changed/final
outcome, or a second rejection still fences. Even without an event store, defer
rollback's error write until restoration has finished. `tests/test_stale_active_renewal.py`
covers the Manager transition (including an ACK still in flight), and
`tests/test_atomic_admission_worker.py` covers the real Worker restoration/error
tail with and without an event Store. A fenced Worker must not begin a rollback checkpoint restoration,
including when fencing itself delivered cancellation. Admission compensation never retries an unowned write in heartbeat
mode. A local deadline guard remains armed after fast renewal errors and after
heartbeat stop; it rechecks the latest lease/proof and fences without waiting for
the admission lock. Record removal and final ACK cancel its timer. Bounded orphan
recovery drain requests cancellation, retains/observes unfinished I/O, and returns
without joining a cancellation-resistant Store. Neither that return nor heartbeat
stop authorizes closing still-in-use resources. A rejected
CAS never falls back to another terminal writer. In heartbeat mode completion
updates require that proof and an atomic matching terminal status/owner in Store;
they only enrich metadata. Single-worker completion retains its recovery fallback.
Never select runs for renewal by local status alone. Each run has a single-flight
renewal check and supervised I/O, bounded by its last confirmed durable lease and
a monotonic wait budget. Heartbeat ticks do not join slow checks; cancellation
signals are delivered per run as results arrive. Timeout requests cancellation
without joining cancellation-resistant I/O, whose late results are observed but
cannot restore local authority. Shutdown drains within its shared budget and
reports outstanding I/O rather than claiming it stopped. SQL/Memory reject expired
renewals. `stop_heartbeat()` is not a Store-resource idle barrier: a driver that
suppresses cancellation can retain its connection until the supervised I/O settles
or the process exits; closing that resource cannot be claimed safe from this return.
Owned terminal writes require a live owner lease (Postgres checks DB time
after its row lock). These guards do not fence every RunStore mutation or provide
a persistent attempt identity. Permanently missing ACKs may conservatively fence
a committed run. Shutdown's drain treats the
same state as active, and also awaits committed terminal workers still executing
hooks, END or resource cleanup. The registered worker shields and drains one owned
finalizer across repeated host cancellation, preserving the first interruption even
if a step fails. There is no deadline that cancels or detaches writes; backend I/O
must be bounded by its backend. Only the optional completion hook receives host
cancellation, and its child task is drained before the terminal tail continues.
A drain timeout leaves staged statuses and commit barriers intact without persisting `interrupted`. A finalizer that raises is
logged with its run ID, staged status and exception while the other runs continue
draining. Coverage: `tests/test_gateway_run_drain_shutdown.py`.

# Runtime implementation details

The runtime AGENTS.md indexes these detailed contracts. Preserve their behavior when changing the corresponding code.

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
still knows the real outcome and holds the lease. Delivery candidates are every
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

**Terminal run cleanup explicitly breaks graph-scoped references while preserving the existing `RunRecord` grace period.** Every `agent.astream()` iterator is closed in `_stream_once`, including abort/exception/early-break paths. A close failure after an abort is warning-only and cannot replace the user-requested `interrupted` outcome; normal-completion close failures still surface, and an in-flight stream exception remains authoritative over a secondary close failure. Journal construction and cancellable preflight work (including MCP task projection and the prior-finalization wait) live inside the worker's guarded body, so cancellation before agent startup still terminalizes the run and closes its stream. `run_agent()` wraps the complete terminal-finalization sequence in an outer teardown guard, so cancellation or failure from any terminal-stage await cannot skip `RunJournal.close()`, removal of the journal, `__pregel_runtime`, and internal runtime-context values from every runnable config, or release of local graph/payload references. That guard schedules bridge cleanup, run-record cleanup, and cyclic GC even when interruption happens before the terminal stream marker or terminal publication itself fails, so neither a cancelled observer nor a delivery-backend outage can strand process-local run state. A non-`Exception` `BaseException` caught while awaiting the completion hook or task-stop notification (including host-task cancellation) is deferred through the ordinary remaining finalization, with the first interruption preserved and every caught host-task `CancelledError` balanced by calling `Task.uncancel()` until the current task’s cumulative cancellation count is clear. Task-stop fan-out runs in one child task and every host wait uses `shield`, so repeated cancellation of the worker cannot cancel that fan-out or skip later observers; the worker keeps awaiting the same child task. A rogue observer that raises its own `CancelledError` remains contained by the extension dispatcher and distinguishable from host cancellation. This guarantee applies only to cancellation caught during those hook stages: clearing the finalizing barrier and publishing END remain direct awaits, so another cancellation in the subsequent critical tail retains forceful-termination semantics instead of creating an unbounded shield. If that tail completes without another interruption, the first deferred interruption is re-raised after END; a barrier-clear failure prevents END publication, while an END failure is raised after the barrier is clear. `RunJournal.flush()` clears its `_pending_progress_task` after awaiting or cancelling it; ordinary `close()` detaches the event store/progress reporter and clears callback bookkeeping only after that flush succeeds, preserving the buffer for retry on a transient store failure. A fenced worker instead calls `close(flush=False)`, which cancels pending journal work and detaches without initiating another event-store write after lease ownership is lost; its final detach runs even if a second cancellation interrupts pending-task shutdown. `RunManager.cleanup(run_id)` retains the process-local `RunRecord`, completed task, and request payload for its default 300-second local join/status window before releasing them, and evicts only when a `RunStore` backs the manager — without one there is no hydration fallback, so the record is retained rather than silently dropping the run's history. Durable history remains in `RunStore`; `StreamBridge` data keeps its separate 60-second late-subscriber window, and both cleanup coroutines run in a fresh empty `contextvars.Context`. A contextless full cyclic-GC pass, coalesced to at most once every 10 seconds and dispatched through the default executor, bounds the lifetime of unreachable LangGraph callback/loop cycles without synchronously walking the heap in the event-loop timer; passes taking at least 100 ms are logged at INFO because CPython GC may still impose interpreter-level pauses.

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

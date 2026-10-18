# Checkpoint Retention Contract (DRAFT)

Status: **draft** — the deletion contract for #4189 item 3. The storage
service and its contract tests predate the production trigger; every future
deletion shape must still be validated against
`backend/tests/test_checkpoint_retention_contract.py`.

## Why a contract is needed

LangGraph checkpoints form a per-thread **parent chain**. Gateway features
depend on that chain being intact:

- **Branch / regenerate** resolves the replay base by walking
  `parent_config` links from a checkpoint that contains the target message
  (`app/gateway/checkpoint_lineage.py::find_checkpoint_before_message`).
- **Explicit resume** replays from a `checkpoint_id` a client still holds.

Deleting checkpoint rows by recency or table size can therefore break those
features **silently** — a missing ancestor surfaces as
`CheckpointLineageIntegrityError` at branch time, or as a lost resume target,
never as an obvious storage bug. The contract below separates deletable rows
from protected rows and pins the verification method.

## Data model

| Backend   | State rows              | Writes rows        |
| --------- | ----------------------- | ------------------ |
| SQLite    | `checkpoints`           | `writes`           |
| Postgres  | `checkpoints`, `checkpoint_blobs` | `checkpoint_writes` |
| Memory    | `saver.storage`, `saver.blobs` | `saver.writes`     |

(Note: SQLite has no separate blob table; channel values live inside the
serialized checkpoint payload. Postgres splits blobs out.)

Measurement shape: per-thread rows + bytes per table, normalized by
`bench_channels._normalized_storage_stats`.

## Protected set (MUST NOT delete without the stated compensation)

1. **Explicit resume targets** — any `checkpoint_id` a client may still
   resume to. Deleting it removes the replay surface
   (`test_deleting_explicit_resume_target_breaks_resume`). A retention policy
   may expire these, but only with an explicit TTL semantic agreed here.
2. **Branch ancestors** — every checkpoint on the parent chain from a
   branchable head back to (and including) the checkpoint *before* the oldest
   branchable message. Deleting any node on that walk breaks branch/regenerate
   with `CheckpointLineageIntegrityError`
   (`test_deleting_branch_ancestor_breaks_lineage_loudly`).
3. **Pending writes** — rows in the writes table are uncommitted/in-flight
   state, not garbage (`test_pending_writes_are_retained_state_not_garbage`).
4. **Duration-only chain links** — `persist_run_durations` appends
   metadata-only checkpoints. A duration-only checkpoint that a later run has
   forked from is a *chain link*: the walk steps through it, so deleting it
   requires **grafting** the fork onto the grandparent (rewriting the fork's
   `parent_config`) in the same change. A bare leaf (below) is safe; a link is
   not. The link shape can only be produced by the real runtime, so the graft
   path is specified here and intentionally not covered by a storage-level
   test.
5. **Latest resumable state per thread** — the newest checkpoint must remain
   addressable so a thread can always continue.

## Provably safe forms (validated by tests)

1. **Leaf sibling branches** — a checkpoint forked off an older turn that has
   no children (`test_leaf_sibling_branch_deletion_is_safe`). Pruning it does
   not affect the main line's walk, explicit resume, or head.
2. **Trailing duration-only leaves** — a duration-only checkpoint no later run
   has forked from (`test_leaf_duration_checkpoint_deletion_is_safe`).

New deletion proposals must add their shape as a test here: construct the
chain, delete, then verify (a) latest resume, (b) explicit `checkpoint_id`
resume, (c) branch from an older visible turn, and (d) orphan row counts.

## Deletion mechanics

- Deletion must cover the backend's tables jointly and account for orphans, and
  blob reachability must be computed from the **surviving checkpoints in a
  whole-thread pass**: after deleting a checkpoint row, a `checkpoint_blobs` /
  `checkpoint_writes` row is an orphan only if *no surviving checkpoint*
  references it. The shared-version case is not hypothetical — the real
  duration-only checkpoint is a copy of the head checkpoint dict
  (`persist_run_history_metadata` replaces only id/ts), so it inherits the
  parent's `channel_versions` verbatim, and on Postgres the blob rows
  reachable from the deleted duration row are the same rows backing its
  parent. An implementation that deletes blobs keyed by the removed
  checkpoint's own `channel_versions` would corrupt the thread's newest
  surviving state — exactly the failure class this contract exists to
  prevent. (For the same reason a real duration-only leaf is not
  payload-free: it materializes the parent's values under
  `{"writes": {"runtime_run_duration": {...}}, "source": "update", "step":
  ...}` metadata, which is what makes reclaiming it worthwhile.)
- Failure semantics: if a proposed deletion cannot be proven safe against the
  protected set, it must not ship. Partial deletion that leaves a dangling
  `parent_config` converts a cleanup into a thread-level outage (branch and
  regenerate fail loudly for every later turn).
- Measurement first: proposals must include before/after numbers from
  `../scripts/benchmark/checkpoint/bench_channels.py` (per-thread rows/bytes,
  SQLite and Postgres) plus the contract test suite passing.

## History fast-path interaction (wiring requirement)

The trailing duration-only leaf is also the carrier of the run-history
metadata cache: `persist_run_history_metadata` accumulates `run_durations`
and `run_message_ids` in the leaf's metadata, and
`app/gateway/routers/threads.py::get_thread_history` reads that map from the
latest checkpoint (`_checkpoint_run_durations` /
`_checkpoint_run_message_ids`, gated on `is_latest_checkpoint`) to answer
every known turn's duration and message-to-run attribution without scanning
the event store. The parent checkpoint the leaf clones does **not** carry
that map.

Deleting the leaf (scenario E1) therefore removes the fast-path cache: the
next history read sees no durations, falls back to event-store + run-manager
scans, and `_persist_run_history_metadata_background` re-writes a fresh
duration-only leaf — which the next retention pass deletes again. Net effect
without sequencing: the reclaimed row comes straight back, plus recurring
store scans and an extra write per read.

The wiring PR that introduces the production trigger must therefore either:

1. **Sequence retention away from history reads** — e.g. run retention on a
   schedule whose next pass re-reclaims the re-created leaf, or run it when
   the thread is not being read; or
2. **Adopt a policy that spares cache-carrying leaves** — e.g. a
   `RetentionPolicy` flag that keeps any trailing duration-only leaf whose
   metadata still carries `run_durations` / `run_message_ids` (same spirit
   as the strict pending-writes guard), at the cost of not reclaiming that
   leaf's rows.

Without either, E1 pruning and history reads churn against each other. This
decision belongs to the wiring PR, not to the storage-level service: the
service cannot tell a cache-carrying leaf from a payload-free one on the
alist path without re-implementing the writer's merge semantics.

## Production completion hook

The Gateway wires the bounded trailing-leaf helper through the existing
optional `RunContext.on_run_completed` callback. The worker invokes that
callback only after a successful run has written its duration metadata and
while the same-thread finalizing fence is still held. The Gateway adapter then:

1. reserves a durable `checkpoint_write` thread operation, so another Gateway
   worker cannot admit a competing run or checkpoint mutation while the pass
   is in flight;
2. acquires `_checkpoint_thread_lock(thread_id)`, the same keyed lock used by
   the duration writer and history migration;
3. reads only the root head, its parent, and the head's pending-write row;
4. removes at most the one contract-proven trailing duration leaf and purges
   any `CachedHistorySaver` entries for that thread;
5. logs the report when a leaf is removed; and
6. invokes the scheduler completion observer regardless of whether retention
   succeeded.

The one-row budget is intentional. A successful run writes at most one new
duration-only leaf, while an older backlog may have accumulated during an
outage or an embedded caller that did not install the Gateway hook. A later
successful run can make bounded progress without turning finalization into an
unbounded sweep. The completion path does not collect storage statistics or
walk the historical checkpoint list; the exhaustive service remains available
for off-path maintenance and measurement. The durable reservation prevents a successor run from
forking from a row after classification but before deletion; the
process-local lock additionally serializes same-worker history and duration
writers. If another operation has already won admission, the hook leaves the
leaf for a later completion rather than attempting an unsafe deletion.

Retention is fail-open: unsupported savers, transient database errors, and
schema mismatches are logged and leave the run outcome and scheduled-task
completion unchanged. Embedded harness callers can omit the hook and retain
the existing behavior. The hook does not run for interrupted, failed, or
aborted records, because those paths do not create a successful duration
checkpoint and must not be treated as an opportunity to rewrite lifecycle
state.

## Item 4 note (large tool results)

`ToolOutputBudgetMiddleware` externalizes oversized tool outputs before they
reach state (preview + file reference under `.tool-results/`), so the
"50 KB result re-snapshotted every step" scenario from the original report
depends on which tools/paths bypass it. The probe
(`../scripts/benchmark/checkpoint/bench_tool_result_probe.py`) measures the
on-disk checkpoint delta for the wrapped vs unwrapped paths on the lead
graph; subagent chains instantiate the same middleware by default. Any PR
claiming a residual gap must name the concrete bypassing path and show its
probe numbers.

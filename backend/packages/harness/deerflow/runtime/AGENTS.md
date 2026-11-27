# Runtime (`deerflow/runtime/`)

Owns run admission, workers, streams, checkpoints, events and server-installed
capabilities. Details:
[runtime details](../../../../docs/runtime-guidance-details.md),
[run event stream](../../../../docs/RUN_EVENT_STREAM.md),
[streaming](../../../../docs/STREAMING.md),
[checkpoint retention](../../../../docs/checkpoint-retention-contract.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "run or stream or checkpoint or event_store or journal"
make test-blocking-io
```

## Streams and reconnect

- **A replay gap is not the end of a run.** When the retained window no longer
  covers a reconnect cursor, the bridge reports a gap and the reader reloads state.
- **Reconnect cursors are client input.** Parse them strictly and answer a
  malformed one as bad input.
- **Redis END publication is atomic.** One Lua script checks the producer token,
  detects END and appends. Restart all Gateways together when stream mode changes;
  old and new producers cannot share a stream.
- **Subscribers get their own copy.** The memory bridge copies events outside its
  condition lock, and caches copy on ingest and on read, so one consumer cannot
  change what another sees.
- **Keep registry locks short.** Heartbeats take the same locks and must not queue
  behind slow work.
- **Subgraph frames keep their namespace.** A bare `values` frame from a subgraph
  would overwrite the thread view of an SDK client. Consumers that only handle the
  root run ignore namespaced frames.

- **Memory writers fence each stream generation.** After a Condition wait,
  reject retired or ended generations before assigning event IDs. Rejected
  writes consume no sequence number; END is idempotent.

## Checkpoints

- **The channel mode is fixed for the life of the process.** A reader in `full`
  mode rejects a `delta` checkpoint; it does not guess.
- **Read and change state through `CheckpointStateAccessor`** with the thread's
  effective schema. It preserves mode gates, parentage and pending writes.
- **A failed pre-run snapshot leaves no message-ID boundary.** When a
  checkpointer exists but the pre-run capture fails, the first `values` frame
  establishes a replay baseline; only later message IDs can decide this run's
  LLM error fallback.
- **Delta resume and rollback rewrite the current head.** They do not fork.
  Reject a missing tuple or pending sends before the first write.
- **Redis history cache purges include the previous default namespace.** On
  the v1-to-v2 upgrade, purge thread data under both prefixes for the same
  database identity. Custom namespaces have an operator-managed migration.

## Admission and terminal commit

- **Only the worker that owns the run commits its terminal state.** A lost or
  expired lease fences later writes, so a recovered run is not overwritten.
- **Register completion before cleanup awaits.** Cancellation during cleanup is
  then safe, and an idempotent request gets the stored result replayed.
- **Terminal cleanup always finishes.** Streams, journals and graph references
  are closed even when the run is cancelled.
- **A provider tool-call ID is not an owner.** Providers reuse IDs across parent
  runs. The server-generated execution ID owns the registry entry, polling,
  cancellation and cleanup; the provider ID only correlates what the user sees.

## Run events and journal

- **`RunJournal` is changed on its owning event loop only.** A recorder failure
  fails open, and a slow recorder must not delay tool state.
- **Retry a sub-agent event batch only on `RunEventStoreNotCommittedError`.**
  Drain writes before propagating cancellation. Retry only when no events
  committed; an uncertain outcome stops history writes. Close the SQL producer
  only after the final flush confirms every write.
- **Usage replay may enrich a message, never add or remove one.** A provider can
  report the end of the same model call twice.
- **Event-store mutations of one thread share one fence** (an asyncio lock plus a
  PostgreSQL lock). The fence serializes writers. It does not tell an old run
  incarnation from a new one.
- **The JSONL store is single-process.** Split on LF; Unicode line separators
  within fields are data. Drain started mutations through cancellation. Save
  the sequence watermark before deletion, and fail closed if it is corrupt.
- **The in-memory store copies caller-owned content at admission.**
- **Event reads pass the trusted user identity**, and the owner on a `RunRecord`
  matches the durable row.
- **An evidence receipt needs the worker's own final acknowledgement.** An
  unknown or cancelled write outcome yields no receipt.

## Goals

- **Goal synthesis is read-only.** `goal_synthesis.py` treats conversation as
  data, redacts PII, excludes evidence tool results and uses the oneshot LLM.
  The newest turn has its own 12,000-character budget; compaction summaries
  use at most half. The Gateway saves the objective.

## Server-installed capabilities

- **Bind the image source before sandbox acquisition.** Unattended runs use a
  usable server profile when image sources coexist; interactive runs require a
  valid saved default or a correlated choice. Keep the binding through goal
  continuations and subagents, and reject a changed profile during execution.
- **Capabilities exist for one request.** The server installs scheduler,
  conversation-reader and client hints. Reject caller copies in both context
  carriers; restore none from checkpoints.
- **Run metadata and hidden messages are display data.** They grant nothing.
- **A scheduled goal is installed in a fresh thread only** and is removed before
  the terminal status commits.
- **Retry the goal evaluator only for a malformed verdict** from a normal model
  completion. Other failures are final.
- **A truncated workspace snapshot cannot prove that a file is absent.**

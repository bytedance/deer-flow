# Runtime (`deerflow/runtime/`)

Executes runs: admission, the run worker, the stream bridge (memory and Redis),
checkpoint access, the run event store and journal, and the server-installed
capabilities of a run. Background:
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
- **Redis END publication is one Lua script.** The producer-token check, the END
  detection and the append happen atomically. Restart all Gateways together when
  the stream mode changes, because old and new producers cannot share a stream.
- **Subscribers get their own copy.** The memory bridge copies events outside its
  condition lock, and caches copy on ingest and on read, so one consumer cannot
  change what another sees.
- **Keep registry locks short.** Heartbeats take the same locks and must not queue
  behind slow work.
- **Subgraph frames keep their namespace.** A bare `values` frame from a subgraph
  would overwrite the thread view of an SDK client. Consumers that only handle the
  root run ignore namespaced frames.

## Checkpoints

- **The channel mode is fixed for the life of the process.** A reader in `full`
  mode rejects a `delta` checkpoint; it does not guess.
- **Read and change state through `CheckpointStateAccessor`** with the thread's
  effective schema. It preserves mode gates, parentage and pending writes.
- **Delta resume and rollback rewrite the current head.** They do not fork.
  Reject a missing tuple or pending sends before the first write.

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
- **Usage replay may enrich a message, never add or remove one.** A provider can
  report the end of the same model call twice.
- **Event-store mutations of one thread share one fence** (an asyncio lock plus a
  PostgreSQL lock). The fence serializes writers. It does not tell an old run
  incarnation from a new one.
- **The JSONL store is single-process.** It splits on LF only, because Unicode
  line separators inside a field are data. A started mutation drains through
  cancellation. The sequence watermark is saved before a run is deleted, and a
  corrupt watermark fails closed.
- **The in-memory store copies caller-owned content at admission.**
- **Event reads pass the trusted user identity**, and the owner on a `RunRecord`
  matches the durable row.
- **An evidence receipt needs the worker's own final acknowledgement.** An
  unknown or cancelled write outcome yields no receipt.

## Server-installed capabilities

- **Capabilities exist for one request.** The scheduler capability, the
  conversation reader and client capability hints are installed by the server.
  A copy that a caller sends is rejected in both context carriers, and none is
  restored from a checkpoint.
- **Run metadata and hidden messages are display data.** They grant nothing.
- **A scheduled goal is installed in a fresh thread only** and is removed before
  the terminal status commits.
- **Retry the goal evaluator only for a malformed verdict** from a normal model
  completion. Other failures are final.
- **A truncated workspace snapshot cannot prove that a file is absent.**

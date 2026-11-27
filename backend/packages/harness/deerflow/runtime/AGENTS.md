# Runtime (`deerflow/runtime/`)

Owns run admission/worker, memory and Redis stream bridges, checkpoints, event
store/journal, and server-installed run capabilities. See
[runtime details](../../../../docs/runtime-guidance-details.md),
[run event stream](../../../../docs/RUN_EVENT_STREAM.md),
[streaming](../../../../docs/STREAMING.md), and
[checkpoint retention](../../../../docs/checkpoint-retention-contract.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "run or stream or checkpoint or event_store or journal"
make test-blocking-io
```

## Streams and reconnect

- A replay gap is not run completion: report the gap and reload state.
- Treat reconnect cursors as untrusted input; reject malformed values.
- Redis END is one Lua transaction: validate producer token, detect END, append.
  Restart all Gateways together when stream mode changes.
- Subscribers and caches own copies; one consumer must not mutate another's data.
- Keep registry locks short; heartbeats share them.
- Preserve subgraph namespaces; root-only SDK consumers ignore namespaced frames.
- **Memory close is a generation fence.** Reject writes at entry and under the
  Condition. Check retired/ended before allocating IDs or appending; rejected
  writes consume no sequence. END is idempotent. Retired readers retain their
  gap while later runs drain. Overlapping closes keep the fence until all
  drains exit, including cancellation; a new generation starts after close
  returns. Redis fences publish/end and checks subscribe around cursor lookup.

## Checkpoints

- Channel mode is fixed for process lifetime; full readers reject delta state.
- Use `CheckpointStateAccessor` with the effective thread schema; preserve mode,
  parentage and pending writes.
- If pre-run snapshot capture fails, the first values frame sets replay baseline;
  only later message IDs determine LLM-error fallback.
- Delta resume/rollback rewrites the current head, not a fork. Reject missing
  tuples or pending sends before writing.
- Redis history purge includes the previous default namespace during v1→v2
  upgrade for the same DB identity; custom namespaces need operator migration.

## Admission and terminal commit

- Only the run-owning worker commits terminal state. Lost/expired leases fence
  later writes so recovery cannot be overwritten.
- Register completion before cleanup awaits; cancellation then remains safe and
  idempotent requests replay the stored result.
- Always finish terminal cleanup of streams, journals and graph references.
- Provider tool-call IDs are not ownership IDs; use server-generated execution
  IDs for registry, polling, cancellation and cleanup.

## Run events and journal

- Mutate `RunJournal` only on its owning event loop. Recorder failure fails open;
  slow recording must not delay tool state.
- Retry a sub-agent event batch only on `RunEventStoreNotCommittedError`. Drain
  writes before propagating cancellation. Retry only transient, definitely
  uncommitted writes; uncertain outcomes stop history writes to avoid duplicate
  steps. Close the SQL producer only after final flush confirms all writes.
- Usage replay may enrich a message, never add/remove one; providers may report
  the same model call twice.
- Per-thread event-store mutations share an asyncio and PostgreSQL fence. It
  serializes writers but does not distinguish old/new run incarnations.
- JSONL is single-process and splits only on LF. Started mutations drain through
  cancellation; save sequence watermark before deleting a run; corrupt
  watermark fails closed.
- In-memory store copies caller data at admission. Event reads use trusted user
  identity, matching the owner on durable RunRecord.
- Evidence receipts require the worker's own final acknowledgement; unknown or
  cancelled outcomes produce no receipt.

## Goals

Goal synthesis is read-only; the Gateway route owns persistence. The evaluator
uses PII redaction and the oneshot path, excludes evidence tool results, keeps
the newest turn within its 12,000-character budget (even for oversized pastes),
and caps summary compaction at half to preserve recent constraints.

## Server-installed capabilities

Capabilities are request-scoped and installed by the server (scheduler,
conversation reader, client hints). Caller-supplied copies are rejected in both
context carriers and never restored from checkpoints. Run metadata and hidden
messages are display data, not authority. Scheduled goals use a fresh thread
and are removed before terminal commit. Retry goal evaluation only for malformed
verdicts from normal model completion; other failures are final. A truncated
workspace snapshot cannot prove a file is absent.

# Authoritative Run terminal events

Date: 2026-10-19. Source baseline: `fee0cd0c180874325305e995197db99f03fa6a6f`.
Scope: owner-side terminal publication and evidence ordering. Recovery publication
and crash-gap reconciliation are separate work. Maintainer agreement on the
Issue solution path remains pending.

## Problem and Issue alignment

[Issue #5342](https://github.com/bytedance/deer-flow/issues/5342) originally asks
for an authoritative `run.end`. Current `run.end` instead reports each root
graph completion, with opaque graph outputs and `metadata.status="success"`.
One Gateway Run may invoke the graph more than once, and artifact delivery,
cancellation, or rollback may change its business outcome afterward.

The implementation adds `run.terminal` while preserving `run.end`. This changes
the Issue's original solution path while addressing its need for authoritative
Run evidence; it does not claim that redefining `run.end` has been accepted.
Before submitting a production implementation PR, explicitly synchronize this choice with the Issue or obtain maintainer
agreement, including whether retaining invocation-level `run.end` is acceptable.
No Issue comment has been posted as part of this local work.

[PR #5351](https://github.com/bytedance/deer-flow/pull/5351) supplies historical
failure scenarios, not an implementation to cherry-pick. Distinguish maintainer
findings from subsequent author responses claiming fixes and later review.
The author's reported validations are not local validation of this baseline
or this implementation; this work does not validate that historical branch.

This is a core runtime protocol concern, involving final ACK attribution and
Journal ordering. An extension lifecycle observer alone cannot enforce these
boundaries. Publication therefore belongs in core.

## Event contract

| Field | Definition |
| --- | --- |
| Event type | `run.terminal` |
| Category | `trace` |
| Identity | `(thread_id, run_id, event_type)` |
| Content | Exactly `{"status": <final Run status>}` in protocol version 1 |
| Status | `success`, `error`, `interrupted`, or `timeout` |
| Metadata | `protocol_version: 1`, `recovered: boolean` |
| Insertion | Run-scoped singleton, confirmed idempotently |
| Normal authority | Current local Run's final Terminal Commit ACK |
| Recovery authority | Successful atomic takeover; recovery publication requires a separate design |

```json
{
  "event_type": "run.terminal",
  "category": "trace",
  "content": {"status": "success"},
  "metadata": {"protocol_version": 1, "recovered": false}
}
```

The normal store envelope still supplies thread/run identity, sequence, time,
and backend-specific owner fields. Do not copy graph outputs, error strings,
credentials, or execution context into the payload. `recovered` identifies the
source of evidence; it grants no publication authority. The event records the
final business outcome. A Seal separately records evidence coverage.

The runtime catalog and formal JSON contract register this additive event
together. Legacy callback events retain their existing definitions.

## Invariants

### Status authority

The publisher must attribute the final ACK to the current Run and owner, with
the acknowledged final outcome still matching. Neither `on_chain_end`, a
same-status row read, a store-only hydrated record, nor a generic truthy store
return grants authority. `_has_final_terminal_ack()` rejects ownership
loss and rollback's intermediate `interrupted` ACK. A rollback may publish
only after restoration settles and its final `error` ACK is confirmed.

Recovery uses its own successful takeover result. Reading an already-terminal
historical row requires a separately defined compensation authorization; it
does not manufacture a new local commit proof. Recovery publication is not
implemented here.

### Evidence ordering

The normal sequence, while the existing finalizing barrier remains
held, is:

1. Finish callback-producing completion hooks and lifecycle observers.
2. Reuse `_stop_evidence_producers()` / `_drain_evidence()` to freeze producers
   and drain accepted Journal writes. Preserve existing cancellation,
   quarantine, and proven-not-committed retry behavior.
3. Validate final publication authority, then confirm the terminal singleton.
4. Capture the Evidence Receipt, then persist the Seal.
5. Release `finalizing` before publishing SSE END, preserving current admission.

All accepted, confirmed Journal evidence must precede a new terminal event.
UNKNOWN predecessors or unfinished drains prohibit publication in this
owner-side complete-tail protocol. Terminal confirmation must precede Receipt
capture; a later append cannot be represented as covered by an older Seal.
Retries may confirm an existing event without creating a later sequence.

`finish_evidence(before_receipt=...)` holds the Journal operation lock while
freezing/draining, invoking the worker's terminal confirmation, and capturing
the Receipt. Ordinary flush/close operations cannot detach or overtake this
sequence. Force close remains independent and causes bounds capture to fail,
including when it arrives during the Receipt read. Existing batch cancellation
and UNKNOWN quarantine handling remain in use.

### Backward compatibility

- Preserve legacy `run.start` / `run.end` producers, counts, categories,
  timing relative to graph callbacks, and opaque output serialization.
- Historical `sealed` evidence without `run.terminal` remains interpretable
  under its original contract. Do not relabel it corrupt or claim it meets
  the new terminal-event protocol merely because it is sealed.
- Consumers claiming new-protocol coverage must actually find and validate
  `run.terminal` inside the captured boundary. A global code upgrade or the
  existing Seal state alone is insufficient evidence of protocol adoption.
- Recovery evidence appended after a Seal is outside that original boundary.
  It cannot silently upgrade historical coverage; any new coverage revision
  belongs to a separately specified recovery protocol.

### Failure isolation

Publication/Seal failure must not rewrite an acknowledged business status.
An unconfirmed or conflicting terminal event cannot authorize a complete Seal
for the new protocol. A confirmed terminal event followed by Seal failure may
remain stored while coverage is partial. Do not delete or replay it blindly.

Missing events must not disable current missing-stream SSE or `/wait`
fallbacks, including Memory Event Store loss after restart. Terminal event
idempotence is independent of Redis END idempotence. Preserve next-message
admission immediately after END even when later cleanup is slow.

## Idempotent confirmation semantics

`confirm_terminal_event()` returns one of four confirmation outcomes:

| Outcome | Required observation | Caller behavior |
| --- | --- | --- |
| `CONFIRMED_NEW` | Store confirms insertion and returned identity, category, content status, and protocol version match | May proceed to Receipt capture |
| `CONFIRMED_EXISTING` | Stored event itself matches that identity, category, status, and version | Idempotent success; preserve the existing record |
| `CONFLICT` | Returned/stored identity or protocol fields contradict expectations, or required fields are malformed/missing | Fail closed, record conflict, do not overwrite or seal as complete |
| `UNKNOWN` | Operation outcome cannot be established | Preserve uncertainty; no blind replay or complete Seal |

Validate required field types as well as values; `recovered` must be boolean.
Its original source marker is preserved on confirmation rather than rewritten
by the retrier. Existing additional optional metadata is not a conflict merely
because it differs from the retrier's metadata. A same-status RunRow is never
an event ACK. `put_if_absent(...).created == False` alone proves neither success
nor conflict.

At most two atomic singleton attempts are made. An ACK-loss retry may become `CONFIRMED_EXISTING` only through the singleton's
atomic check/insert and matching record validation, while publication remains
authorized. It must not replay a quarantined Journal batch. A proven rejection
before insertion may be retried under the existing bounded retry policy;
eligibility failures before a write attempt do not constitute an ACK.

`CONFIRMED` means confirmation within the store's declared failure model:

| Backend | Boundary |
| --- | --- |
| Memory | One event loop/process lifetime; no persistence across restart |
| JSONL | Declared single-process mutation boundary; no multi-process guarantee |
| SQLite | Database-backed confirmation; this local reproduction uses one process |
| PostgreSQL | Database-backed confirmation; cross-instance contention needs real independent sessions/processes |

Singleton uniqueness does not make the RunRow commit and event insertion one
transaction. Crashing between them may leave a terminal row with no event.

## Deterministic reproduction scope

`backend/tests/test_run_terminal_protocol.py` drives the real `run_agent()`
finalizer, RunManager, SQLite RunRepository, DbRunEventStore, and Journal.
Offline graph doubles emit real root callbacks for controlled invocation
counts; the rollback test uses a compiled LangGraph and an actual in-memory checkpointer
for rollback restoration. The original seven tests observe real Worker output
without inserting synthetic terminal events. Additional conflict tests seed
pre-existing records to verify rejection. Every gate is released before bounded
cleanup.

| Test | Observed interleaving and required behavior |
| --- | --- |
| Repeated root completions | Two root completions retain two legacy output events; final ACK requires exactly one independent success terminal |
| Artifact delivery failure | Root completion succeeds; real artifact output exists; pause verification while row is running; unpresented output produces final error requiring an error terminal |
| Peer takeover | Pause owner terminal CAS, expire lease, win real takeover, resume rejected owner; check no unauthorized terminal, then require healthy owner publication |
| Rollback final ACK | Cancel real graph with rollback, stop before real restoration; interrupted proof is intermediate; restoration and final error ACK require an error terminal |
| Unknown Journal write | Persist a Journal batch but hold/lose its ACK; check no overtaking terminal, replay, or complete Seal; retain business status; then require healthy publication |
| Cross-thread callback | Hold an actually admitted cross-thread callback before owner-loop execution; freeze with pending producer; release callback and require its seq before terminal |
| Receipt and Seal boundary | Withhold terminal singleton ACK after commit and reject any Receipt entry before ACK; capture actual Receipt and pause before Seal; require terminal inside that original boundary |

The takeover and unknown-write cases execute refusal checks before a healthy
positive control, so absence of a publisher cannot make the overall test pass
vacuously. Callback and Receipt gates observe actual writes, their ACKs, and the
original boundary used by the Seal.

Additional Worker tests cover default single-worker operation, explicit commit
ACKs, ACK loss, conflicting existing events, malformed/unknown store returns,
cancellation, user ownership, and SSE/admission liveness. Event confirmation
contracts exercise Memory, JSONL, SQLite, and opt-in PostgreSQL. PostgreSQL
contention tests use independent connection pools and observe an actual waiting
advisory lock before allowing the first transaction to commit. Those results
establish singleton behavior at the event-store boundary; they do not prove
multi-Gateway recovery or exactly-once Redis END.

Single-worker status writes produce a terminal proof only on an explicit
successful write. A legacy `None` return or a read of a matching terminal row
continues to follow existing status-recovery semantics but cannot authorize a
new terminal event. With no backing RunStore, the local Manager transition is
authoritative within that process lifetime. Local status changes retain their
existing mutability; a newly staged outcome cannot use the earlier outcome's
proof, and a later accepted terminal transition replaces that local proof.

## Recovery audit and non-goals

Recovery publication must cover all of these entry points. This implementation
adds no recovery writes:

| Entry point | Boundary to cover |
| --- | --- |
| `RunManager.reconcile_orphaned_inflight_runs()` | Successful orphan takeover |
| `RunManager.cancel()` remote takeover | Expired owner lease |
| Same-thread interrupt/rollback atomic admission | Attributed replacement claims and any remaining old finalizer |
| `ScheduledTaskRepository.reconcile_stuck_once_tasks()` | Direct RunRepository takeover |
| `ScheduledTaskRunRepository.reconcile_active_runs()` | Separate direct RunRepository takeover |
| `RunRepository.recover_unsealed_evidence()` | Marks terminal evidence partial; does not publish an event |

Recovery must preserve user ownership, Redis producer leases, retained/missing
stream liveness, and independent END deduplication. No status-only terminal
scanner is authorized while a legal finalizer may still produce evidence.

A durable Outbox/reconciliation protocol is required if the project promises
eventual terminal evidence after every committed business outcome. An
owner-side best-effort mirror cannot make that guarantee. Lease, cancellation
arbitration, Scheduler, stream bridge, outbox, migration, and historical
backfill implementation are outside this change's scope.

## Validation

Run from `backend/` with the checkout's harness and extension API first on
`PYTHONPATH`:

```bash
PYTHONPATH=packages/harness:packages/extension-api:. uv run pytest \
  tests/test_run_terminal_protocol.py tests/test_terminal_event_confirmation.py \
  tests/test_run_event_stream_contract.py tests/test_run_journal.py \
  tests/test_run_event_store.py tests/test_run_worker_delivery.py \
  tests/test_run_worker_finalization_cancellation.py \
  tests/test_completed_run_evidence.py tests/test_gateway_run_recovery.py \
  tests/test_wait_disconnect_handling.py tests/test_multi_worker_run_ownership.py \
  tests/test_terminal_commit_authority.py tests/test_atomic_admission_authority.py \
  tests/test_atomic_admission_worker.py tests/test_terminal_store_contract.py \
  tests/test_scheduler_goal_runtime.py tests/test_scheduled_goal_handoff.py -q
```

Set `TEST_POSTGRES_URI` to a disposable real PostgreSQL database to include the
independent-pool contention contracts. The tests create and remove private
schemas; SQLite passes alone do not establish PostgreSQL concurrency behavior.

Before publication was implemented, all seven original Worker tests failed at
the missing `run.terminal` assertion, with zero setup or teardown errors.

Local validation on 2026-10-19 used the existing Python environment with imports
verified against this checkout:

- Focused suite above, including real temporary PostgreSQL: **914 passed,
  16 skipped, 1 warning**. Skips cover backend-specific cases on inapplicable
  stores. The warning is an existing Starlette test-client deprecation.
- Blocking I/O: **259 passed, 1 skipped, 3 setup errors**, matching the earlier
  baseline. All three errors are missing `quickjs` package metadata in workflow
  fixtures; they are environment blockers rather than behavioral failures.
- Ruff lint/format and diff whitespace checks passed.

No full-backend, real Redis recovery, or historical PR branch validation is
implied by these results.

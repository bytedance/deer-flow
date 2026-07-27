# Cross-worker run cancellation

Date: 2026-07-27  
Issue: [#3239](https://github.com/bytedance/deer-flow/issues/3239)

## Problem

In a multi-worker Gateway, a run is owned by one worker but any HTTP worker may
receive its cancellation request. Today `RunManager.cancel()` rejects a request
that lands on a non-owner while the owner's lease is valid. The API turns that
outcome into HTTP 409, so a normal load-balancer routing decision can make the
stop button fail. The durable run remains active and can then reject the next
message on the same thread.

The lease must remain the single-writer fencing mechanism: a cancellation
request must not let the receiving worker execute or finalize the run.

## Considered approaches

### Durable cancellation intent in the run store

Persist the first requested action on the active `runs` row. The owner observes
that intent while renewing its lease, then runs the existing local
interrupt/rollback path.

- Survives worker and Redis reconnects.
- Works across processes and Pods without routable worker identities.
- Preserves the active-run uniqueness and lease fencing boundaries.
- Adds a small schema change and bounds cancellation latency by the heartbeat
  interval.

### Redis Pub/Sub control messages

Publish cancellation directly to the owner process.

- Lower nominal latency.
- Pub/Sub delivery is not durable, so a reconnect or process race can lose the
  request.
- Couples run ownership to the stream-bridge implementation.

### Route cancellation to the owner

Expose worker addresses and proxy the request to `owner_worker_id`.

- Can cancel immediately.
- Requires service discovery and worker-level routing that Uvicorn processes do
  not provide portably.
- Makes load-balancer topology part of the runtime correctness contract.

## Decision

Use durable cancellation intent. Add nullable `cancel_requested_at` and
`cancel_action` columns to `runs`. The first accepted action wins, matching the
existing idempotent local cancellation behavior.

`RunStore.request_cancel()` atomically records the intent only while a row is
`pending` or `running`. `RunStore.renew_lease()` renews ownership and returns the
stored action in the same operation for the SQL store. The default method keeps
third-party stores source-compatible by wrapping the existing `update_lease()`
contract without an extra read; stock memory and SQL stores implement intent
observation.

## Runtime flow

1. A non-owner receives `interrupt` or `rollback`.
2. If the lease is past the takeover grace period, existing orphan takeover
   marks the run `error`.
3. Otherwise the receiver atomically records the cancellation intent and
   returns an accepted outcome.
4. The owner heartbeat renews the lease and reads the action.
5. The owner sets its process-local abort state, cancels the task when running,
   and persists the normal `interrupted` transition.
6. Existing worker finalization performs rollback when requested, publishes the
   final stream events and END, and leaves the durable row terminal.
7. Only after terminalization can the thread admit another active run.

If completion wins the race before the intent update, cancellation reports the
run as no longer cancellable. If the owner dies after accepting the request,
lease expiry and orphan reconciliation remain the terminal fallback.

## API behavior

- Local cancel and dead-owner takeover keep their existing 202 behavior.
- A live remote owner now produces 202 instead of routing-dependent 409.
- Repeated remote requests are idempotently accepted; the first action wins.
- `wait=true` waits on the existing cross-process stream bridge for owner
  finalization. A non-standard deployment without a cross-process bridge
  returns 202 rather than blocking on an unreachable local stream.
- The cancel-then-stream SDK endpoint subscribes to the shared stream after
  recording the request; without a cross-process bridge it also returns 202.

## Verification

Tests cover:

- request persistence and first-action-wins behavior in memory and SQL stores;
- two managers sharing a store, with the non-owner requesting cancellation and
  the owner heartbeat stopping its task;
- interrupt and rollback propagation;
- HTTP cancel no longer returning 409 solely because of worker routing;
- cancel-then-stream safe fallback without a cross-process bridge;
- existing lease takeover, fencing, idempotency, and single-worker behavior.
